"""Build a standalone Stash.exe with PyInstaller.

    python.exe scripts/build_exe.py                 # build
    python.exe scripts/build_exe.py --outdir D:\\apps

Produces a one-folder app (~250 MB, mostly Qt) that runs on a machine with no
Python installed — hand someone the folder and they double-click the .exe.

Two things are easy to get wrong and are handled here:

* the source folder is usually a UNC path (\\\\wsl.localhost\\...), and
  PyInstaller's work/dist directories must NOT live there — it writes
  constantly and UNC makes that slow and lock-prone. Both default to a local
  temp/output path.
* imageio_ffmpeg's bundled ffmpeg.exe is data, not an import, so PyInstaller
  cannot discover it. It is added explicitly.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "Stash"


def _default_outdir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "Stash" / "build"


def ensure_pyinstaller() -> bool:
    try:
        import PyInstaller  # noqa: F401

        return True
    except ImportError:
        pass
    print("PyInstaller is not installed — installing it now...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "pyinstaller"]
    )
    return result.returncode == 0


def ffmpeg_binary() -> Path | None:
    try:
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=None, help="where to put the app")
    parser.add_argument("--onefile", action="store_true", help="single .exe (slower start)")
    args = parser.parse_args()

    if not ensure_pyinstaller():
        print("Could not install PyInstaller.")
        return 1

    plugin_dir = Path(__file__).resolve().parent.parent
    entry = plugin_dir / "panel" / "__main__.py"
    icon = plugin_dir / "panel" / "icon.ico"
    style = plugin_dir / "panel" / "style.qss"

    outdir = (args.outdir or _default_outdir()).resolve()
    workdir = outdir / "work"
    outdir.mkdir(parents=True, exist_ok=True)

    separator = ";" if os.name == "nt" else ":"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",  # no console window
        "--name", APP_NAME,
        "--distpath", str(outdir / "dist"),
        "--workpath", str(workdir),
        "--specpath", str(workdir),
        "--paths", str(plugin_dir),
        # style.qss is read at runtime from next to panel/, so it must ship.
        "--add-data", f"{style}{separator}panel",
        # Qt multimedia is loaded through plugins PyInstaller does not always see.
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "PySide6.QtMultimediaWidgets",
        "--hidden-import", "win32com.client",
        # Trim the biggest things nothing here uses.
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.Qt3DCore",
        "--exclude-module", "matplotlib",
        "--exclude-module", "tkinter",
    ]
    if args.onefile:
        command.append("--onefile")
    if icon.exists():
        command += ["--icon", str(icon)]

    ffmpeg = ffmpeg_binary()
    if ffmpeg and ffmpeg.exists():
        command += ["--add-binary", f"{ffmpeg}{separator}imageio_ffmpeg/binaries"]
    else:
        print("warning: imageio_ffmpeg binary not found — video thumbnails will not work")

    command.append(str(entry))

    print(f"building {APP_NAME} -> {outdir / 'dist'}")
    result = subprocess.run(command)
    if result.returncode != 0:
        print("\nBuild failed. The output above says why.")
        return result.returncode

    app = outdir / "dist" / APP_NAME
    print(f"\nBuilt: {app}")
    print(f"Run:   {app / (APP_NAME + '.exe')}")
    print("\nHand the whole folder to someone — no Python needed on their machine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
