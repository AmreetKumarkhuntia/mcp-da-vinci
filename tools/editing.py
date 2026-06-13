"""Text-based / assembly editing: transcribe, read the cut, rebuild from segments.

Resolve's scripting API cannot trim, blade, slip or move a clip that is already
on the timeline (TimelineItem exposes only Get* for source/record ranges — no
resize). So "editing" here is **assembly**: read the timeline's edit decisions
(each clip's source in/out + position), or transcribe the audio, decide which
ranges to keep, then *rebuild* the kept segments into a fresh timeline via
MediaPool.AppendToTimeline (which accepts per-clip in/out + record position).

This is the backbone for transcript-driven rough cuts ("keep the good takes,
drop the flubs"): transcribe_timeline -> get_transcript -> pick keep-ranges ->
build_timeline_from_segments. Rebuilding drops per-clip grades/Fusion/transitions
(clipInfo can't carry them) — it is a rough-cut tool, not a finishing tool.

NOTE: transcribe_timeline needs DaVinci Resolve Studio with the speech-to-text
model installed. These tools are dependency-free (Resolve-native) but the
end-to-end loop has not been exercised against real footage yet.
"""

from __future__ import annotations

from resolve.app import mcp
from resolve.connection import (
    find_clips_by_name,
    frame_to_timecode,
    get_current_project,
    get_current_timeline,
    get_media_pool,
)


@mcp.tool()
def transcribe_timeline() -> dict:
    """Transcribe the current timeline's audio into a subtitle/caption track.

    Wraps Timeline.CreateSubtitlesFromAudio — requires Resolve **Studio** with the
    speech-to-text language model downloaded, and audio on the timeline. The
    resulting captions are read back (with timecodes) by get_transcript. Can take
    a while on long timelines.
    """
    timeline = get_current_timeline()
    if not timeline.CreateSubtitlesFromAudio():
        raise RuntimeError(
            "CreateSubtitlesFromAudio failed. Checklist: (1) this is Resolve "
            "Studio; (2) the speech-to-text model is installed (Resolve > "
            "Preferences, or it downloads on first use); (3) the timeline has "
            "audio with speech."
        )
    return {
        "timeline": timeline.GetName(),
        "subtitle_tracks": timeline.GetTrackCount("subtitle"),
    }


@mcp.tool()
def get_transcript() -> dict:
    """Read the timeline's caption/subtitle segments as timestamped text.

    Returns one entry per caption: ``{index, start_frame, end_frame, start_tc,
    end_tc, text}`` (frames are absolute timeline frames; map keep-ranges back to
    source clips with get_timeline_edl, then rebuild via
    build_timeline_from_segments). Run transcribe_timeline first if there are no
    captions yet.
    """
    timeline = get_current_timeline()
    fps = float(timeline.GetSetting("timelineFrameRate"))
    track_count = timeline.GetTrackCount("subtitle")
    segments = []
    for track in range(1, track_count + 1):
        for item in timeline.GetItemListInTrack("subtitle", track) or []:
            start, end = item.GetStart(), item.GetEnd()
            segments.append(
                {
                    "track": track,
                    "start_frame": start,
                    "end_frame": end,
                    "start_tc": frame_to_timecode(start, fps),
                    "end_tc": frame_to_timecode(end, fps),
                    # Subtitle items surface their caption text as the item name.
                    "text": item.GetName(),
                }
            )
    segments.sort(key=lambda s: s["start_frame"])
    if not segments:
        raise RuntimeError(
            "No caption segments found. Run transcribe_timeline first (or add a "
            "subtitle track)."
        )
    return {"timeline": timeline.GetName(), "count": len(segments), "segments": segments}


@mcp.tool()
def get_timeline_edl() -> dict:
    """Read every clip's edit decisions: source in/out, record position, track.

    The data needed to rebuild (or re-cut) a timeline by assembly. Per clip:
    ``{track, name, media_pool_item, source_in, source_out, record_start,
    record_end}``. ``media_pool_item`` is None for generators/titles (not
    media-backed — they can't be reassembled via build_timeline_from_segments).
    """
    timeline = get_current_timeline()
    clips = []
    for track in range(1, timeline.GetTrackCount("video") + 1):
        for item in timeline.GetItemListInTrack("video", track) or []:
            mpi = item.GetMediaPoolItem()
            clips.append(
                {
                    "track": track,
                    "name": item.GetName(),
                    "media_pool_item": mpi.GetName() if mpi else None,
                    "source_in": item.GetSourceStartFrame(),
                    "source_out": item.GetSourceEndFrame(),
                    "record_start": item.GetStart(),
                    "record_end": item.GetEnd(),
                }
            )
    return {"timeline": timeline.GetName(), "count": len(clips), "clips": clips}


@mcp.tool()
def build_timeline_from_segments(
    name: str,
    clip_names: list[str],
    source_in: list[int],
    source_out: list[int],
    track_index: int = 1,
) -> dict:
    """Build a new timeline from trimmed segments (the assembly/rough-cut primitive).

    Parallel lists define each segment: ``clip_names[i]`` is a media-pool clip,
    trimmed to source frames ``source_in[i]``..``source_out[i]`` (source-clip
    frames, not timeline frames). Segments are appended in order onto video track
    ``track_index`` of a fresh timeline ``name``. This is how you "cut" via
    scripting — assemble pre-trimmed pieces — since clips already on a timeline
    can't be trimmed in place.

    A clip may repeat across segments (e.g. keep three good ranges of one long
    take). Grades/Fusion comps/transitions are NOT carried over (clipInfo can't
    express them) — rough cut only.
    """
    if not (len(clip_names) == len(source_in) == len(source_out)) or not clip_names:
        raise ValueError(
            "clip_names, source_in and source_out must be equal-length, non-empty lists."
        )
    media_pool = get_media_pool()
    # Resolve each distinct name once; reuse the MediaPoolItem across segments.
    unique = list(dict.fromkeys(clip_names))
    items = dict(zip(unique, find_clips_by_name(unique)))

    timeline = media_pool.CreateEmptyTimeline(name)
    if timeline is None:
        raise RuntimeError(
            f"Failed to create timeline {name!r} (the name may already be in use)."
        )

    clip_infos = [
        {
            "mediaPoolItem": items[clip_names[i]],
            "startFrame": int(source_in[i]),
            "endFrame": int(source_out[i]),
            "trackIndex": track_index,
        }
        for i in range(len(clip_names))
    ]
    appended = media_pool.AppendToTimeline(clip_infos)
    if not appended:
        raise RuntimeError(
            "AppendToTimeline added no clips. Check that source_in < source_out are "
            "within each clip's range and the clips have the requested media type."
        )
    return {
        "timeline": timeline.GetName(),
        "segments_requested": len(clip_names),
        "segments_appended": len(appended),
    }
