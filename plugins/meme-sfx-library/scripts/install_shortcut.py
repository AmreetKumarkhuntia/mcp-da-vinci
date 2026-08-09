"""Put the panel on the Desktop and in the Start Menu.

    python.exe scripts/install_shortcut.py            # create
    python.exe scripts/install_shortcut.py --remove   # undo

The shortcut targets pythonw.exe directly rather than run_panel.bat, so
launching it never flashes a console window. Pass --remove to clean up.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

NAME = "Meme & SFX Library.lnk"


def _targets() -> tuple[Path, Path, Path]:
    plugin_dir = Path(__file__).resolve().parent.parent
    entry = plugin_dir / "panel" / "__main__.py"
    icon = plugin_dir / "panel" / "icon.ico"
    return plugin_dir, entry, icon


def _locations() -> list[Path]:
    places: list[Path] = []
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    if desktop.is_dir():
        places.append(desktop)
    appdata = os.environ.get("APPDATA")
    if appdata:
        start = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if start.is_dir():
            places.append(start)
    return places


def create() -> int:
    try:
        from win32com.client import Dispatch
    except ImportError:
        print("pywin32 is required to create shortcuts:  pip install pywin32")
        return 1

    plugin_dir, entry, icon = _targets()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    shell = Dispatch("WScript.Shell")
    made = 0
    for folder in _locations():
        link = shell.CreateShortCut(str(folder / NAME))
        link.TargetPath = str(pythonw)
        link.Arguments = f'"{entry}"'
        # A UNC working directory is rejected by the shell; point at the user
        # profile and let __main__.py fix sys.path itself.
        link.WorkingDirectory = str(Path.home())
        link.Description = "Searchable meme & SFX library — drag into DaVinci Resolve"
        if icon.exists():
            link.IconLocation = str(icon)
        link.save()
        print(f"created  {folder / NAME}")
        made += 1

    if not made:
        print("Found neither a Desktop nor a Start Menu folder — nothing created.")
        return 1
    return 0


def remove() -> int:
    removed = 0
    for folder in _locations():
        link = folder / NAME
        if link.exists():
            link.unlink()
            print(f"removed  {link}")
            removed += 1
    if not removed:
        print("No shortcuts found.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remove", action="store_true", help="delete the shortcuts")
    args = parser.parse_args()
    return remove() if args.remove else create()


if __name__ == "__main__":
    raise SystemExit(main())
