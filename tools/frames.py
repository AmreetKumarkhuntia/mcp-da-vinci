"""Frame capture: return the timeline frame at the playhead as MCP image content.

The grab includes everything as rendered — Fusion comp output, grades, all
tracks — so this is the visual-feedback half of the edit -> look -> adjust loop.
Runs through the gallery (GrabStill -> ExportStills -> read bytes -> cleanup).
"""

from __future__ import annotations

import io
import math
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


def _grab_still_jpeg(project, timeline) -> bytes | None:
    """GrabStill at the playhead and return it as JPEG bytes via the gallery.

    Returns None when GrabStill itself yields nothing (typically a page that
    can't grab — the caller switches page and retries). Owns the gallery still
    and temp dir, cleaning both up even on error.
    """
    still = timeline.GrabStill()
    if still is None:
        return None
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
            return fh.read()
    finally:
        album.DeleteStills([still])
        shutil.rmtree(tmp_dir, ignore_errors=True)


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

        raw = _grab_still_jpeg(project, timeline)
        if raw is None and not switched:
            resolve.OpenPage("color")
            switched = True
            raw = _grab_still_jpeg(project, timeline)
        if raw is None:
            raise RuntimeError(
                "GrabStill returned nothing — ensure a timeline is active and the "
                "playhead is over a clip."
            )

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


@mcp.tool()
def grab_frames(
    frames: list[int],
    columns: int | None = None,
    tile_width: int | None = None,
    max_width: int = 1280,
    jpeg_quality: int = 85,
) -> list:
    """Capture several timeline frames into one labeled contact-sheet JPEG.

    Renders each absolute timeline ``frame`` (see get_timeline_info), tiles the
    grabs into a grid, and labels each with its frame number — one round-trip to
    review motion/timing instead of many single grabs. ``columns`` defaults to a
    near-square grid. The sheet is about ``max_width`` wide unless ``tile_width``
    is given (which sets the per-tile width and then overrides max_width). Max 16
    frames per call; render-heavy comps (high motion-blur Quality) make each grab
    slow, so batch accordingly.
    """
    try:
        from PIL import Image as PILImage
        from PIL import ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for grab_frames: python.exe -m pip install pillow"
        ) from exc

    if not frames:
        raise ValueError("Pass at least one frame.")
    if len(frames) > 16:
        raise ValueError(f"Too many frames ({len(frames)}); review in batches of <=16.")

    resolve = get_resolve()
    project = get_current_project()
    timeline = get_current_timeline()
    fps = float(timeline.GetSetting("timelineFrameRate"))

    columns = columns or math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / columns)
    if tile_width is None:
        tile_width = max(160, max_width // columns)

    prev_page = resolve.GetCurrentPage()
    switched = False
    grabs = []  # (frame, timecode, jpeg_bytes)
    try:
        if prev_page not in _TIMECODE_PAGES:
            resolve.OpenPage("color")
            switched = True
        for f in frames:
            timecode = frame_to_timecode(f, fps)
            if not timeline.SetCurrentTimecode(timecode):
                raise RuntimeError(
                    f"SetCurrentTimecode({timecode!r}) failed for frame {f} — the "
                    "target must lie within the timeline (absolute timeline frame, "
                    "e.g. start_frame from get_timeline_info)."
                )
            raw = _grab_still_jpeg(project, timeline)
            if raw is None:
                raise RuntimeError(f"GrabStill returned nothing at frame {f}.")
            grabs.append((f, timeline.GetCurrentTimecode(), raw))
    finally:
        if switched:
            resolve.OpenPage(prev_page)

    # Tile the grabs into a labeled contact sheet.
    tiles = []
    for f, _tc, raw in grabs:
        im = PILImage.open(io.BytesIO(raw)).convert("RGB")
        im.thumbnail((tile_width, 10**6), PILImage.Resampling.LANCZOS)
        tiles.append((f, im))
    cell_w = max(im.width for _, im in tiles)
    cell_h = max(im.height for _, im in tiles)
    pad = 4
    sheet = PILImage.new(
        "RGB",
        (columns * cell_w + (columns + 1) * pad, rows * cell_h + (rows + 1) * pad),
        (16, 16, 16),
    )
    try:
        font = ImageFont.truetype("arial.ttf", max(12, cell_w // 24))
    except Exception:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(sheet)
    for idx, (f, im) in enumerate(tiles):
        row, col = divmod(idx, columns)
        x = pad + col * (cell_w + pad)
        y = pad + row * (cell_h + pad)
        sheet.paste(im, (x, y))
        label = f"f{f}"
        bbox = draw.textbbox((0, 0), label, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.rectangle([x, y, x + tw + 8, y + th + 6], fill=(0, 0, 0))
        draw.text((x + 4, y + 3), label, fill=(255, 255, 255), font=font)

    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=jpeg_quality)
    return [
        Image(data=buf.getvalue(), format="jpeg"),
        {
            "frames": [f for f, _, _ in grabs],
            "timecodes": [tc for _, tc, _ in grabs],
            "grid": [columns, rows],
            "tile_size": [cell_w, cell_h],
            "width": sheet.width,
            "height": sheet.height,
        },
    ]
