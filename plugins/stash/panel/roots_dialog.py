"""The `+` folder manager.

Roots are user state, not configuration: add a folder here and it is indexed on
the next rescan. Removing one drops its items but deliberately leaves
`user_meta` alone, so re-adding the folder brings favourites and tags back.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class RootsDialog(QDialog):
    def __init__(self, library, parent=None) -> None:
        super().__init__(parent)
        self.library = library
        self.changed = False

        self.setWindowTitle("Library folders")
        self.resize(660, 320)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Folders scanned for memes, sound effects, overlays and images.")
        )

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["On", "Items", "Folder"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        add = QPushButton("+  Add folder…")
        add.clicked.connect(self.add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

        self.table.itemChanged.connect(self._on_item_changed)
        self.reload()

    def reload(self) -> None:
        counts: dict[str, int] = {}
        for item in self.library.items:
            counts[item.root] = counts.get(item.root, 0) + 1

        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for root in self.library.roots():
            row = self.table.rowCount()
            self.table.insertRow(row)

            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            enabled.setCheckState(Qt.Checked if root["enabled"] else Qt.Unchecked)
            enabled.setData(Qt.UserRole, root["path"])
            self.table.setItem(row, 0, enabled)

            count = QTableWidgetItem(f"{counts.get(root['path'], 0):,}")
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, count)

            path = QTableWidgetItem(root["path"])
            path.setData(Qt.UserRole, root["path"])
            path.setToolTip(f"{root['label']} — {root['path']}")
            self.table.setItem(row, 2, path)
        self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        path = item.data(Qt.UserRole)
        self.library.set_root_enabled(path, item.checkState() == Qt.Checked)
        self.changed = True

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add library folder")
        if not folder:
            return
        # QFileDialog hands back forward slashes even on Windows; the whole
        # index stores native paths so that dragged URLs match the disk exactly.
        folder = folder.replace("/", "\\")
        self.library.add_root(folder)
        self.changed = True
        self.reload()

    def remove_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        path = self.table.item(rows[0].row(), 2).data(Qt.UserRole)
        answer = QMessageBox.question(
            self,
            "Remove folder",
            f"Stop indexing:\n{path}\n\nFavourites and tags are kept, so "
            "re-adding the folder restores them.",
        )
        if answer != QMessageBox.Yes:
            return
        self.library.remove_root(path)
        self.changed = True
        self.reload()
