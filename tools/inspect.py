"""Read-only tools: inspect the Resolve app, projects, timelines, media, renders."""

from __future__ import annotations

from resolve.app import mcp
from resolve.connection import (
    find_timeline_by_name,
    get_current_project,
    get_current_timeline,
    get_media_pool,
    get_project_manager,
    get_resolve,
)

_TRACK_TYPES = ("video", "audio", "subtitle")


@mcp.tool()
def get_resolve_info() -> dict:
    """Return DaVinci Resolve product name, version and the currently open page."""
    resolve = get_resolve()
    return {
        "product": resolve.GetProductName(),
        "version": resolve.GetVersionString(),
        "current_page": resolve.GetCurrentPage(),
    }


@mcp.tool()
def list_projects() -> list[str]:
    """List the project names in the current database folder."""
    return get_project_manager().GetProjectListInCurrentFolder()


@mcp.tool()
def get_current_project_info() -> dict:
    """Return name, timeline count and key settings of the currently open project."""
    project = get_current_project()
    return {
        "name": project.GetName(),
        "timeline_count": project.GetTimelineCount(),
        "frame_rate": project.GetSetting("timelineFrameRate"),
        "resolution": {
            "width": project.GetSetting("timelineResolutionWidth"),
            "height": project.GetSetting("timelineResolutionHeight"),
        },
    }


@mcp.tool()
def list_timelines() -> list[dict]:
    """List all timelines in the current project with their 1-based index."""
    project = get_current_project()
    current = project.GetCurrentTimeline()
    current_name = current.GetName() if current else None

    timelines = []
    for idx in range(1, project.GetTimelineCount() + 1):
        timeline = project.GetTimelineByIndex(idx)
        if timeline:
            name = timeline.GetName()
            timelines.append(
                {"index": idx, "name": name, "is_current": name == current_name}
            )
    return timelines


@mcp.tool()
def get_timeline_info(name: str | None = None) -> dict:
    """Return track layout, frame range and playhead of a timeline.

    Uses the named timeline, or the current timeline when ``name`` is omitted.
    """
    timeline = find_timeline_by_name(name) if name else get_current_timeline()

    tracks = {}
    for track_type in _TRACK_TYPES:
        count = timeline.GetTrackCount(track_type)
        tracks[track_type] = [
            {
                "index": i,
                "name": timeline.GetTrackName(track_type, i),
                "enabled": timeline.GetIsTrackEnabled(track_type, i),
            }
            for i in range(1, count + 1)
        ]

    return {
        "name": timeline.GetName(),
        "start_frame": timeline.GetStartFrame(),
        "end_frame": timeline.GetEndFrame(),
        "start_timecode": timeline.GetStartTimecode(),
        "current_timecode": timeline.GetCurrentTimecode(),
        "tracks": tracks,
    }


@mcp.tool()
def list_media_pool(folder: str | None = None) -> list[dict]:
    """List clips in a media-pool folder (the root folder when ``folder`` omitted).

    Returns each clip's name, type, duration and frame rate.
    """
    media_pool = get_media_pool()
    target = media_pool.GetRootFolder()

    if folder:
        match = next(
            (f for f in target.GetSubFolderList() or [] if f.GetName() == folder), None
        )
        if match is None:
            raise RuntimeError(f"No media-pool folder named {folder!r} under root.")
        target = match

    clips = []
    for clip in target.GetClipList() or []:
        clips.append(
            {
                "name": clip.GetName(),
                "type": clip.GetClipProperty("Type"),
                "duration": clip.GetClipProperty("Duration"),
                "fps": clip.GetClipProperty("FPS"),
            }
        )
    return clips


@mcp.tool()
def get_render_queue() -> list[dict]:
    """Return queued render jobs together with their current status."""
    project = get_current_project()
    jobs = []
    for job in project.GetRenderJobList() or []:
        job_id = job.get("JobId")
        status = project.GetRenderJobStatus(job_id) if job_id else {}
        jobs.append(
            {
                "job_id": job_id,
                "name": job.get("OutputFilename") or job.get("RenderJobName"),
                "target_dir": job.get("TargetDir"),
                "status": status.get("JobStatus"),
                "completion_percentage": status.get("CompletionPercentage"),
            }
        )
    return jobs
