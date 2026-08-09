"""Gate 2: does the ASR path survive a --windowed PyInstaller build?

Stash lost a day to this exact class of bug. Audio waveforms rendered perfectly
under python.exe and produced *zero* files in the frozen app, because a
``--windowed`` build sets ``sys.stderr`` to None, a helper called
``sys.stderr.flush()``, and the resulting AttributeError was swallowed by a
broad ``except`` several frames up and turned into "no result". See
stash/NOTES.md, "The frozen-build bug".

Scribe is far more exposed than Stash was: ctranslate2, ffmpeg and onnxruntime
all write to fd 2, and the ASR path shells out to a subprocess. In a windowed
build the process has no valid standard handles at all, and Windows hands
INVALID_HANDLE_VALUE down to children — which makes ffmpeg fail in ways that
read as "your file is corrupt".

Rather than rebuild the app to find out (5 minutes a cycle), NOTES.md's own
prescription is two lines:

    sys.stderr = None
    sys.stdout = None

That is what --windowed does. This script does it, then runs the real thing.

    python.exe scripts/spike_frozen.py --media "F:\\recordings\\...\\3.mkv"

Everything it needs to report has to be buffered and printed at the very end,
after the streams are restored — because while the test is running there is
nowhere to print to. That constraint is the point: any code that assumes it can
print is code that breaks in the shipped artifact.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scribelib import cuda  # noqa: E402

DEFAULT_MODEL = r"E:\models\whisper-hinglish-prime-ct2"
ENHANCE_AF = "highpass=f=80, afftdn=nf=-25, dynaudnorm=g=7:m=15:p=0.9, alimiter=limit=0.95"

log: list[str] = []


def note(message: str) -> None:
    log.append(message)


def run_under_null_streams(media: Path, model_dir: Path, stream: int,
                           start: float, dur: float) -> bool:
    """The whole ASR path with no usable std streams. Returns ok."""
    import imageio_ffmpeg
    from faster_whisper import WhisperModel

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with tempfile.TemporaryDirectory(prefix="scribe-frozen-") as tmp:
        raw = Path(tmp) / "raw48.wav"
        wav = Path(tmp) / "probe.wav"

        # Hazard 1: a child process inheriting invalid handles. Every
        # subprocess call in scribelib must pipe explicitly for this reason.
        try:
            subprocess.run(
                [ffmpeg, "-y", "-ss", str(start), "-t", str(dur), "-i", str(media),
                 "-map", f"0:a:{stream}", "-ac", "1", "-ar", "48000", "-vn", str(raw)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
            subprocess.run(
                [ffmpeg, "-y", "-i", str(raw), "-af", ENHANCE_AF,
                 "-ac", "1", "-ar", "16000", str(wav)],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
            )
        except Exception:
            note("FAIL ffmpeg extract under null streams:\n" + traceback.format_exc())
            return False
        note(f"ok   ffmpeg extract ({wav.stat().st_size/1e6:.1f} MB)")

        # Hazard 2: a soundfile/numpy read. Stash's actual bug lived here.
        try:
            import numpy as np
            import soundfile as sf

            data, rate = sf.read(str(wav), dtype="float32")
            note(f"ok   soundfile read ({len(data)/rate:.1f}s @ {rate} Hz, "
                 f"peak {float(np.abs(data).max()):.3f})")
        except Exception:
            note("FAIL soundfile read under null streams:\n" + traceback.format_exc())
            return False

        # Hazard 3: ctranslate2 loading CUDA, which reports failure on fd 2.
        try:
            model = WhisperModel(str(model_dir), device="cuda", compute_type="int8_float16")
        except Exception:
            note("FAIL model load under null streams:\n" + traceback.format_exc())
            return False
        note("ok   model load (cuda, int8_float16)")

        # Hazard 4: decoding. This is where the missing-cuBLAS error surfaced,
        # and where the frozen build is most likely to differ.
        try:
            segments, _info = model.transcribe(
                str(wav), task="transcribe", language="en", word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(threshold=0.3, min_silence_duration_ms=200,
                                    speech_pad_ms=400),
                condition_on_previous_text=False, no_repeat_ngram_size=3,
                hallucination_silence_threshold=2.0,
            )
            words = sum(len(seg.words or []) for seg in segments)
        except Exception:
            note("FAIL decode under null streams:\n" + traceback.format_exc())
            return False

        if words == 0:
            note("FAIL decode produced zero words (pick a window with speech)")
            return False
        note(f"ok   decode ({words} words)")
        return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--media", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--stream", type=int, default=0)
    ap.add_argument("--start", type=float, default=2532.0)
    ap.add_argument("--dur", type=float, default=30.0)
    args = ap.parse_args()

    media, model_dir = Path(args.media), Path(args.model)
    if not media.exists():
        print(f"no such file: {media}")
        return 1

    cuda.register()

    real_out, real_err = sys.stdout, sys.stderr
    # Anything that writes to the *file descriptors* rather than to the Python
    # objects still needs somewhere to go, or it kills the process outright.
    sink = io.StringIO()
    ok = False
    t0 = time.perf_counter()
    try:
        sys.stdout = None  # type: ignore[assignment]
        sys.stderr = None  # type: ignore[assignment]
        try:
            ok = run_under_null_streams(media, model_dir, args.stream, args.start, args.dur)
        except BaseException:  # noqa: BLE001 - restore the streams no matter what
            sys.stdout, sys.stderr = real_out, real_err
            note("FAIL unexpected:\n" + traceback.format_exc())
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    elapsed = time.perf_counter() - t0
    _ = sink

    print(f"sys.stdout / sys.stderr were None for {elapsed:.1f}s\n")
    for line in log:
        print(line)
    print("\nPASS" if ok else "\nFAIL — this WILL break the frozen build; fix before slice 8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
