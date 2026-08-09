"""The results grid — and the drag that is the whole point of the panel.

`startDrag` builds a QMimeData carrying file URLs, which Qt converts to a
Windows CF_HDROP: byte-for-byte what Explorer puts on the clipboard, and what
Resolve's Media Pool and timeline already know how to accept. Verified in
scripts/spike_drag.py; see docs/library-panel-notes.md.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtCore import QMimeData
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPixmap  # noqa: F401
from PySide6.QtWidgets import QAbstractItemView, QListView

from . import debug, theme
from .delegate import TileDelegate
from .model import LibraryModel


class ResultsView(QListView):
    auditionRequested = Signal(object)
    favoriteToggled = Signal(object)
    dragStarted = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._delegate = TileDelegate(self)
        self.setItemDelegate(self._delegate)

        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        # Movement stays at the default; DragOnly already prevents rearranging.
        self.setSpacing(2)
        # Uniform sizes make laying out thousands of rows O(1); batching keeps
        # the first paint immediate on a big result set.
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched)
        self.setBatchSize(120)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setDefaultDropAction(Qt.CopyAction)

        self.empty_message = ""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        model = self.model()
        if model is None or model.rowCount() or not self.empty_message:
            return
        # An empty grid with no explanation is the worst first-run experience
        # there is — say what to do instead of showing a void.
        painter = QPainter(self.viewport())
        painter.setPen(theme.MUTED)
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        painter.drawText(
            self.viewport().rect().adjusted(28, 28, -28, -28),
            Qt.AlignCenter | Qt.TextWordWrap,
            self.empty_message,
        )
        painter.end()

    def set_compact(self, compact: bool) -> None:
        self._delegate.compact = compact
        self.setGridSize(QSize())
        self.reset()
        self.scheduleDelayedItemsLayout()

    def selected_items(self) -> list:
        model = self.model()
        if not isinstance(model, LibraryModel):
            return []
        return model.items_at(self.selectedIndexes())

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.pos())
        debug.log(
            f"press at {event.pos().x()},{event.pos().y()} "
            f"index_valid={index.isValid()} row={index.row()} "
            f"dragEnabled={self.dragEnabled()} mode={self.dragDropMode()}"
        )
        super().mousePressEvent(event)

    # --------------------------------------------------------------- drag ---
    def startDrag(self, supportedActions) -> None:
        items = self.selected_items()
        debug.log(f"startDrag called, {len(items)} item(s) selected")
        if not items:
            return

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(item.path) for item in items])
        # Some targets take text but not URLs; costs nothing to offer both.
        mime.setText("\n".join(item.path for item in items))

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(items))
        drag.setHotSpot(QPoint(24, 20))

        window = self.window()
        # Fade the panel so the drop target underneath stays visible. Verified
        # not to interfere with the drag itself.
        window.setWindowOpacity(0.25)
        try:
            result = drag.exec(Qt.CopyAction | Qt.LinkAction, Qt.CopyAction)
            debug.log(f"drag.exec returned {result!r} for {items[0].path}")
        finally:
            window.setWindowOpacity(1.0)
        self.dragStarted.emit(len(items))

    def _drag_pixmap(self, items) -> QPixmap:
        label = items[0].stem
        if len(items) > 1:
            label = f"{label}  +{len(items) - 1}"
        font = QFont("Segoe UI", 9)
        metrics = QFontMetrics(font)
        width = min(280, metrics.horizontalAdvance(label) + 28)

        pixmap = QPixmap(width, 40)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 235))
        painter.drawRoundedRect(pixmap.rect().adjusted(0, 0, -1, -1), 6, 6)
        painter.setBrush(theme.kind_color(items[0].kind))
        painter.drawRoundedRect(4, 4, 4, 32, 2, 2)
        painter.setPen(theme.TEXT)
        painter.setFont(font)
        painter.drawText(
            pixmap.rect().adjusted(14, 0, -8, 0),
            Qt.AlignVCenter,
            metrics.elidedText(label, Qt.ElideMiddle, width - 22),
        )
        painter.end()
        return pixmap

    # ----------------------------------------------------------- keyboard ---
    def keyPressEvent(self, event) -> None:
        key = event.key()
        current = self.currentIndex()
        model = self.model()
        item = model.item_at(current) if isinstance(model, LibraryModel) else None

        if key == Qt.Key_Space and item is not None:
            self.auditionRequested.emit(item)
            event.accept()
            return
        if key in (Qt.Key_F,) and item is not None and not event.modifiers():
            self.favoriteToggled.emit(item)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        model = self.model()
        item = model.item_at(self.indexAt(event.pos())) if isinstance(model, LibraryModel) else None
        if item is not None:
            self.auditionRequested.emit(item)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
