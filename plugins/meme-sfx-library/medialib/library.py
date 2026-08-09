"""The facade every front-end talks to.

Holds one sqlite connection, the fully-loaded item list, and the tag sidecar.
Deliberately synchronous and framework-free: the Qt layer drives the slow calls
(`refresh`) from a worker thread and calls the fast ones (`search`) directly.
"""

from __future__ import annotations

from . import index, search as search_mod, store, tags as tags_mod
from .model import MediaItem
from .search import Query


class Library:
    def __init__(self) -> None:
        self.conn = store.connect()
        self.sidecar: dict = {}
        self.alias_groups: list[frozenset[str]] = []
        self.items: list[MediaItem] = []
        self.reload()

    # ------------------------------------------------------------- loading ---
    def reload(self) -> None:
        """Re-read the sidecar and pull every row into memory."""
        self.sidecar = tags_mod.load_sidecar()
        self.alias_groups = tags_mod.alias_groups(self.sidecar)
        self.items = tags_mod.apply(store.load_all(self.conn), self.sidecar)

    def refresh(self, progress=None) -> dict:
        """Rescan disk, probe what changed, then reload. Slow — call off-thread."""
        summary = index.refresh(self.conn, progress)
        self.reload()
        return summary

    # -------------------------------------------------------------- query ---
    def search(
        self,
        text: str = "",
        kind: str | None = None,
        tags: frozenset[str] = frozenset(),
        favorites_only: bool = False,
        roots: frozenset[str] = frozenset(),
        limit: int = 300,
    ) -> list[MediaItem]:
        query = Query(
            text=text,
            kind=kind,
            tags=tags,
            favorites_only=favorites_only,
            roots=roots,
        )
        return search_mod.search(self.items, query, self.alias_groups, limit)

    def top_tags(self, items: list[MediaItem], limit: int = 24):
        return search_mod.top_tags(items, limit)

    def counts(self) -> dict:
        return store.counts(self.conn)

    # -------------------------------------------------------------- roots ---
    def roots(self, enabled_only: bool = False) -> list[dict]:
        return store.list_roots(self.conn, enabled_only)

    def add_root(self, path: str, label: str | None = None) -> None:
        path = path.rstrip("\\/")
        store.add_root(self.conn, path, label or path.rsplit("\\", 1)[-1])

    def remove_root(self, path: str) -> None:
        store.remove_root(self.conn, path)
        self.reload()

    def set_root_enabled(self, path: str, enabled: bool) -> None:
        store.set_root_enabled(self.conn, path, enabled)

    # ---------------------------------------------------------- user state ---
    def toggle_favorite(self, item: MediaItem) -> bool:
        item.favorite = not item.favorite
        store.set_favorite(self.conn, item.path, item.favorite)
        return item.favorite

    def set_user_tags(self, item: MediaItem, tags: str) -> None:
        item.user_tags = tags
        store.set_user_tags(self.conn, item.path, tags)
        item.tags = tags_mod.derive(item, self.sidecar)

    def note_use(self, item: MediaItem) -> None:
        item.play_count += 1
        store.note_use(self.conn, item.path)

    def close(self) -> None:
        self.conn.close()
