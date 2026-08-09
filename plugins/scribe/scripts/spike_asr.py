"""Gate 1: does faster-whisper run on the GPU under WINDOWS Python?

Everything in Scribe's design assumes the answer is yes. The proven setup lives
in a WSL venv (ctranslate2 4.8.1 + faster-whisper 1.2.1, working), and the card
is a Blackwell RTX 5070 (sm_120) — a recent enough architecture that CUDA kernel
coverage is a real question, and one that says nothing about WSL vs Windows
until it is measured on both.

If this fails, nothing else in the plan changes except the default backend:
scribelib gets a WslBackend that runs the same `scribelib.cli` module through
wsl.exe. That is why this runs first and alone.

Run it:

    python.exe scripts/spike_asr.py --media "F:\\recordings\\1 heart\\3.mkv"

The single most useful thing this script does is NOT swallow the failure.
ctranslate2 reports missing cuDNN/cuBLAS by writing to fd 2 and then dying, and
that text is the whole diagnosis — so stderr is left alone here and every
exception is printed with its traceback.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scribelib import cuda  # noqa: E402  (must run before ctranslate2 is imported)

DEFAULT_MODEL = r"E:\models\whisper-hinglish-prime-ct2"

# Copied verbatim from transcribe_words.py — the voice-enhance chain the model
# was tuned against. Changing it changes accuracy, so the spike uses the real one.
ENHANCE_AF = "highpass=f=80, afftdn=nf=-25, dynaudnorm=g=7:m=15:p=0.9, alimiter=limit=0.95"


def rule(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 68 - len(title)))


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def list_audio_streams(media: Path) -> list[str]:
    """Audio stream lines from ffmpeg's banner.

    imageio_ffmpeg ships ffmpeg but NOT ffprobe (verified on this machine), so
    stream discovery has to come from `ffmpeg -i` stderr. Slice 1 turns this
    into a real parser; here it is just printed so we can see what OBS wrote.
    """
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(media)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    return [ln.strip() for ln in proc.stderr.splitlines() if re.search(r"Stream #\d+:\d+.*Audio:", ln)]


def extract(media: Path, out: Path, stream: int, start: float, dur: float) -> float:
    """Two-pass extract, same shape as transcribe_words.py.

    -ss before -i so seeking a 39 GB mkv is a keyframe jump, not a decode.
    Args are a list, never a shell string: this machine's user profile is
    'C:\\Users\\Amreet khuntia', with a space in it.
    """
    t0 = time.perf_counter()
    raw = out.with_name(out.stem + "_raw48.wav")
    subprocess.run(
        [ffmpeg_exe(), "-y", "-ss", str(start), "-t", str(dur), "-i", str(media),
         "-map", f"0:a:{stream}", "-ac", "1", "-ar", "48000", "-vn", str(raw)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    subprocess.run(
        [ffmpeg_exe(), "-y", "-i", str(raw), "-af", ENHANCE_AF,
         "-ac", "1", "-ar", "16000", str(out)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    raw.unlink(missing_ok=True)
    return time.perf_counter() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--media", required=True, help="a real recording, not a tone")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--stream", type=int, default=0, help="audio stream index (-map 0:a:N)")
    ap.add_argument("--start", type=float, default=60.0, help="seconds into the file")
    ap.add_argument("--dur", type=float, default=30.0)
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--compute", default="int8_float16")
    args = ap.parse_args()

    print(f"python      {sys.version.split()[0]}  {sys.executable}")

    rule("cuda dll search path")
    registered = cuda.register()
    for path in registered:
        print(f"registered {path}")
    if not registered:
        print(cuda.describe())

    rule("ctranslate2")
    try:
        import ctranslate2

        print(f"ctranslate2 {ctranslate2.__version__}")
        count = ctranslate2.get_cuda_device_count()
        print(f"cuda devices {count}")
        if count:
            print(f"compute types {sorted(ctranslate2.get_supported_compute_types('cuda'))}")
    except Exception:
        traceback.print_exc()
        print("\nFAIL: ctranslate2 did not import or could not see the GPU.")
        print("The traceback above is the diagnosis — do not summarise it away.")
        return 1

    rule("media")
    media = Path(args.media)
    if not media.exists():
        print(f"FAIL: no such file: {media}")
        return 1
    for line in list_audio_streams(media):
        print(line)

    model_dir = Path(args.model)
    if not (model_dir / "model.bin").exists():
        print(f"\nFAIL: no model.bin under {model_dir}")
        return 1

    with tempfile.TemporaryDirectory(prefix="scribe-spike-") as tmp:
        wav = Path(tmp) / "probe.wav"
        rule("extract")
        try:
            secs = extract(media, wav, args.stream, args.start, args.dur)
        except subprocess.CalledProcessError as exc:
            print(exc.stderr[-4000:] if exc.stderr else "(no stderr)")
            print("\nFAIL: ffmpeg extract. Wrong --stream index?")
            return 1
        print(f"{args.dur:.0f}s of audio -> {wav.stat().st_size/1e6:.1f} MB in {secs:.1f}s")

        rule("model load")
        from faster_whisper import WhisperModel

        t0 = time.perf_counter()
        try:
            model = WhisperModel(str(model_dir), device=args.device, compute_type=args.compute)
        except Exception:
            traceback.print_exc()
            print(f"\nFAIL: WhisperModel({args.device}, {args.compute}) would not load.")
            print("If this names cudnn64_9.dll / cublas64_12.dll, install the CUDA wheels:")
            print('  python.exe -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"')
            return 1
        load_s = time.perf_counter() - t0
        print(f"loaded in {load_s:.1f}s  ({args.device}, {args.compute})")

        rule("transcribe")
        t0 = time.perf_counter()
        try:
            segments, info = model.transcribe(
                str(wav),
                task="transcribe",
                language="en",
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(threshold=0.3, min_silence_duration_ms=200, speech_pad_ms=400),
                condition_on_previous_text=False,
                no_repeat_ngram_size=3,
                hallucination_silence_threshold=2.0,
            )
            # transcribe() returns before decoding starts; this is the eager
            # feature-extraction + VAD cost that slice 3 has to show a phase for.
            gen_s = time.perf_counter() - t0
            print(f"generator returned after {gen_s:.1f}s (feature extraction + VAD)")
            print(f"detected language {info.language!r} p={info.language_probability:.2f}")

            first_s = None
            n_seg = n_word = 0
            for seg in segments:
                if first_s is None:
                    first_s = time.perf_counter() - t0
                    print(f"first segment after {first_s:.1f}s")
                n_seg += 1
                words = seg.words or []
                n_word += len(words)
                if n_seg <= 3:
                    print(f"  [{seg.start:7.2f} {seg.end:7.2f}] {seg.text.strip()[:70]}")
                    for w in words[:4]:
                        print(f"      {w.start:7.2f} {w.end:7.2f}  p={w.probability:.2f}  {w.word!r}")
        except Exception:
            traceback.print_exc()
            print("\nFAIL: decoding raised.")
            return 1
        total_s = time.perf_counter() - t0

    rule("verdict")
    print(f"segments {n_seg}   words {n_word}   wall {total_s:.1f}s for {args.dur:.0f}s audio "
          f"({args.dur/total_s:.1f}x realtime)")
    if n_word == 0:
        print("FAIL: zero words. The model loaded but produced nothing.")
        return 1
    if not (model_dir / "config.json").exists():
        print("WARN: no config.json — alignment_heads cannot be checked.")
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
