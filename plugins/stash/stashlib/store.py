"""sqlite persistence.

Two tables on purpose:

* ``items`` is derived and disposable — delete it and a rescan rebuilds it in
  about a minute.
* ``user_meta`` is irreplaceable, so it is keyed by **path** rather than by an
  items rowid. Favorites and hand-written tags then survive a full rebuild, a
  root being removed and re-added, or a schema migration.

sqlite is never on the query path: search loads everything into RAM once.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterable

from . import config
from .model import MediaItem

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS roots (
  id      INTEGER PRIMARY KEY,
  path    TEXT    NOT NULL UNIQUE,
  label   TEXT    NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  added   REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
  path        TEXT    PRIMARY KEY,
  root        TEXT    NOT NULL,
  root_label  TEXT    NOT NULL,
  rel_dir     TEXT    NOT NULL,
  stem        TEXT    NOT NULL,
  norm        TEXT    NOT NULL,
  ext         TEXT    NOT NULL,
  kind        TEXT    NOT NULL,
  size        INTEGER NOT NULL,
  mtime       REAL    NOT NULL,
  duration    REAL,
  width       INTEGER,
  height      INTEGER,
  probe_state INTEGER NOT NULL DEFAULT 0,
  thumb_state INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_items_kind ON items(kind);
CREATE INDEX IF NOT EXISTS ix_items_root ON items(root);

CREATE TABLE IF NOT EXISTS user_meta (
  path       TEXT    PRIMARY KEY,
  favorite   INTEGER NOT NULL DEFAULT 0,
  user_tags  TEXT    NOT NULL DEFAULT '',
  play_count INTEGER NOT NULL DEFAULT 0,
  last_used  REAL
);

CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""

_ITEM_COLUMNS = (
    "path, root, root_label, rel_dir, stem, norm, ext, kind, size, mtime, "
    "duration, width, height, probe_state, thumb_state"
)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path(), timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(k, v) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    _seed_roots(conn)
    return conn


# ------------------------------------------------------------------- roots ---

def _seed_roots(conn: sqlite3.Connection) -> None:
    """Populate the default roots once, on a virgin database only.

    Guarded by a meta flag rather than by "roots is empty", so that a user who
    deliberately removes every seeded root does not get them back on next launch.
    """
    if conn.execute("SELECT 1 FROM meta WHERE k='roots_seeded'").fetchone():
        return
    now = time.time()
    for path, label in config.seed_roots():
        conn.execute(
            "INSERT OR IGNORE INTO roots(path, label, enabled, added) VALUES (?,?,1,?)",
            (path, label, now),
        )
    conn.execute("INSERT INTO meta(k, v) VALUES ('roots_seeded', '1')")
    conn.commit()


def list_roots(conn: sqlite3.Connection, enabled_only: bool = False) -> list[dict]:
    sql = "SELECT id, path, label, enabled, added FROM roots"
    if enabled_only:
        sql += " WHERE enabled = 1"
    return [dict(r) for r in conn.execute(sql + " ORDER BY id")]


def add_root(conn: sqlite3.Connection, path: str, label: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO roots(path, label, enabled, added) VALUES (?,?,1,?)",
        (path, label, time.time()),
    )
    conn.commit()


def remove_root(conn: sqlite3.Connection, path: str) -> None:
    """Drop a root and its items. ``user_meta`` is deliberately untouched, so
    re-adding the folder restores favorites and tags."""
    conn.execute("DELETE FROM roots WHERE path = ?", (path,))
    conn.execute("DELETE FROM items WHERE root = ?", (path,))
    conn.commit()


def set_root_enabled(conn: sqlite3.Connection, path: str, enabled: bool) -> None:
    conn.execute("UPDATE roots SET enabled = ? WHERE path = ?", (int(enabled), path))
    conn.commit()


# ------------------------------------------------------------------- items ---

def existing_keys(conn: sqlite3.Connection) -> dict[str, tuple[int, float]]:
    """path -> (size, mtime), the change key for incremental rescans."""
    return {
        row["path"]: (row["size"], row["mtime"])
        for row in conn.execute("SELECT path, size, mtime FROM items")
    }


def upsert_items(conn: sqlite3.Connection, rows: Iterable[tuple]) -> int:
    placeholders = ",".join("?" * len(_ITEM_COLUMNS.split(",")))
    cur = conn.executemany(
        f"INSERT INTO items ({_ITEM_COLUMNS}) VALUES ({placeholders}) "
        "ON CONFLICT(path) DO UPDATE SET "
        "root=excluded.root, root_label=excluded.root_label, rel_dir=excluded.rel_dir, "
        "stem=excluded.stem, norm=excluded.norm, ext=excluded.ext, kind=excluded.kind, "
        "size=excluded.size, mtime=excluded.mtime, "
        "duration=NULL, width=NULL, height=NULL, probe_state=0, thumb_state=0",
        rows,
    )
    conn.commit()
    return cur.rowcount


def delete_paths(conn: sqlite3.Connection, paths: Iterable[str]) -> int:
    paths = list(paths)
    if not paths:
        return 0
    conn.executemany("DELETE FROM items WHERE path = ?", ((p,) for p in paths))
    conn.commit()
    return len(paths)


def update_probe(
    conn: sqlite3.Connection,
    path: str,
    duration: float | None,
    width: int | None,
    height: int | None,
    state: int,
) -> None:
    conn.execute(
        "UPDATE items SET duration=?, width=?, height=?, probe_state=? WHERE path=?",
        (duration, width, height, state, path),
    )


def pending_probes(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return [
        (row["path"], row["kind"])
        for row in conn.execute("SELECT path, kind FROM items WHERE probe_state = 0")
    ]


def load_all(conn: sqlite3.Connection) -> list[MediaItem]:
    """Every row as a MediaItem, with user_meta merged in. ~3 MB at 5k items."""
    meta = {
        row["path"]: row
        for row in conn.execute(
            "SELECT path, favorite, user_tags, play_count, last_used FROM user_meta"
        )
    }
    items: list[MediaItem] = []
    for row in conn.execute(f"SELECT {_ITEM_COLUMNS} FROM items"):
        extra = meta.get(row["path"])
        items.append(
            MediaItem(
                path=row["path"],
                root=row["root"],
                root_label=row["root_label"],
                rel_dir=row["rel_dir"],
                stem=row["stem"],
                norm=row["norm"],
                ext=row["ext"],
                kind=row["kind"],
                size=row["size"],
                mtime=row["mtime"],
                duration=row["duration"],
                width=row["width"],
                height=row["height"],
                probe_state=row["probe_state"],
                thumb_state=row["thumb_state"],
                favorite=bool(extra["favorite"]) if extra else False,
                user_tags=extra["user_tags"] if extra else "",
                play_count=extra["play_count"] if extra else 0,
                last_used=extra["last_used"] if extra else None,
            )
        )
    return items


# --------------------------------------------------------------- user meta ---

def set_favorite(conn: sqlite3.Connection, path: str, favorite: bool) -> None:
    conn.execute(
        "INSERT INTO user_meta(path, favorite) VALUES (?, ?) "
        "ON CONFLICT(path) DO UPDATE SET favorite = excluded.favorite",
        (path, int(favorite)),
    )
    conn.commit()


def set_user_tags(conn: sqlite3.Connection, path: str, tags: str) -> None:
    conn.execute(
        "INSERT INTO user_meta(path, user_tags) VALUES (?, ?) "
        "ON CONFLICT(path) DO UPDATE SET user_tags = excluded.user_tags",
        (path, tags),
    )
    conn.commit()


def note_use(conn: sqlite3.Connection, path: str) -> None:
    conn.execute(
        "INSERT INTO user_meta(path, play_count, last_used) VALUES (?, 1, ?) "
        "ON CONFLICT(path) DO UPDATE SET "
        "play_count = user_meta.play_count + 1, last_used = excluded.last_used",
        (path, time.time()),
    )
    conn.commit()


def counts(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) n, SUM(probe_state != 0) probed FROM items"
    ).fetchone()
    by_kind = {
        r["kind"]: r["n"]
        for r in conn.execute("SELECT kind, COUNT(*) n FROM items GROUP BY kind")
    }
    return {"total": row["n"] or 0, "probed": row["probed"] or 0, "by_kind": by_kind}
