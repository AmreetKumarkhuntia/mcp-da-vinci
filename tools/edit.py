"""Mutation tools: import media, build timelines, add markers, switch pages."""

from __future__ import annotations

from resolve.app import mcp
from resolve.connection import (
    find_clips_by_name,
    find_timeline_by_name,
    frame_to_timecode,
    get_current_project,
    get_current_timeline,
    get_media_pool,
    get_resolve,
)

_PAGES = ("media", "cut", "edit", "fusion", "color", "fairlight", "deliver")


@mcp.tool()
def import_media(paths: list[str]) -> list[str]:
    """Import file/folder paths into the current media-pool folder.

    Paths must be valid on the machine running Resolve (Windows paths).
    Returns the names of the created media-pool clips.
    """
    items = get_media_pool().ImportMedia(paths)
    if not items:
        raise RuntimeError(
            "No media was imported. Check the paths exist and are valid media files."
        )
    return [item.GetName() for item in items]


@mcp.tool()
def create_timeline(name: str) -> dict:
    """Create a new empty timeline with the given name and make it current."""
    timeline = get_media_pool().CreateEmptyTimeline(name)
    if timeline is None:
        raise RuntimeError(
            f"Failed to create timeline {name!r} (the name may already be in use)."
        )
    return {"name": timeline.GetName()}


@mcp.tool()
def create_timeline_from_clips(name: str, clip_names: list[str]) -> dict:
    """Create a new timeline named ``name`` populated with the given media-pool clips."""
    clips = find_clips_by_name(clip_names)
    timeline = get_media_pool().CreateTimelineFromClips(name, clips)
    if timeline is None:
        raise RuntimeError(
            f"Failed to create timeline {name!r} (the name may already be in use)."
        )
    return {"name": timeline.GetName(), "clip_count": len(clips)}


@mcp.tool()
def append_clips_to_timeline(clip_names: list[str]) -> dict:
    """Append the named media-pool clips to the current timeline."""
    clips = find_clips_by_name(clip_names)
    appended = get_media_pool().AppendToTimeline(clips)
    if not appended:
        raise RuntimeError(
            "No clips were appended. Ensure a timeline is active and clips are valid."
        )
    return {"appended_count": len(appended)}


@mcp.tool()
def set_current_timeline(name: str) -> dict:
    """Make the named timeline the current/active timeline."""
    timeline = find_timeline_by_name(name)
    if not get_current_project().SetCurrentTimeline(timeline):
        raise RuntimeError(f"Failed to set {name!r} as the current timeline.")
    return {"current_timeline": name}


@mcp.tool()
def add_timeline_marker(
    frame: int,
    color: str = "Blue",
    name: str = "",
    note: str = "",
    duration: int = 1,
) -> dict:
    """Add a marker to the current timeline at ``frame`` (offset from timeline start).

    ``color`` is a Resolve marker color name (e.g. Blue, Cyan, Green, Yellow, Red,
    Pink, Purple, Fuchsia, Rose, Lavender, Sky, Mint, Lemon, Sand, Cocoa, Cream).
    """
    timeline = get_current_timeline()
    if not timeline.AddMarker(frame, color, name, note, duration, ""):
        raise RuntimeError(
            f"Failed to add marker at frame {frame} "
            "(a marker may already exist at that frame)."
        )
    return {"frame": frame, "color": color, "name": name}


@mcp.tool()
def insert_fusion_composition() -> dict:
    """Insert an empty Fusion Composition generator clip at the playhead.

    The blank canvas for from-scratch motion graphics (titles, lower thirds):
    no media needed — build its comp with the fusion_* tools afterwards.
    Duration follows the project's standard generator length (default 5s).
    """
    timeline = get_current_timeline()
    item = timeline.InsertFusionCompositionIntoTimeline()
    if item is None:
        raise RuntimeError(
            "InsertFusionCompositionIntoTimeline failed — ensure a timeline is "
            "active and the playhead is over empty track space (edit page)."
        )
    return {
        "clip": item.GetName(),
        "timeline_start_frame": item.GetStart(),
        "timeline_end_frame": item.GetEnd(),
    }


@mcp.tool()
def set_playhead(timecode: str | None = None, frame: int | None = None) -> dict:
    """Move the playhead to ``timecode`` ("HH:MM:SS:FF") or absolute ``frame``.

    ``frame`` uses the same basis as get_timeline_info's start_frame/end_frame
    (non-drop conversion; pass a timecode for drop-frame timelines). Rejected
    on the fusion/media pages — open_page("edit") first.
    """
    if (timecode is None) == (frame is None):
        raise ValueError("Pass exactly one of timecode / frame.")
    timeline = get_current_timeline()
    if frame is not None:
        timecode = frame_to_timecode(
            frame, float(timeline.GetSetting("timelineFrameRate"))
        )
    if not timeline.SetCurrentTimecode(timecode):
        raise RuntimeError(
            f"SetCurrentTimecode({timecode!r}) failed — it is rejected on the "
            "fusion/media pages (open_page('edit') first) and the target must "
            "lie within the timeline range."
        )
    return {"current_timecode": timeline.GetCurrentTimecode()}


@mcp.tool()
def open_page(page: str) -> dict:
    """Switch the Resolve UI to a page.

    One of: media, cut, edit, fusion, color, fairlight, deliver.
    """
    if page not in _PAGES:
        raise ValueError(f"Unknown page {page!r}. Must be one of {list(_PAGES)}.")
    if not get_resolve().OpenPage(page):
        raise RuntimeError(f"Failed to open page {page!r}.")
    return {"current_page": page}
