"""Background thumbnail generation for whatever is currently on screen.

Tasks emit a QImage, never a QPixmap: QPixmap may only be touched on the GUI
thread. The main thread converts and parks the result on the MediaItem itself,
which is shared across searches, so a thumbnail is built at most once per
session no matter how many queries surface the file.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage

from stashlib import thumbs
from stashlib.model import MediaItem


class _Signals(QObject):
    ready = Signal(str, object)  # path, QImage
    missed = Signal(str)


class _Task(QRunnable):
    def __init__(self, item: MediaItem, signals: _Signals) -> None:
        super().__init__()
        self.item = item
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            path = thumbs.ensure(self.item)
        except Exception:
            path = None
        if path is None:
            self.signals.missed.emit(self.item.path)
            return
        image = QImage(str(path))
        if image.isNull():
            self.signals.missed.emit(self.item.path)
            return
        self.signals.ready.emit(self.item.path, image)


class ThumbLoader(QObject):
    ready = Signal(str, object)

    def __init__(self, parent=None, max_threads: int = 4) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max_threads)
        self._signals = _Signals(self)
        self._signals.ready.connect(self._on_ready)
        self._signals.missed.connect(self._on_missed)
        self._inflight: set[str] = set()
        self._failed: set[str] = set()

    def request(self, items: list[MediaItem]) -> None:
        for item in items:
            if item.thumb is not None:
                continue
            if item.path in self._inflight or item.path in self._failed:
                continue
            self._inflight.add(item.path)
            self.pool.start(_Task(item, self._signals))

    def _on_ready(self, path: str, image: QImage) -> None:
        self._inflight.discard(path)
        self.ready.emit(path, image)

    def _on_missed(self, path: str) -> None:
        self._inflight.discard(path)
        # Remember failures so a corrupt file is not retried on every keystroke.
        self._failed.add(path)

    def shutdown(self) -> None:
        self.pool.clear()
        self.pool.waitForDone(2000)
