"""Make ctranslate2 able to find cuBLAS and cuDNN on Windows.

ctranslate2 does not vendor the CUDA runtime. The supported way to supply it is
the nvidia-* pip wheels, which on Linux are found through RPATH — and on Windows
land in ``site-packages/nvidia/<lib>/bin`` with nothing on any search path
pointing there. Since Python 3.8 a plain LoadLibrary no longer searches PATH for
dependent DLLs either, so the folders have to be registered explicitly with
``os.add_dll_directory``.

Measured on this machine, and the reason this module exists rather than a
comment in a README:

    ctranslate2.get_cuda_device_count()          -> 1        (looks fine)
    get_supported_compute_types("cuda")          -> int8_float16, ...  (fine)
    WhisperModel(..., device="cuda")             -> loads    (fine)
    model.encode(...)                            -> RuntimeError:
                                                    Library cublas64_12.dll is
                                                    not found or cannot be loaded

Every cheap check passes. **The failure only appears at the first encode**, so a
CUDA preflight that stops at "device count > 0" reports a green light on a setup
that cannot decode a single frame. Anything claiming to verify GPU support has
to actually decode something.

Call ``register()`` before importing ctranslate2 or faster_whisper.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The subfolders the nvidia-* wheels use. cuda_nvrtc is included because
# cublas depends on it; leaving it out produces the same error one layer down.
_NVIDIA_SUBDIRS = ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime")


def candidate_dirs(extra: tuple[str, ...] = ()) -> list[Path]:
    """Directories that might hold the CUDA DLLs, best first.

    ``extra`` comes from settings.json so a machine with a system CUDA install
    (or a hand-placed cuDNN) can point at it without reinstalling wheels.
    """
    found: list[Path] = []

    for raw in extra:
        path = Path(raw)
        if path.is_dir():
            found.append(path)

    for site in sys.path:
        nvidia = Path(site) / "nvidia"
        if not nvidia.is_dir():
            continue
        for sub in _NVIDIA_SUBDIRS:
            binary_dir = nvidia / sub / "bin"
            if binary_dir.is_dir():
                found.append(binary_dir)

    # Dedupe, keep order.
    seen: set[str] = set()
    unique: list[Path] = []
    for path in found:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def register(extra: tuple[str, ...] = ()) -> list[Path]:
    """Add the CUDA DLL folders to the search path. Returns what was added.

    Never raises. A machine with no GPU, or no wheels installed, gets an empty
    list and a CPU fallback — that is a supported configuration, not an error.
    """
    if not sys.platform.startswith("win"):
        return []

    added: list[Path] = []
    for path in candidate_dirs(extra):
        try:
            os.add_dll_directory(str(path))
        except OSError:
            continue
        added.append(path)

    # PATH is not consulted for dependent DLLs since 3.8, but cuDNN loads some
    # of its own siblings through mechanisms that still are. Cheap insurance.
    if added:
        os.environ["PATH"] = os.pathsep.join(
            [*(str(p) for p in added), os.environ.get("PATH", "")]
        )
    return added


def describe() -> str:
    """One-line human summary, for --version output and the panel's About box."""
    dirs = candidate_dirs()
    if not dirs:
        return "no CUDA wheel directories found (CPU only)"
    return f"{len(dirs)} CUDA dir(s): " + ", ".join(p.parent.name for p in dirs)
