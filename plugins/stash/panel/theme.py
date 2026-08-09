"""Shared colours. Kept in Python rather than only in QSS because the tile
delegate paints by hand and needs the same values."""

from __future__ import annotations

from PySide6.QtGui import QColor

BG = QColor("#1b1b1b")
TILE = QColor("#2b2b2b")
TILE_HOVER = QColor("#343434")
TILE_SELECTED = QColor("#33485a")
BORDER = QColor("#3c3c3c")
ACCENT = QColor("#3fa7d6")
TEXT = QColor("#dcdcdc")
MUTED = QColor("#8c8c8c")
STAR = QColor("#f2c14e")

KIND_COLORS = {
    "audio": QColor("#4ec9b0"),
    "video": QColor("#c586c0"),
    "image": QColor("#d7ba7d"),
}

KIND_GLYPH = {"audio": "♪", "video": "▶", "image": "■"}


def kind_color(kind: str) -> QColor:
    return KIND_COLORS.get(kind, MUTED)
