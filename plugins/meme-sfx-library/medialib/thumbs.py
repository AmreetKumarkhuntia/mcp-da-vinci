"""Thumbnails for visuals, waveform strips for audio.

Cache filenames are content-addressed — ``sha1(path|size|mtime)`` — so
invalidation needs no logic at all: edit a file and its key changes, leaving the
old entry orphaned. At ~5,000 items the whole cache is around 25 MB.

Waveforms are decoration rather than a feature: the median sound effect here is
under a second and renders as an identical blob at tile size, so the strip is
drawn faintly behind the name and the real affordance is instant audition.
"""

from __future__ import annotations

from pathlib import Path

from . import config
from .model import MediaItem

THUMB_W = 320
THUMB_H = 180
WAVE_W = 320
WAVE_H = 64
WAVE_RGB = (78, 201, 176)


def cache_path(item: MediaItem) -> Path:
    key = item.content_key
    suffix = "png" if item.kind == "audio" else "jpg"
    folder = config.thumbs_dir() / key[:2]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{key}.{suffix}"


def _seek_seconds(item: MediaItem) -> float:
    """Grab a frame a little way in — meme clips and green screens routinely
    open on black, so frame 0 makes a useless tile."""
    if item.duration and item.duration > 0:
        return min(0.5, item.duration * 0.25)
    return 0.0


def _render_video(item: MediaItem, target: Path) -> bool:
    import imageio_ffmpeg
    from PIL import Image

    seek = _seek_seconds(item)
    input_params = ["-ss", f"{seek:.2f}"] if seek > 0 else []
    gen = imageio_ffmpeg.read_frames(
        item.path, input_params=input_params, output_params=["-vframes", "1"]
    )
    try:
        meta = next(gen)
        raw = next(gen)
    finally:
        gen.close()

    width, height = meta["size"]
    image = Image.frombytes("RGB", (width, height), raw)
    image.thumbnail((THUMB_W, THUMB_H * 4), Image.LANCZOS)
    image.save(target, "JPEG", quality=80)
    return True


def _render_image(item: MediaItem, target: Path) -> bool:
    from PIL import Image

    with Image.open(item.path) as image:
        image.seek(0) if getattr(image, "n_frames", 1) > 1 else None
        image = image.convert("RGB")
        image.thumbnail((THUMB_W, THUMB_H * 4), Image.LANCZOS)
        image.save(target, "JPEG", quality=80)
    return True


def _render_waveform(item: MediaItem, target: Path) -> bool:
    import numpy as np
    import soundfile
    from PIL import Image, ImageDraw

    from .probe import silence_native_stderr

    with silence_native_stderr():
        data, _rate = soundfile.read(item.path, dtype="float32", always_2d=True)
    if data.size == 0:
        return False

    mono = np.abs(data).max(axis=1)
    buckets = min(WAVE_W, max(1, mono.size))
    # Trim the tail so the reshape divides evenly; losing <1 bucket of samples
    # is invisible at this resolution.
    usable = (mono.size // buckets) * buckets
    peaks = mono[:usable].reshape(buckets, -1).max(axis=1)
    peak = float(peaks.max()) or 1.0
    peaks = peaks / peak

    image = Image.new("RGBA", (WAVE_W, WAVE_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    middle = WAVE_H / 2
    step = WAVE_W / buckets
    for index, value in enumerate(peaks):
        half = max(0.5, value * (WAVE_H / 2 - 2))
        x = index * step
        draw.rectangle(
            [x, middle - half, x + max(1.0, step - 0.4), middle + half],
            fill=(*WAVE_RGB, 200),
        )
    image.save(target, "PNG")
    return True


_RENDERERS = {"video": _render_video, "image": _render_image, "audio": _render_waveform}


def ensure(item: MediaItem) -> Path | None:
    """Return a cached thumbnail path, rendering it if needed.

    Any failure returns None rather than raising: a corrupt file in a
    5,000-item library must cost one blank tile, not a crashed worker.
    """
    target = cache_path(item)
    if target.exists() and target.stat().st_size > 0:
        return target

    renderer = _RENDERERS.get(item.kind)
    if renderer is None:
        return None
    try:
        if renderer(item, target):
            return target
    except Exception:
        # Leave no half-written file behind to be trusted on the next run.
        target.unlink(missing_ok=True)
    return None


def cache_size_bytes() -> int:
    return sum(p.stat().st_size for p in config.thumbs_dir().rglob("*") if p.is_file())
