"""System-wide hotkey to summon the panel over Resolve.

Uses RegisterHotKey with a NULL window handle, so WM_HOTKEY is posted to the
thread queue and Qt hands it to a native event filter. Registering the hotkey
is also what earns the process the right to call SetForegroundWindow when it
fires — Windows otherwise refuses foreground steals.

Registration can legitimately fail (another app owns the combination). That is
reported, never fatal: the panel is perfectly usable without it.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

DEFAULT_ID = 0xA71
DEFAULT_MODS = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT
DEFAULT_VK = 0x4D  # 'M'
DEFAULT_LABEL = "Ctrl+Shift+M"


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    triggered = Signal()

    def __init__(self, parent=None) -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        self.registered = False
        self._id = DEFAULT_ID

    def register(self, app) -> bool:
        try:
            ok = ctypes.windll.user32.RegisterHotKey(
                None, self._id, DEFAULT_MODS, DEFAULT_VK
            )
        except Exception:
            ok = False
        if ok:
            app.installNativeEventFilter(self)
            self.registered = True
        return self.registered

    def unregister(self) -> None:
        if not self.registered:
            return
        try:
            ctypes.windll.user32.UnregisterHotKey(None, self._id)
        except Exception:
            pass
        self.registered = False

    def nativeEventFilter(self, event_type, message):  # noqa: D102 - Qt override
        if event_type == b"windows_generic_MSG":
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_HOTKEY and msg.wParam == self._id:
                self.triggered.emit()
                return True, 0
        return False, 0


def bring_to_front(window) -> None:
    """Restore, raise and focus. Called from the hotkey handler, where the
    process is briefly permitted to take the foreground."""
    window.showNormal()
    window.raise_()
    window.activateWindow()
    try:
        ctypes.windll.user32.SetForegroundWindow(int(window.winId()))
    except Exception:
        pass
