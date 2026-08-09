"""Cheap per-file metadata: duration for audio/video, dimensions for visuals.

Measured on this library: soundfile.info ~6 ms (it handles mp3, so audio needs
no ffmpeg at all), ffmpeg header read 60-170 ms, PIL open ~10 ms. At those
costs a full pass over ~5,000 files is well under a minute, which is why the
index does one eagerly in the background instead of probing lazily.
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import NamedTuple


@contextlib.contextmanager
def silence_native_stderr():
    """Mute file descriptor 2 for the duration of a probe pass.

    libmpg123 (under libsndfile) writes ID3 parse warnings directly to fd 2,
    not through Python, so they cannot be filtered with the logging module and
    they bury real output — a few hundred lines for this library. Redirect the
    descriptor itself. Process-global, so wrap the whole pass in one place
    rather than each worker.
    """
    try:
        saved = os.dup(2)
    except OSError:
        # No usable stderr to silence — nothing to do.
        yield
        return
    devnull = os.open(os.devnull, os.O_WRONLY)
    try:
        # sys.stderr is None in a --windowed PyInstaller build, so this must be
        # guarded: an AttributeError here escapes into the caller and takes the
        # whole render down. That is what silently killed audio waveforms (and
        # only audio) in the frozen app while they worked fine under Python.
        if sys.stderr is not None:
            sys.stderr.flush()
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(devnull)
        os.close(saved)


class Probe(NamedTuple):
    duration: float | None
    width: int | None
    height: int | None
    ok: bool


FAILED = Probe(None, None, None, False)


def probe_audio(path: str) -> Probe:
    try:
        import soundfile

        info = soundfile.info(path)
        return Probe(float(info.duration), None, None, True)
    except Exception:
        return FAILED


def probe_video(path: str) -> Probe:
    """Read only the ffmpeg header.

    ``read_frames`` yields a metadata dict first and decoded frames after, so
    taking one item and closing the generator gets duration and size without
    decoding any picture data.
    """
    try:
        import imageio_ffmpeg

        gen = imageio_ffmpeg.read_frames(path)
        try:
            meta = next(gen)
        finally:
            gen.close()
        size = meta.get("size") or (None, None)
        duration = meta.get("duration")
        return Probe(
            float(duration) if duration else None,
            int(size[0]) if size[0] else None,
            int(size[1]) if size[1] else None,
            True,
        )
    except Exception:
        return FAILED


def probe_image(path: str) -> Probe:
    try:
        from PIL import Image

        with Image.open(path) as img:
            width, height = img.size
            frames = getattr(img, "n_frames", 1)
        # An animated GIF/WebP is really a short video; keep a duration so the
        # tile can show one and the preview knows to loop it.
        duration = None
        if frames > 1:
            duration = frames / 10.0
        return Probe(duration, int(width), int(height), True)
    except Exception:
        return FAILED


_DISPATCH = {"audio": probe_audio, "video": probe_video, "image": probe_image}


def probe(path: str, kind: str) -> Probe:
    return _DISPATCH.get(kind, lambda _p: FAILED)(path)
