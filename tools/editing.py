"""Timeline editing: split takes, drop the bad ones, transcribe, assemble rough cuts.

DaVinci Resolve 21 added the editing primitives this module needs natively:
- ``Timeline.DetectSceneCuts()`` splits one continuous recording into separate clips.
- ``Timeline.DeleteClips(items, ripple)`` removes clips and (with ripple) closes the gap.
- ``TimelineItem.SetClipEnabled(bool)`` mutes a take without deleting it.
So the "keep the good takes, drop the flubs" loop is native: ``detect_scene_cuts`` ->
``get_timeline_edl`` / ``transcribe_timeline`` + ``get_transcript`` to decide which clips
are bad -> ``delete_timeline_clips(ripple=True)``.

What v21 still lacks is an in-place blade/trim/slip setter for an arbitrary frame
(``TimelineItem`` exposes only ``Get*`` for its source/record ranges). To cut a bad span
out of the *middle* of one unbroken take you therefore still rebuild the kept ranges into
a fresh timeline with ``build_timeline_from_segments`` (which sets per-clip in/out via
``MediaPool.AppendToTimeline``). Rebuilding drops per-clip grades/Fusion/transitions, so
it stays a rough-cut tool, not a finishing tool.

ALL of these require Resolve **Studio** 21+: external scripting itself, plus
``DetectSceneCuts``, ``DeleteClips`` and ``CreateSubtitlesFromAudio``. The free edition
can't even open the scripting bridge (its fusionscript init fails). ``get_transcript``'s
caption-text accessor (``item.GetName()``) is still unverified against live captions —
confirm it once a Studio 21 connection is available.
"""

from __future__ import annotations

from resolve.app import mcp
from resolve.connection import (
    find_clips_by_name,
    frame_to_timecode,
    get_current_timeline,
    get_media_pool,
    get_resolve,
)


def _select_track_items(timeline, track, names, indices):
    """Resolve TimelineItems on a video track by name and/or 1-based position.

    Returns the matching items in track order; with neither ``names`` nor ``indices``
    returns every item on the track. Raises when a selector matches nothing so a
    cut/mute never silently hits the wrong set.
    """
    items = timeline.GetItemListInTrack("video", track) or []
    if not names and not indices:
        return list(items)
    wanted_names = set(names or [])
    wanted_idx = {int(i) for i in (indices or [])}  # CLI/MCP may pass these as strings
    chosen, seen = [], set()
    matched_names, matched_idx = set(), set()
    for pos, item in enumerate(items, start=1):
        nm = item.GetName()
        if pos not in wanted_idx and nm not in wanted_names:
            continue
        if id(item) not in seen:
            chosen.append(item)
            seen.add(id(item))
        if pos in wanted_idx:
            matched_idx.add(pos)
        if nm in wanted_names:
            matched_names.add(nm)
    missing_names = wanted_names - matched_names
    missing_idx = wanted_idx - matched_idx
    if missing_names or missing_idx:
        raise RuntimeError(
            f"No clips on video track {track} matched names={sorted(missing_names)} "
            f"indices={sorted(missing_idx)}. Track has {len(items)} clip(s): "
            f"{[it.GetName() for it in items]}."
        )
    return chosen


