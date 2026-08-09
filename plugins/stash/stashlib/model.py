"""The one record type the whole library is made of."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass(slots=True)
class MediaItem:
    path: str  # Windows path, exactly as it will be dragged
    root: str  # the configured root it was found under
    root_label: str
    rel_dir: str  # path below the root, e.g. "SFX Pack\\Whoosh"
    stem: str  # raw filename without extension
    norm: str  # normalize(stem) — what search matches against
    ext: str
    kind: str  # audio | video | image
    size: int
    mtime: float
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    probe_state: int = 0  # 0 new, 1 probed, 2 failed
    thumb_state: int = 0

    # Session-lifetime thumbnail cache. Typed as ``object`` on purpose: the Qt
    # layer parks a QPixmap here, and stashlib must never import PySide6.
    thumb: object | None = None

    # merged in at load time, not stored on this row
    tags: frozenset[str] = field(default_factory=frozenset)
    favorite: bool = False
    user_tags: str = ""
    play_count: int = 0
    last_used: float | None = None

    @property
    def name(self) -> str:
        return f"{self.stem}{self.ext}"

    @property
    def content_key(self) -> str:
        """Cache filename. Changes whenever the file does, so thumbnail
        invalidation needs no timestamp comparison — the old entry is simply
        orphaned."""
        raw = f"{self.path}|{self.size}|{self.mtime}".encode("utf-8", "surrogateescape")
        return hashlib.sha1(raw).hexdigest()[:16]

    def tokens(self) -> list[str]:
        return self.norm.split()
