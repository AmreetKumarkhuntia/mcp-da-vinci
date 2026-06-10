"""Frame capture: return the timeline frame at the playhead as MCP image content.

The grab includes everything as rendered — Fusion comp output, grades, all
tracks — so this is the visual-feedback half of the edit -> look -> adjust loop.
Runs through the gallery (GrabStill -> ExportStills -> read bytes -> cleanup).
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile

from mcp.server.fastmcp import Image

from resolve.app import mcp
from resolve.connection import (
    frame_to_timecode,
    get_current_project,
    get_current_timeline,
    get_resolve,
)

# SetCurrentTimecode is rejected on the fusion/media pages.
_TIMECODE_PAGES = {"cut", "edit", "color", "fairlight", "deliver"}


@mcp.tool()
def grab_frame(
    timecode: str | None = None,
    frame: int | None = None,
    max_width: int = 1280,
    jpeg_quality: int = 85,
) -> list:
    """Capture the current timeline frame as a JPEG image.

    Grabs at the playhead, or moves it first when ``timecode`` ("HH:MM:SS:FF")
    or ``frame`` (absolute timeline frame, see get_timeline_info) is given.
    Temporarily switches to the color page when the playhead must move while on
    the fusion/media pages, restoring the original page after. Returns the
    image plus {timecode, width, height} metadata.
    """
    try:
        from PIL import Image as PILImage
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for grab_frame: python.exe -m pip install pillow"
        ) from exc

    if timecode is not None and frame is not None:
        raise ValueError("Pass at most one of timecode / frame.")

    resolve = get_resolve()
    project = get_current_project()
    timeline = get_current_timeline()

    prev_page = resolve.GetCurrentPage()
    switched = False
    try:
        if frame is not None:
            timecode = frame_to_timecode(
                frame, float(timeline.GetSetting("timelineFrameRate"))
            )
        if timecode is not None:
            if prev_page not in _TIMECODE_PAGES:
                resolve.OpenPage("color")
                switched = True
            if not timeline.SetCurrentTimecode(timecode):
                raise RuntimeError(
                    f"SetCurrentTimecode({timecode!r}) failed — the target must lie "
                    "within the timeline (frame is the absolute timeline frame, "
                    "e.g. start_frame from get_timeline_info)."
                )

        still = timeline.GrabStill()
        if still is None and not switched:
            resolve.OpenPage("color")
            switched = True
            still = timeline.GrabStill()
        if still is None:
            raise RuntimeError(
                "GrabStill returned nothing — ensure a timeline is active and the "
                "playhead is over a clip."
            )

        album = project.GetGallery().GetCurrentStillAlbum()
        tmp_dir = tempfile.mkdtemp(prefix="resolve_grab_")
        try:
            if not album.ExportStills([still], tmp_dir, "grab", "jpg"):
                raise RuntimeError("Gallery ExportStills failed.")
            # Export also writes a .drx sidecar; the name pattern varies by version.
            jpgs = [f for f in os.listdir(tmp_dir) if f.lower().endswith(".jpg")]
            if not jpgs:
                raise RuntimeError("ExportStills produced no .jpg file.")
            with open(os.path.join(tmp_dir, jpgs[0]), "rb") as fh:
                raw = fh.read()
        finally:
            album.DeleteStills([still])
            shutil.rmtree(tmp_dir, ignore_errors=True)

        grabbed_at = timeline.GetCurrentTimecode()
    finally:
        if switched:
            resolve.OpenPage(prev_page)

    img = PILImage.open(io.BytesIO(raw))
    if img.width > max_width:
        img.thumbnail((max_width, 10**6), PILImage.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=jpeg_quality)

    return [
        Image(data=buf.getvalue(), format="jpeg"),
        {"timecode": grabbed_at, "width": img.width, "height": img.height},
    ]
