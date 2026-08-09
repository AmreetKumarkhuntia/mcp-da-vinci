"""Build a distributable Setup.exe with install/uninstall support.

    python.exe scripts/build_installer.py              # app + installer
    python.exe scripts/build_installer.py --skip-app   # reuse the last app build

Runs PyInstaller first (via build_exe.py), then compiles installer/*.iss with
Inno Setup's command-line compiler. The result is a single file you can hand to
anyone: it installs per-user with no admin rights, adds Start Menu and optional
Desktop shortcuts, and registers a proper entry in Windows "Installed apps" so
it can be uninstalled the normal way.

Inno Setup is the only extra tool needed:  winget install JRSoftware.InnoSetup
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

def _iscc_candidates() -> list[Path]:
    roots = [
        Path(r"C:\Program Files (x86)"),
        Path(r"C:\Program Files"),
    ]
    # winget installs Inno Setup per-user by default, which puts it under
    # %LOCALAPPDATA%\Programs rather than Program Files.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        roots.insert(0, Path(local) / "Programs")
    return [root / f"Inno Setup {v}" / "ISCC.exe" for root in roots for v in (6, 7)]


def find_iscc() -> Path | None:
    for candidate in _iscc_candidates():
        if candidate.exists():
            return candidate
    from shutil import which

    found = which("ISCC.exe")
    return Path(found) if found else None


def app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or "."
    return Path(base) / "Stash" / "build" / "dist" / "Stash"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-app", action="store_true", help="reuse the existing app build")
    parser.add_argument("--outdir", type=Path, default=None)
    args = parser.parse_args()

    plugin_dir = Path(__file__).resolve().parent.parent
    script = plugin_dir / "installer" / "Stash.iss"

    iscc = find_iscc()
    if iscc is None:
        print(
            "Inno Setup not found. Install it with:\n"
            "    winget install JRSoftware.InnoSetup\n"
            "then run this again."
        )
        return 1

    if not args.skip_app:
        print("=== building the app with PyInstaller ===")
        result = subprocess.run([sys.executable, str(plugin_dir / "scripts" / "build_exe.py")])
        if result.returncode != 0:
            return result.returncode

    source = app_dir()
    if not (source / "Stash.exe").exists():
        print(f"App build not found at {source}. Run without --skip-app first.")
        return 1

    outdir = (args.outdir or (source.parent.parent / "installer")).resolve()
    outdir.mkdir(parents=True, exist_ok=True)

    print("\n=== compiling the installer ===")
    result = subprocess.run(
        [
            str(iscc),
            f"/DSourceDir={source}",
            f"/DOutputDir={outdir}",
            str(script),
        ]
    )
    if result.returncode != 0:
        print("\nInstaller compile failed — see the output above.")
        return result.returncode

    built = sorted(outdir.glob("Stash-Setup-*.exe"))
    if built:
        installer = built[-1]
        size = installer.stat().st_size / 1_000_000
        print(f"\nInstaller: {installer}  ({size:.0f} MB)")
        print("\nHand that single file to anyone. It installs per-user (no admin),")
        print("and uninstalls from Settings > Apps > Installed apps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
