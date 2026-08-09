"""Preview and audition.

Auditioning is the highest-frequency action in the whole panel — you arrow
through forty whooshes to find the one that fits — so it is bound to the arrow
keys by default rather than hidden behind a play button.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from stashlib.model import MediaItem


def _human(item: MediaItem) -> str:
    bits = [item.ext.lstrip(".").upper()]
    if item.duration:
        bits.append(f"{item.duration:.2f}s")
    if item.width and item.height:
        bits.append(f"{item.width}x{item.height}")
    bits.append(f"{item.size / 1_000_000:.1f} MB")
    if item.rel_dir:
        bits.append(item.rel_dir)
    return "  ·  ".join(bits)


class PreviewPane(QWidget):
    playbackFinished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.item: MediaItem | None = None

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)

        self.video = QVideoWidget(self)
        self.player.setVideoOutput(self.video)

        self.image = QLabel(self)
        self.image.setAlignment(Qt.AlignCenter)

        self.wave = QLabel(self)
        self.wave.setAlignment(Qt.AlignCenter)
        self.wave.setScaledContents(False)

        self.stack = QStackedWidget(self)
        for widget in (self.video, self.image, self.wave):
            self.stack.addWidget(widget)

        self.play_button = QToolButton(self)
        self.play_button.setText("▶")
        self.play_button.setToolTip("Play / stop  (Space)")
        self.play_button.clicked.connect(self.toggle)

        self.position = QSlider(Qt.Horizontal, self)
        self.position.setRange(0, 0)
        self.position.sliderMoved.connect(self.player.setPosition)

        self.volume = QSlider(Qt.Horizontal, self)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(80)
        self.volume.setToolTip("Volume")
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))

        self.info = QLabel("", self)
        self.info.setObjectName("status")

        transport = QHBoxLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        transport.setSpacing(6)
        transport.addWidget(self.play_button)
        transport.addWidget(self.position, 1)
        transport.addWidget(QLabel("🔊"))
        transport.addWidget(self.volume)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.stack, 1)
        layout.addLayout(transport)
        layout.addWidget(self.info)

        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)

    # ------------------------------------------------------------- control ---
    def show_item(self, item: MediaItem | None, autoplay: bool = False) -> None:
        self.player.stop()
        self.item = item
        if item is None:
            self.info.setText("")
            return

        self.info.setText(f"{item.name}\n{_human(item)}")

        if item.kind == "image":
            self.stack.setCurrentWidget(self.image)
            pixmap = QPixmap(item.path)
            if not pixmap.isNull():
                self.image.setPixmap(
                    pixmap.scaled(
                        self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                )
            return

        if item.kind == "audio":
            self.stack.setCurrentWidget(self.wave)
            thumb = item.thumb
            if isinstance(thumb, QPixmap) and not thumb.isNull():
                self.wave.setPixmap(
                    thumb.scaled(
                        self.wave.width() - 16,
                        max(24, self.wave.height() - 16),
                        Qt.IgnoreAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
            else:
                self.wave.setPixmap(QPixmap())
        else:
            self.stack.setCurrentWidget(self.video)

        self.player.setSource(QUrl.fromLocalFile(item.path))
        if autoplay:
            self.player.play()

    def toggle(self) -> None:
        if self.item is None or self.item.kind == "image":
            return
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()
        else:
            self.player.setPosition(0)
            self.player.play()

    def stop(self) -> None:
        self.player.stop()

    # ------------------------------------------------------------- signals ---
    def _on_position(self, value: int) -> None:
        if not self.position.isSliderDown():
            self.position.setValue(value)

    def _on_duration(self, value: int) -> None:
        self.position.setRange(0, value)

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.play_button.setText("■" if playing else "▶")
        if not playing:
            self.playbackFinished.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Re-fit whatever static media is showing; the player handles video.
        if self.item is not None and self.item.kind in ("image", "audio"):
            self.show_item(self.item, autoplay=False)
