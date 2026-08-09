# Scribe — findings & friction log

Everything here was measured on this machine (Windows 11 + WSL2, RTX 5070 12 GB,
DaVinci Resolve 21.0.00048 **free**, `E:\Python\python.exe` 3.12.8). Don't
re-derive it. Where a number is missing, it hasn't been measured yet — say so
rather than guessing.

Sister document: `/home/amreet_khuntia/repos/stash/NOTES.md`. Scribe is a
deliberate near-clone of Stash's architecture, and several of its findings were
imported here as constraints rather than rediscovered.

---

## Slice 0 — the two gates

Both green. Details below, because *how* they went green is more useful than
the verdict.

### Gate 1: faster-whisper on the GPU, under Windows Python

`python.exe scripts/spike_asr.py --media "F:\recordings\1 heart\3.mkv" --start 2532 --dur 45`

```
ctranslate2 4.8.1          (identical to the version proven in the WSL venv)
cuda devices 1
compute types              bfloat16 float16 float32 int8 int8_bfloat16
                           int8_float16 int8_float32
model load                 1.4 s      (cuda, int8_float16)
generator returned         0.1 s      feature extraction + VAD
first segment              9.9 s
total                      11.1 s for 45 s of audio  =  4.0x realtime
result                     4 segments, 85 words, Hinglish, word-level p≈0.9–1.0
```

**The Blackwell question is settled: sm_120 works.** ctranslate2 4.8.1 decodes on
the RTX 5070 under native Windows, at the same version that works under WSL. The
`WslBackend` fallback in the plan is therefore not needed for correctness. It
stays in the design as a seam only, and should not be built until something
actually needs it.

### The CUDA trap, and why `cuda.py` exists

This is the finding worth the whole slice.

`pip install faster-whisper` gets you ctranslate2 but **not** the CUDA runtime,
and on Windows nothing points at it even after you install the wheels. What
makes it dangerous is where the failure lands:

| Check | Result |
|---|---|
| `ctranslate2.get_cuda_device_count()` | `1` ✅ |
| `get_supported_compute_types("cuda")` | includes `int8_float16` ✅ |
| `WhisperModel(..., device="cuda")` | loads in 1.5 s ✅ |
| `model.encode(...)`, first segment | ❌ `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded` |

Every cheap preflight passes on a setup that cannot decode one frame. **A CUDA
check that stops short of actually decoding is worthless.** `scribelib/cuda.py`
says this at the top; keep it there.

Fix, in two parts — both are required:

1. `python.exe -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"`
   (1.37 GB: cudnn 737 MB + cublas 553 MB + cuda_nvrtc 76 MB, pulled in
   automatically as a cublas dependency).
2. `os.add_dll_directory` over each `site-packages/nvidia/*/bin`. On Linux these
   wheels are found through RPATH; on Windows nothing points there, and since
   Python 3.8 a plain LoadLibrary no longer searches PATH for dependent DLLs.
   Installing the wheels alone **does not fix it** — verified, the error was
   byte-identical before and after the install.

Registered dirs on this machine:

```
E:\Python\Lib\site-packages\nvidia\cublas\bin
E:\Python\Lib\site-packages\nvidia\cudnn\bin
E:\Python\Lib\site-packages\nvidia\cuda_nvrtc\bin
```

### Gate 2: does it survive `--windowed`?

`python.exe scripts/spike_frozen.py --media "F:\recordings\1 heart\3.mkv"`

```
sys.stdout / sys.stderr were None for 4.4 s
ok   ffmpeg extract (1.0 MB)
ok   soundfile read (30.0s @ 16000 Hz, peak 0.950)
ok   model load (cuda, int8_float16)
ok   decode (53 words)
PASS
```

Imported wholesale from Stash's frozen-build bug: a `--windowed` PyInstaller
build sets `sys.stderr` to `None`, and a single `sys.stderr.flush()` inside a
helper — swallowed by a broad `except` several frames up — silently produced
zero waveforms in the shipped app while working perfectly under `python.exe`.
Testing it costs two lines instead of a 5-minute rebuild:

```python
sys.stderr = None
sys.stdout = None
```

Scribe passes today. It will keep passing only if two rules hold:

- **Every** `subprocess.run`/`Popen` passes `stdout=`/`stderr=` explicitly. A
  windowed process has no valid standard handles, and Windows hands
  `INVALID_HANDLE_VALUE` to children — which makes ffmpeg fail in ways that read
  as "your file is corrupt".
- Nothing in `scribelib` calls `print(..., file=sys.stderr)`. Diagnostics go
  through a caller-supplied `log()` callback; the CLI prints, the panel routes to
  `debug.log`.

---

## Traps that cost time, so they don't cost it twice

