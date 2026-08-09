"""Hand-painted result tiles.

One tile = a thumbnail area (a kind-coloured placeholder until the thumbnail
cache lands) plus two elided lines of name, a duration badge and a favourite
star. Uniform size, so the view can lay out 5,000 rows in constant time.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from . import theme

TILE_W = 178
TILE_H = 116
THUMB_H = 74
PAD = 5


class TileDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, compact: bool = False) -> None:
        super().__init__(parent)
        self.compact = compact

    def tile_size(self) -> QSize:
        if self.compact:
            return QSize(TILE_W - 40, TILE_H - 44)
        return QSize(TILE_W, TILE_H)

    def sizeHint(self, option, index) -> QSize:
        return self.tile_size()

    def paint(self, painter: QPainter, option, index) -> None:
        from .model import LibraryModel

        item = index.data(LibraryModel.ItemRole)
        if item is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = option.rect.adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hovered = bool(option.state & QStyle.State_MouseOver)

        background = (
            theme.TILE_SELECTED if selected else theme.TILE_HOVER if hovered else theme.TILE
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 6, 6)

        thumb_h = 0 if self.compact else THUMB_H
        colour = theme.kind_color(item.kind)

        if thumb_h:
            thumb = QRect(rect.left(), rect.top(), rect.width(), thumb_h)
            self._paint_thumb(painter, thumb, item, colour)
        else:
            # Compact mode has no thumbnail; a colour stripe still identifies kind.
            stripe = QRect(rect.left(), rect.top(), 3, rect.height())
            painter.setBrush(colour)
            painter.drawRect(stripe)

        text_top = rect.top() + thumb_h + (2 if thumb_h else PAD)
        text_rect = QRect(
            rect.left() + PAD + (0 if thumb_h else 6),
            text_top,
            rect.width() - 2 * PAD,
            rect.bottom() - text_top - 2,
        )
        self._paint_name(painter, text_rect, item.stem)

        if item.favorite:
            painter.setPen(QPen(theme.STAR))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(
                QRect(rect.right() - 18, rect.top() + 2, 16, 16),
                Qt.AlignCenter,
                "★",
            )

        if selected:
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.ACCENT, 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 6, 6)

        painter.restore()

    # ------------------------------------------------------------ internals ---
    def _paint_thumb(self, painter, rect: QRect, item, colour: QColor) -> None:
        pixmap = item.thumb
        has_thumb = isinstance(pixmap, QPixmap) and not pixmap.isNull()

        if has_thumb and item.kind == "audio":
            # A waveform is a transparent strip, not a picture: letterbox it
            # over the kind wash instead of cropping it to fill.
            faded = QColor(colour)
            faded.setAlpha(30)
            painter.setPen(Qt.NoPen)
            painter.setBrush(faded)
            painter.drawRect(rect)
            scaled = pixmap.scaled(
                rect.width() - 8, rect.height() - 18, Qt.IgnoreAspectRatio,
                Qt.SmoothTransformation,
            )
            painter.drawPixmap(
                rect.left() + 4,
                rect.top() + (rect.height() - scaled.height()) // 2,
                scaled,
            )
        elif has_thumb:
            scaled = pixmap.scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            source_x = max(0, (scaled.width() - rect.width()) // 2)
            source_y = max(0, (scaled.height() - rect.height()) // 2)
            painter.drawPixmap(
                rect, scaled, QRect(source_x, source_y, rect.width(), rect.height())
            )
        else:
            faded = QColor(colour)
            faded.setAlpha(38)
            painter.setPen(Qt.NoPen)
            painter.setBrush(faded)
            painter.drawRect(rect)
            painter.setPen(QPen(colour))
            painter.setFont(QFont("Segoe UI", 20))
            painter.drawText(rect, Qt.AlignCenter, theme.KIND_GLYPH.get(item.kind, "?"))

        if item.duration:
            label = f"{item.duration:.1f}s"
            painter.setFont(QFont("Segoe UI", 7))
            metrics = QFontMetrics(painter.font())
            width = metrics.horizontalAdvance(label) + 8
            badge = QRect(rect.right() - width - 4, rect.bottom() - 16, width, 13)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 160))
            painter.drawRoundedRect(badge, 3, 3)
            painter.setPen(QPen(theme.TEXT))
            painter.drawText(badge, Qt.AlignCenter, label)

    def _paint_name(self, painter: QPainter, rect: QRect, name: str) -> None:
        painter.setPen(QPen(theme.TEXT))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        line_height = metrics.height()
        max_lines = max(1, rect.height() // line_height)

        words = name.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if metrics.horizontalAdvance(candidate) <= rect.width() or not current:
                current = candidate
            else:
                lines.append(current)
                current = word
            if len(lines) == max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)

        if not lines:
            return
        # Whatever did not fit gets elided into the last visible line.
        consumed = " ".join(lines)
        if len(consumed) < len(name):
            lines[-1] = metrics.elidedText(
                name[len(" ".join(lines[:-1])) :].strip(), Qt.ElideRight, rect.width()
            )

        for row, line in enumerate(lines):
            line_rect = QRect(
                rect.left(), rect.top() + row * line_height, rect.width(), line_height
            )
            painter.drawText(line_rect, Qt.AlignLeft | Qt.AlignVCenter, line)
