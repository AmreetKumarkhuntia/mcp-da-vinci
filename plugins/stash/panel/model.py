"""A plain list model over the ranked search result.

Deliberately not a QSortFilterProxyModel: the search returns results in score
order, and a proxy can only accept or reject rows, never rank them. It would
also cross the C++/Python boundary once per row per keystroke, which is far
slower than scoring all 5,000 items in pure Python (single-digit milliseconds).
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt

from stashlib.model import MediaItem


class LibraryModel(QAbstractListModel):
    ItemRole = Qt.UserRole + 1

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[MediaItem] = []
        self._rows: dict[str, int] = {}

    def set_items(self, items: list[MediaItem]) -> None:
        self.beginResetModel()
        self._items = items
        self._rows = {item.path: row for row, item in enumerate(items)}
        self.endResetModel()

    def row_for_path(self, path: str) -> int:
        """-1 if that file is not in the current result set."""
        return self._rows.get(path, -1)

    def item_at(self, index) -> MediaItem | None:
        row = index.row() if hasattr(index, "row") else int(index)
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def items_at(self, indexes) -> list[MediaItem]:
        rows = sorted({i.row() for i in indexes})
        return [self._items[r] for r in rows if 0 <= r < len(self._items)]

    def refresh_row(self, row: int) -> None:
        if 0 <= row < len(self._items):
            index = self.index(row, 0)
            self.dataChanged.emit(index, index)

    # -------------------------------------------------- QAbstractListModel ---
    def flags(self, index):
        """Mark rows draggable.

        Load-bearing, and silent when missing: Qt only enters DraggingState if
        `selectedDraggableIndexes()` is non-empty, and that filters on
        Qt.ItemIsDragEnabled. The default flags are Enabled|Selectable, so
        without this the grid selects normally and simply never starts a drag —
        `startDrag()` is not called at all, with no error anywhere.
        """
        base = super().flags(index)
        if index.isValid():
            return base | Qt.ItemIsDragEnabled
        return base

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        item = self.item_at(index)
        if item is None:
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return item.stem
        if role == Qt.ToolTipRole:
            bits = [item.path]
            if item.duration:
                bits.append(f"{item.duration:.1f}s")
            if item.width and item.height:
                bits.append(f"{item.width}x{item.height}")
            if item.tags:
                bits.append(" ".join(sorted(item.tags)))
            return "\n".join(bits)
        if role == self.ItemRole:
            return item
        return None
