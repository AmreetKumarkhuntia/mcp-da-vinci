"""Main window: search, filter, drag."""

from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from stashlib.library import Library

from .filters import KindFilter, SearchBar
from .hotkey import DEFAULT_LABEL as hotkey_label
from .hotkey import GlobalHotkey, bring_to_front
from .model import LibraryModel
from .preview import PreviewPane
from .results_view import ResultsView
from .roots_dialog import RootsDialog
from .thumb_loader import ThumbLoader
from .workers import RefreshWorker

RESULT_LIMIT = 400


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Stash — media library")
        self.settings = QSettings("Stash", "panel")

        self.library = Library()
        self.worker: RefreshWorker | None = None
        self.kind: str | None = None
        self.favorites_only = False
        self.compact = False
        self._suppress_autoplay = False

        self._build_ui()
        self._restore_state()
        self._install_hotkey()
        self.rerun_query()
        if not self.library.roots():
            # Nothing to show and nothing to scan — go straight to the folder
            # picker rather than leaving a new user staring at an empty grid.
            QTimer.singleShot(400, self.open_roots)
        QTimer.singleShot(0, self._use_dark_title_bar)
        QTimer.singleShot(150, self.start_refresh)

    def _use_dark_title_bar(self) -> None:
        """Ask DWM for a dark title bar so the frame matches the app.

        Windows 10 1809+ only, and the attribute id changed in 20H1 — try the
        current one and fall back. Purely cosmetic, so failure is ignored.
        """
        try:
            import ctypes

            handle = int(self.winId())
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):
                if (
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        handle, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
                    )
                    == 0
                ):
                    break
        except Exception:
            pass

    # ----------------------------------------------------------------- ui ---
    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 4)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)

        self.search = SearchBar(self)
        self.search.textChanged.connect(self.rerun_query)
        top.addWidget(self.search, 1)

        self.kind_filter = KindFilter(self)
        self.kind_filter.kindChanged.connect(self.on_kind_changed)
        top.addWidget(self.kind_filter)

        self.favorite_button = self._tool("★", "Favourites only", self.toggle_favorites)
        self.favorite_button.setCheckable(True)
        self.auto_button = self._tool(
            "🔊", "Auto-play sounds as you arrow through results", lambda: None
        )
        self.auto_button.setCheckable(True)
        self.auto_button.setChecked(True)
        top.addWidget(self.auto_button)
        self.compact_button = self._tool("▤", "Compact mode", self.toggle_compact)
        self.compact_button.setCheckable(True)
        self.ontop_button = self._tool("📌", "Always on top", self.toggle_on_top)
        self.ontop_button.setCheckable(True)
        for button in (self.favorite_button, self.compact_button, self.ontop_button):
            top.addWidget(button)
        top.addWidget(self._tool("＋", "Library folders…", self.open_roots))
        top.addWidget(self._tool("⟳", "Rescan folders", self.start_refresh))

        outer.addLayout(top)

        self.model = LibraryModel(self)
        self.thumbs = ThumbLoader(self)
        self.thumbs.ready.connect(self.on_thumb_ready)
        self.view = ResultsView(self)
        self.view.setModel(self.model)
        self.view.favoriteToggled.connect(self.on_favorite_toggled)
        self.view.auditionRequested.connect(self.on_audition)
        self.view.dragStarted.connect(
            lambda n: self.status.setText(f"dragged {n} file(s)")
        )

        self.preview = PreviewPane(self)
        self.splitter = QSplitter(Qt.Vertical, self)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([460, 200])
        outer.addWidget(self.splitter, 1)

        self.view.selectionModel().currentChanged.connect(self.on_current_changed)

        bar = QHBoxLayout()
        bar.setContentsMargins(2, 0, 2, 0)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.progress = QProgressBar(self)
        self.progress.setMaximumWidth(150)
        self.progress.setTextVisible(False)
        self.progress.hide()
        bar.addWidget(self.status, 1)
        bar.addWidget(self.progress)
        outer.addLayout(bar)

        self.setCentralWidget(central)
        self._build_shortcuts()

    def _tool(self, text: str, tip: str, slot) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    def _build_shortcuts(self) -> None:
        for position in range(4):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{position + 1}"), self)
            shortcut.activated.connect(
                lambda p=position: self.kind_filter.select(p)
            )
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(self.focus_search)
        QShortcut(QKeySequence("Ctrl+R"), self).activated.connect(self.start_refresh)
        QShortcut(QKeySequence("Ctrl+C"), self).activated.connect(self.copy_path)
        escape = QShortcut(QKeySequence("Esc"), self)
        escape.activated.connect(self.on_escape)

    # -------------------------------------------------------------- query ---
    def rerun_query(self) -> None:
        hits = self.library.search(
            text=self.search.text(),
            kind=self.kind,
            favorites_only=self.favorites_only,
            limit=RESULT_LIMIT,
        )
        self.model.set_items(hits)
        if hits:
            # Selecting row 0 is bookkeeping, not the user arrowing through
            # results — it must not fire a sound on launch or on every keystroke.
            self._suppress_autoplay = True
            try:
                self.view.setCurrentIndex(self.model.index(0, 0))
            finally:
                self._suppress_autoplay = False
        self.thumbs.request(hits)
        self._update_status(len(hits))

    def on_thumb_ready(self, path: str, image) -> None:
        row = self.model.row_for_path(path)
        if row < 0:
            return  # the result set moved on while this was rendering
        item = self.model.item_at(row)
        if item is not None and item.thumb is None:
            item.thumb = QPixmap.fromImage(image)
            self.model.refresh_row(row)

    def _update_status(self, shown: int) -> None:
        total = len(self.library.items)
        suffix = "" if shown < RESULT_LIMIT else f" (first {RESULT_LIMIT})"
        self.status.setText(f"{shown:,} of {total:,} items{suffix}")

        if not self.library.roots():
            self.view.empty_message = (
                "No folders yet.\n\n"
                "Click  ＋  above and pick a folder of memes, sound effects,\n"
                "green screens or overlays. Sub-folders are included, and their\n"
                "names become searchable tags automatically."
            )
        elif not total:
            self.view.empty_message = (
                "Folders are configured but nothing was found in them yet.\n"
                "Click  ⟳  to rescan, or  ＋  to check the folder list."
            )
        elif not shown:
            self.view.empty_message = "No matches. Try fewer words, or Ctrl+1 for All."
        else:
            self.view.empty_message = ""

    def on_kind_changed(self, kind: str | None) -> None:
        self.kind = kind
        self.rerun_query()

    def toggle_favorites(self) -> None:
        self.favorites_only = self.favorite_button.isChecked()
        self.rerun_query()

    def on_favorite_toggled(self, item) -> None:
        self.library.toggle_favorite(item)
        row = self.model._items.index(item) if item in self.model._items else -1
        if row >= 0:
            self.model.refresh_row(row)
        self.status.setText(
            f"{'★ favourited' if item.favorite else 'unfavourited'}  {item.stem}"
        )

    def on_current_changed(self, current, _previous) -> None:
        item = self.model.item_at(current)
        # Only sound auto-plays. Video would turn arrow-keying into chaos.
        autoplay = (
            item is not None
            and item.kind == "audio"
            and self.auto_button.isChecked()
            and not self._suppress_autoplay
        )
        self.preview.show_item(item, autoplay=autoplay)

    def on_audition(self, item) -> None:
        self.preview.show_item(item, autoplay=False)
        self.preview.toggle()
        self.library.note_use(item)

    def copy_path(self) -> None:
        items = self.view.selected_items()
        if not items:
            return
        QGuiApplication.clipboard().setText("\n".join(i.path for i in items))
        self.status.setText(f"copied {len(items)} path(s)")

    # ------------------------------------------------------------ refresh ---
    def start_refresh(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("scanning folders…")

        self.worker = RefreshWorker(self)
        self.worker.progressed.connect(self.on_progress)
        self.worker.succeeded.connect(self.on_refresh_done)
        self.worker.failed.connect(self.on_refresh_failed)
        self.worker.start()

    def on_progress(self, phase: str, done: int, total: int) -> None:
        if phase == "probe" and total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
            self.status.setText(f"reading media info… {done:,}/{total:,}")

    def on_refresh_done(self, summary: dict) -> None:
        self.progress.hide()
        self.library.reload()
        self.rerun_query()
        changed = summary.get("added_or_changed", 0)
        removed = summary.get("removed", 0)
        if changed or removed:
            self.status.setText(
                f"{len(self.library.items):,} items  ·  +{changed} / -{removed}"
            )

    def on_refresh_failed(self, message: str) -> None:
        self.progress.hide()
        self.status.setText(f"scan failed — {message}")

    # -------------------------------------------------------------- modes ---
    def open_roots(self) -> None:
        dialog = RootsDialog(self.library, self)
        dialog.exec()
        if dialog.changed:
            self.start_refresh()

    def toggle_compact(self) -> None:
        self.compact = self.compact_button.isChecked()
        self.view.set_compact(self.compact)
        self.preview.setVisible(not self.compact)
        if self.compact:
            self.preview.stop()
        self.settings.setValue("compact", self.compact)

    def toggle_on_top(self) -> None:
        on_top = self.ontop_button.isChecked()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on_top)
        self.show()  # re-applying window flags hides the window on Windows
        self.settings.setValue("on_top", on_top)

    def _install_hotkey(self) -> None:
        from PySide6.QtWidgets import QApplication

        self.hotkey = GlobalHotkey(self)
        self.hotkey.triggered.connect(self.on_hotkey)
        if not self.hotkey.register(QApplication.instance()):
            self.status.setText(
                f"{hotkey_label} is taken by another app — global summon disabled"
            )

    def on_hotkey(self) -> None:
        """Summon over Resolve, or dismiss if already in front."""
        if self.isActiveWindow() and not self.isMinimized():
            self.showMinimized()
            return
        bring_to_front(self)
        self.focus_search()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def on_escape(self) -> None:
        if self.search.text():
            self.search.clear()
        else:
            self.showMinimized()

    # -------------------------------------------------------------- state ---
    def _restore_state(self) -> None:
        geometry = self.settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(880, 620)

        if self.settings.value("on_top", False, type=bool):
            self.ontop_button.setChecked(True)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        if self.settings.value("compact", False, type=bool):
            self.compact_button.setChecked(True)
            self.compact = True
            self.view.set_compact(True)

    def closeEvent(self, event) -> None:
        self.settings.setValue("geometry", self.saveGeometry())
        self.hotkey.unregister()
        self.preview.stop()
        self.thumbs.shutdown()
        if self.worker is not None and self.worker.isRunning():
            self.worker.wait(3000)
        self.library.close()
        super().closeEvent(event)
