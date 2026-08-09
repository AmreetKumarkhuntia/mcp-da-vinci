"""Entry point.

    python.exe -m panel                 # from the plugin folder
    python.exe panel\\__main__.py        # from anywhere (what the shortcut uses)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Works whether this is run as `-m panel`, as a bare script path, or from a
# PyInstaller bundle: put the plugin folder on sys.path so `stashlib` and
# `panel` resolve without an install step.
_PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from panel.app import MainWindow  # noqa: E402


def resource(name: str) -> Path:
    """Locate a bundled file, frozen or not.

    PyInstaller unpacks --add-data into sys._MEIPASS; a normal checkout keeps
    them next to this module.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        candidate = Path(bundle) / "panel" / name
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().with_name(name)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Stash")
    app.setOrganizationName("Stash")

    icon = resource("icon.ico")
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))

    style = resource("style.qss")
    if style.exists():
        app.setStyleSheet(style.read_text(encoding="utf-8"))

    if not os.environ.get("LOCALAPPDATA"):
        print(
            "warning: LOCALAPPDATA is unset — the index will be written under "
            "~/.cache instead of the Windows profile. Run this with Windows "
            "python.exe, not a WSL interpreter.",
            file=sys.stderr,
        )

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
