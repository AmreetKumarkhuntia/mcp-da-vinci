"""Scan -> diff -> probe -> store.

The walk is cheap enough (~0.01 s for 5,000 files) to run unconditionally on
every launch, so there is no filesystem watcher and no staleness heuristic:
compare (size, mtime) against what is stored and act on the difference.
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
from collections.abc import Callable

from . import probe as probe_mod
from . import scan, store
from .normalize import normalize

Progress = Callable[[str, int, int], None] | None


def _report(progress: Progress, phase: str, done: int, total: int) -> None:
    if progress is not None:
        progress(phase, done, total)


def rescan(conn: sqlite3.Connection, progress: Progress = None) -> dict:
    """Bring ``items`` in line with what is on disk. Returns a summary."""
    roots = [(r["path"], r["label"]) for r in store.list_roots(conn, enabled_only=True)]
    known = store.existing_keys(conn)

    seen: set[str] = set()
    rows: list[tuple] = []
    unchanged = 0

    for found in scan.walk_roots(roots):
        seen.add(found.path)
        previous = known.get(found.path)
        if previous is not None and previous == (found.size, found.mtime):
            unchanged += 1
            continue
        rows.append(
            (
                found.path,
                found.root,
                found.root_label,
                found.rel_dir,
                found.stem,
                normalize(found.stem),
                found.ext,
                found.kind,
                found.size,
                found.mtime,
                None,
                None,
                None,
                0,
                0,
            )
        )
        _report(progress, "scan", len(seen), 0)

    gone = [path for path in known if path not in seen]

    store.upsert_items(conn, rows)
    store.delete_paths(conn, gone)

    return {
        "roots": len(roots),
        "seen": len(seen),
        "added_or_changed": len(rows),
        "unchanged": unchanged,
        "removed": len(gone),
    }


def probe_pending(
    conn: sqlite3.Connection, workers: int = 6, progress: Progress = None
) -> dict:
    """Fill in duration/dimensions for everything not probed yet.

    Probing runs on threads (soundfile and the ffmpeg subprocess both release
    the GIL) but every database write happens here on the calling thread, so
    the connection is never shared across threads.
    """
    pending = store.pending_probes(conn)
    if not pending:
        return {"probed": 0, "failed": 0}

    done = failed = 0
    with probe_mod.silence_native_stderr(), concurrent.futures.ThreadPoolExecutor(
        max_workers=workers
    ) as pool:
        futures = {
            pool.submit(probe_mod.probe, path, kind): path for path, kind in pending
        }
        for future in concurrent.futures.as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
            except Exception:
                result = probe_mod.FAILED
            store.update_probe(
                conn,
                path,
                result.duration,
                result.width,
                result.height,
                1 if result.ok else 2,
            )
            done += 1
            failed += not result.ok
            if done % 200 == 0:
                conn.commit()
                _report(progress, "probe", done, len(pending))
    conn.commit()
    _report(progress, "probe", done, len(pending))
    return {"probed": done - failed, "failed": failed}


def refresh(conn: sqlite3.Connection, progress: Progress = None) -> dict:
    summary = rescan(conn, progress)
    summary.update(probe_pending(conn, progress=progress))
    return summary
