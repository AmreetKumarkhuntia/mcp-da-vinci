"""Phase-0 gate: does a Qt drag land in DaVinci Resolve?

Everything downstream (the whole panel) assumes Qt's QDrag produces a Windows
CF_HDROP that Resolve accepts, exactly like an Explorer drag. Prove it here
before writing product code.

    python.exe scripts/spike_drag.py

Drag each button onto Resolve and record what happens in the matrix printed at
startup. Kept in the repo permanently: when a Resolve update breaks drag, this
is the 10-second bisect.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Real files from the library. One video, one audio, one mixed multi-selection.
MEME = r"D:\videos\video making stuffs\meme\Meme Videos\HEHE BOI.mp4"
GREEN = r"D:\videos\video making stuffs\meme\Green Screen\3 2 1 GO COUNTDOWN.mp4"
HORN = r"D:\videos\sound\SFX Pack\Horn\Air Horn sound effect.mp3"

CASES: list[tuple[str, list[str]]] = [
    ("1 video  (HEHE BOI.mp4)", [MEME]),
    ("1 audio  (Air Horn.mp3)", [HORN]),
    ("3 mixed  (2 video + 1 audio)", [MEME, GREEN, HORN]),
]


def integrity_report() -> str:
    """Compare our integrity level against Resolve's.

    If Resolve runs at a higher level than us, Windows UIPI silently blocks the
    drag by design — which looks identical to "Resolve rejected the drop". This
    is the first thing to check when the gate fails.
    """
    try:
        import win32api
        import win32con
        import win32process
        import win32security
    except ImportError:
        return "integrity check skipped (pywin32 not importable)"

    names = {0x1000: "Low", 0x2000: "Medium", 0x3000: "High", 0x4000: "System"}
    QUERY_LIMITED = 0x1000

    def level(pid: int) -> int | None:
        try:
            handle = win32api.OpenProcess(QUERY_LIMITED, False, pid)
            token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
            sid, _ = win32security.GetTokenInformation(
                token, win32security.TokenIntegrityLevel
            )
            last = win32security.GetSidSubAuthorityCount(sid) - 1
            return win32security.GetSidSubAuthority(sid, last)
        except Exception:
            return None

    def describe(rid: int | None) -> str:
        if rid is None:
            return "unknown (access denied — likely higher than us)"
        return f"{names.get(rid, hex(rid))} ({hex(rid)})"

    ours = level(win32api.GetCurrentProcessId())

    resolve_pid = None
    for pid in win32process.EnumProcesses():
        try:
            handle = win32api.OpenProcess(QUERY_LIMITED, False, pid)
            exe = win32process.GetModuleFileNameEx(handle, 0)
        except Exception:
            continue
        if exe.lower().endswith("resolve.exe"):
            resolve_pid = pid
            break

    if resolve_pid is None:
        return f"panel={describe(ours)} · Resolve.exe NOT RUNNING — start it first"

    theirs = level(resolve_pid)
    verdict = "OK"
    if ours is not None and theirs is not None and theirs > ours:
        verdict = "*** UIPI WILL BLOCK THE DRAG — run both at the same level ***"
    elif theirs is None:
        verdict = "*** Resolve token unreadable — it is probably elevated, UIPI risk ***"
    return (
        f"panel={describe(ours)} · Resolve(pid {resolve_pid})={describe(theirs)} · {verdict}"
    )


def drag_pixmap(paths: list[str]) -> QPixmap:
    pixmap = QPixmap(180, 44)
    pixmap.fill(QColor("#1f6f8b"))
    painter = QPainter(pixmap)
    painter.setPen(QColor("white"))
    painter.setFont(QFont("Segoe UI", 9))
    label = paths[0].rsplit("\\", 1)[-1]
    if len(paths) > 1:
        label = f"{label}  ×{len(paths)}"
    painter.drawText(pixmap.rect().adjusted(8, 0, -8, 0), Qt.AlignVCenter, label)
    painter.end()
    return pixmap


class DragButton(QPushButton):
    def __init__(self, label: str, paths: list[str], dim: QCheckBox):
        super().__init__(label)
        self.paths = paths
        self.dim = dim
        self.setMinimumHeight(46)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in self.paths])
        mime.setText("\n".join(self.paths))  # belt-and-braces fallback format
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(drag_pixmap(self.paths))
        drag.setHotSpot(QPoint(20, 22))

        window = self.window()
        if self.dim.isChecked():
            window.setWindowOpacity(0.25)
        try:
            result = drag.exec(Qt.CopyAction | Qt.LinkAction, Qt.CopyAction)
        finally:
            window.setWindowOpacity(1.0)
        print(f"[drop] {len(self.paths)} file(s) -> action={result!r}", flush=True)


def main() -> int:
    print(__doc__)
    print("integrity:", integrity_report())
    print(
        "\nMatrix to fill in (drag each button onto each target):\n"
        "  target                     | 1 video | 1 audio | 3 mixed\n"
        "  Media Pool (Media page)    |         |         |\n"
        "  Media Pool (Edit page)     |         |         |\n"
        "  Timeline V1 (empty)        |         |         |\n"
        "  Timeline A1 (empty)        |         |         |\n"
        "\nNote: action=0 means the target refused the drop; action=1 means copy.\n"
    )

    app = QApplication(sys.argv)
    window = QWidget()
    window.setWindowTitle("drag spike -> Resolve")
    window.setWindowFlags(window.windowFlags() | Qt.WindowStaysOnTopHint)

    layout = QVBoxLayout(window)
    layout.addWidget(QLabel("Press and drag a button onto Resolve.\nWatch the console for the drop action."))

    dim = QCheckBox("Fade window to 25% while dragging (so you can see the target)")
    dim.setChecked(True)

    for label, paths in CASES:
        layout.addWidget(DragButton(label, paths, dim))
    layout.addWidget(dim)

    window.resize(380, 260)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
