"""Background work.

The scan/probe pass opens its **own** sqlite connection inside the worker
thread rather than borrowing the Library's. sqlite3 connections are bound to
the thread that created them, and WAL mode makes a second connection cheap and
safe. The main thread just calls `Library.reload()` when the worker signals
done.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class RefreshWorker(QThread):
    progressed = Signal(str, int, int)
    succeeded = Signal(dict)
    failed = Signal(str)

    def run(self) -> None:  # noqa: D102 - QThread entry point
        from stashlib import index, store

        conn = None
        try:
            conn = store.connect()
            summary = index.refresh(conn, self._progress)
            self.succeeded.emit(summary)
        except Exception as exc:  # a bad root must not kill the panel
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()

    def _progress(self, phase: str, done: int, total: int) -> None:
        self.progressed.emit(phase, done, total)
