"""Walk the configured roots. Fast enough to run unconditionally on launch."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import NamedTuple

from . import config


class Found(NamedTuple):
    path: str
    root: str
    root_label: str
    rel_dir: str
    stem: str
    ext: str
    kind: str
    size: int
    mtime: float


def walk_root(root: str, label: str) -> Iterator[Found]:
    """Yield every classifiable media file under ``root``.

    Unreadable directories are skipped rather than raised: a library root can
    easily contain a permission-denied or disconnected subtree, and one bad
    folder must not abort the scan.
    """
    root = os.path.normpath(root)
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        dirnames[:] = [d for d in dirnames if d not in config.SKIP_DIRS]
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        for filename in filenames:
            stem, ext = os.path.splitext(filename)
            kind = config.kind_for(ext)
            if kind is None:
                continue
            full = os.path.join(dirpath, filename)
            try:
                stat = os.stat(full)
            except OSError:
                continue
            yield Found(
                path=full,
                root=root,
                root_label=label,
                rel_dir=rel_dir,
                stem=stem,
                ext=ext.lower(),
                kind=kind,
                size=stat.st_size,
                mtime=stat.st_mtime,
            )


def walk_roots(roots: list[tuple[str, str]]) -> Iterator[Found]:
    for root, label in roots:
        yield from walk_root(root, label)
