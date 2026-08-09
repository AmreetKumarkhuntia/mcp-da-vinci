"""Search box and the kind filter."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLineEdit,
    QToolButton,
    QWidget,
)

KINDS: tuple[tuple[str, str | None], ...] = (
    ("All", None),
    ("Video", "video"),
    ("Audio", "audio"),
    ("Image", "image"),
)


class SearchBar(QLineEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("search your stash…")
        self.setClearButtonEnabled(True)
        self.setObjectName("searchBar")


class KindFilter(QWidget):
    kindChanged = Signal(object)  # str | None

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for position, (label, kind) in enumerate(KINDS):
            button = QToolButton(self)
            button.setText(label)
            button.setCheckable(True)
            button.setProperty("kind", kind)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"{label}  (Ctrl+{position + 1})")
            if kind is None:
                button.setChecked(True)
            self.group.addButton(button, position)
            layout.addWidget(button)

        self.group.idClicked.connect(self._emit)

    def _emit(self, button_id: int) -> None:
        self.kindChanged.emit(KINDS[button_id][1])

    def select(self, position: int) -> None:
        button = self.group.button(position)
        if button is not None:
            button.setChecked(True)
            self._emit(position)