**A silent window will fake a pass.** The first gate-1 run used `--start 60` and
reported `segments 0, words 0` — no error, no CUDA complaint. The recording opens
with a silent intro, the VAD dropped the whole window, and `encode()` was
therefore never called, so the missing-cuBLAS failure never surfaced. A green-ish
"it ran and produced nothing" hid a hard failure one layer down. **Any ASR test
must assert a word count > 0**; `spike_asr.py` and `spike_frozen.py` both do.

Level survey of `F:\recordings\1 heart\3.mkv` (211 min), via
`ffmpeg -af volumedetect`:

| offset | mean | peak |
|---|---|---|
| 10.5 min | −23.0 dB | 0.0 dB |
| 42.2 min | −14.5 dB | 0.0 dB |
| 84.4 min | −18.6 dB | 0.0 dB |
| 126.6 min | −26.6 dB | −0.4 dB |
| 168.8 min | −48.5 dB | −15.0 dB |

t = 2532 s (42.2 min) is the standing test window.

**Time-to-first-word is ~10 s even on a 45-second clip**, and that is *decode*
latency, not extraction — `transcribe()` returned its generator in 0.1 s. On a
2-hour file the two-pass ffmpeg extract dominates instead and runs to minutes.
Both need a named phase in the UI or the panel reads as hung. This is the
measurement that justifies chunked mode (plan slice 10).

**ffmpeg's `-ss` before `-i` matters.** Seeking to 42 min in a 39 GB mkv and
pulling 45 s took 0.3 s warm / 2.8 s cold. With `-ss` after `-i` it decodes from
the start.

---

## Environment

`E:\Python\python.exe` 3.12.8 already had, before Scribe:

```
PySide6_Essentials 6.11.1   PySide6_Addons 6.11.1   numpy 2.4.2
soundfile 0.13.1            imageio-ffmpeg 0.6.0    pywin32 312
pyinstaller 6.22.0
```

`pip install faster-whisper` added: `faster-whisper 1.2.1`, `ctranslate2 4.8.1`,
`onnxruntime 1.28.0`, `tokenizers 0.23.1`, `huggingface-hub 1.27.0`,
`av 18.0.0`, `protobuf`, `flatbuffers`, `pyyaml`, `fsspec`, `filelock`,
`hf-xet`, and it upgraded `click` 8.2.1 → 8.4.2.

Two consequences:

- **`av` (PyAV) came along for free**, and it exposes structured stream metadata.
  This retires the "no ffprobe" risk in the plan — `imageio_ffmpeg` really does
  ship only `ffmpeg.exe` (verified: one binary,
  `imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe`), but stream enumeration
  can use PyAV instead of parsing banner text. Decide in slice 1; prefer PyAV.
- **The `click` upgrade broke an unrelated package**: `scenedetect 0.6.7.1`
  requires `click<8.3.0`. Nothing in Scribe uses either. Noted because it is the
  cost of sharing one system-wide Windows Python across tools — the same
  trade-off Stash made deliberately (no venv, because `.lnk`, `.bat` and
  Resolve's Scripts menu don't activate one).

### Model

`E:\models\whisper-hinglish-prime-ct2` — CTranslate2 `int8_float16`, **1.48 GB**
`model.bin`, a `whisper-large-v3` fine-tune (`Oriserve/Whisper-Hindi2Hinglish-Prime`)
with hand-patched `alignment_heads`. Files: `model.bin`, `config.json`,
`tokenizer.json`, `vocabulary.json`, `preprocessor_config.json`.

The `alignment_heads` patch is the most fragile thing in this setup — without it
word timestamps silently collapse to segment boundaries. `scribelib/models.py`
must warn loudly if `config.json` lacks it. Not yet implemented.

Hinglish decodes under `language="en"`, not `hi`. Confirmed in the gate output:
`Rank ke lie percentile kya?` came back romanised, `p=1.00`. Keep the rationale
comment when porting the `transcribe()` kwargs.

### Not usable

- `E:\models\huggingface` — HF safetensors snapshots; faster-whisper cannot load
  a local HF directory, only a CT2 conversion.
- `ggml-tiny.en.bin` — whisper.cpp format, no backend installed here.
- `E:\models\blobs` and `E:\models\manifests` are empty. No Ollama, no gguf, no
  local LLM anywhere on this machine. Irrelevant to ASR; noted so nobody looks.

---

## Test media

`F:\recordings\1 heart\3.mkv` — 39.8 GB, 211 min, **one** audio stream
(`Stream #0:1: Audio: aac (LC), 48000 Hz, stereo`).

Note it is *not* multi-track: the audio-stream picker cannot be exercised
against it. A genuine multi-track OBS recording is still needed as a fixture
before slice 1's `list_audio_streams()` can be called verified.

---

## TODO

- Find or record a multi-track OBS file; it is the only fixture that proves the
  stream picker.
- `scribelib/models.py` `alignment_heads` guard.
- Decide PyAV vs banner-parsing for stream enumeration (prefer PyAV).
- Measure time-to-first-word on a full 2-hour file, to size chunked mode.
