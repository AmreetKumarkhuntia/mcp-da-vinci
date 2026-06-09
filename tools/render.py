"""Render-queue tools: configure format/codec, queue jobs, start/stop, check status."""

from __future__ import annotations

from resolve.app import mcp
from resolve.connection import get_current_project


@mcp.tool()
def list_render_formats() -> dict:
    """Return available render formats mapped to their file extension."""
    return get_current_project().GetRenderFormats()


@mcp.tool()
def list_render_codecs(render_format: str) -> dict:
    """Return available codecs (description -> codec name) for a render format."""
    return get_current_project().GetRenderCodecs(render_format)


@mcp.tool()
def set_render_format_and_codec(render_format: str, codec: str) -> dict:
    """Set the current render format and codec.

    Use names from ``list_render_formats`` / ``list_render_codecs``.
    """
    if not get_current_project().SetCurrentRenderFormatAndCodec(render_format, codec):
        raise RuntimeError(
            f"Failed to set render format {render_format!r} / codec {codec!r}. "
            "Verify both against list_render_formats and list_render_codecs."
        )
    return {"format": render_format, "codec": codec}


@mcp.tool()
def add_render_job(target_dir: str, custom_name: str | None = None) -> dict:
    """Queue a render job for the current timeline.

    ``target_dir`` is the output directory on the Resolve machine (a Windows path).
    Returns the new job id.
    """
    project = get_current_project()
    settings: dict[str, str] = {"TargetDir": target_dir}
    if custom_name:
        settings["CustomName"] = custom_name
    if not project.SetRenderSettings(settings):
        raise RuntimeError(f"Failed to apply render settings: {settings}")

    job_id = project.AddRenderJob()
    if not job_id:
        raise RuntimeError(
            "Failed to add render job. Ensure a timeline is active and settings are valid."
        )
    return {"job_id": job_id, "target_dir": target_dir}


@mcp.tool()
def start_render(job_ids: list[str] | None = None) -> dict:
    """Start rendering. Renders the given job ids, or all queued jobs when omitted."""
    project = get_current_project()
    started = project.StartRendering(job_ids) if job_ids else project.StartRendering()
    if not started:
        raise RuntimeError("Failed to start rendering (no valid queued jobs?).")
    return {"rendering": True, "job_ids": job_ids or "all"}


@mcp.tool()
def stop_render() -> dict:
    """Stop any render currently in progress."""
    project = get_current_project()
    project.StopRendering()
    return {"rendering": project.IsRenderingInProgress()}


@mcp.tool()
def get_render_status(job_id: str) -> dict:
    """Return status and completion percentage for a render job id."""
    status = get_current_project().GetRenderJobStatus(job_id)
    if not status:
        raise RuntimeError(f"No status for job id {job_id!r} (unknown job?).")
    return {
        "job_id": job_id,
        "status": status.get("JobStatus"),
        "completion_percentage": status.get("CompletionPercentage"),
        "time_taken_seconds": status.get("TimeTakenToRenderInMs"),
    }
