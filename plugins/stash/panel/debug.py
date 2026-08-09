"""Opt-in diagnostics for the drag path.

Drag failures are silent by nature — the mouse just lets go and nothing
happens — and an exception raised inside a Qt event handler goes to stderr,
which is discarded when the app runs under pythonw or as a frozen .exe. So
when something is wrong, turn this on:

    set MEMESFX_DEBUG=1

or, when the launcher makes that awkward — a shortcut, a frozen .exe, or a
process started from WSL, where environment variables do NOT cross into
Windows — just create an empty marker file:

    %LOCALAPPDATA%\\Stash\\library\\debug.on

Writes to %LOCALAPPDATA%\\Stash\\library\\panel-debug.log. Off by
default and costs nothing when off.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path


def _folder() -> Path:
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    folder = Path(base) / "Stash" / "library"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def log_path() -> Path:
    return _folder() / "panel-debug.log"


def _enabled() -> bool:
    if os.environ.get("MEMESFX_DEBUG"):
        return True
    try:
        return (_folder() / "debug.on").exists()
    except Exception:
        return False


ENABLED = _enabled()


def log(message: str) -> None:
    if not ENABLED:
        return
    try:
        stamp = time.strftime("%H:%M:%S")
        with log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}  {message}\n")
    except Exception:
        pass  # diagnostics must never be the thing that breaks the app