@mcp.tool()
def transcribe_timeline(language: str | None = None) -> dict:
    """Transcribe the current timeline's audio into a subtitle/caption track.

    Wraps Timeline.CreateSubtitlesFromAudio — requires Resolve **Studio** 21+ with the
    speech-to-text language model downloaded, and audio on the timeline. The resulting
    captions are read back (with timecodes) by get_transcript. Can take a while on long
    timelines.

    ``language`` is an optional auto-caption language name (e.g. "english", "auto",
    "korean"); it maps to the resolve.AUTO_CAPTION_* constant and is passed through the
    autoCaptionSettings dict. Omit it to let Resolve auto-detect the language.
    """
    timeline = get_current_timeline()
    settings = {}
    if language:
        resolve = get_resolve()
        key = getattr(resolve, "SUBTITLE_LANGUAGE", None)
        value = getattr(resolve, f"AUTO_CAPTION_{language.strip().upper()}", None)
        if key is None or value is None:
            raise ValueError(
                f"Unknown caption language {language!r}. Expected an auto-caption name "
                "like 'english', 'auto' or 'korean' (maps to resolve.AUTO_CAPTION_*); "
                "requires Resolve Studio 21+."
            )
        settings[key] = value
    ok = (
        timeline.CreateSubtitlesFromAudio(settings)
        if settings
        else timeline.CreateSubtitlesFromAudio()
    )
    if not ok:
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
def detect_scene_cuts() -> dict:
    """Auto-detect cut points and split the current timeline into separate clips.

    Wraps Timeline.DetectSceneCuts() (Resolve **Studio** 21+). Use it to break one
    continuous recording — e.g. several takes recorded back-to-back — into individual
    clips you can then drop with delete_timeline_clips. It finds hard cuts / scene
    changes; it won't find boundaries inside a single unbroken take. Reports the
    video-track-1 clip count before and after so you can see how many pieces it made.
    """
    timeline = get_current_timeline()
    before = len(timeline.GetItemListInTrack("video", 1) or [])
    if not timeline.DetectSceneCuts():
        raise RuntimeError(
            "DetectSceneCuts failed. Needs Resolve Studio 21+ and a timeline with "
            "detectable cuts on its media."
        )
    after = len(timeline.GetItemListInTrack("video", 1) or [])
    return {
        "timeline": timeline.GetName(),
        "track1_clips_before": before,
        "track1_clips_after": after,
    }


@mcp.tool()
def delete_timeline_clips(
    track: int = 1,
    names: list[str] | None = None,
    indices: list[int] | None = None,
    ripple: bool = True,
) -> dict:
    """Delete clips from the current timeline — the "drop the bad takes" primitive.

    Selects clips on video ``track`` by ``names`` and/or 1-based ``indices`` (position
    within the track), then removes them with Timeline.DeleteClips. ``ripple=True``
    (default) closes the gap so later clips shift left; ``ripple=False`` leaves a gap.
    Pass neither names nor indices to clear the whole track.

    DESTRUCTIVE and IN-PLACE — there is no undo over scripting. Prototype on a throwaway
    timeline (create_timeline) before touching real work. Requires Resolve **Studio** 21+.
    """
    timeline = get_current_timeline()
    items = _select_track_items(timeline, track, names, indices)
    before = len(timeline.GetItemListInTrack("video", track) or [])
    if not timeline.DeleteClips(items, ripple):
        raise RuntimeError(
            "DeleteClips failed (needs Resolve Studio 21+). Ensure the track isn't "
            "locked and the selected items are valid."
        )
    after = len(timeline.GetItemListInTrack("video", track) or [])
    return {
        "timeline": timeline.GetName(),
        "track": track,
        "deleted": len(items),
        "ripple": ripple,
        "clips_before": before,
        "clips_after": after,
    }


@mcp.tool()
def set_clip_enabled(
    enabled: bool,
    track: int = 1,
    names: list[str] | None = None,
    indices: list[int] | None = None,
) -> dict:
    """Enable or disable (mute) timeline clips without deleting them.

    The reversible alternative to delete_timeline_clips: SetClipEnabled(False) makes a
    take inert (no output) while leaving it on the timeline, so keep/drop decisions can
    be auditioned and undone. Selects clips on video ``track`` by ``names`` and/or
    1-based ``indices`` (all clips on the track if neither is given). Requires Resolve
    **Studio** 21+.
    """
    timeline = get_current_timeline()
    items = _select_track_items(timeline, track, names, indices)
    failed = [it.GetName() for it in items if not it.SetClipEnabled(enabled)]
    if failed:
        raise RuntimeError(f"SetClipEnabled({enabled}) failed for: {failed}")
    return {
        "timeline": timeline.GetName(),
        "track": track,
        "enabled": enabled,
        "count": len(items),
        "clips": [it.GetName() for it in items],
    }


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
