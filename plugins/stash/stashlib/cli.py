"""Dev harness for the library core — no Qt involved.

    python.exe -m stashlib.cli scan
    python.exe -m stashlib.cli search "air horn"
    python.exe -m stashlib.cli search whoosh --kind audio --limit 10
    python.exe -m stashlib.cli roots
    python.exe -m stashlib.cli roots --add "D:\\videos\\overlays" --label Overlays

This is how the ranker gets tuned: change a weight, re-run the golden queries,
compare. It exists before the GUI on purpose.
"""

from __future__ import annotations

import argparse
import sys
import time

from . import config
from .library import Library


def _fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "     "
    return f"{seconds:5.1f}s"


def cmd_scan(lib: Library, args) -> int:
    started = time.perf_counter()

    # Progress goes to stdout, not stderr: the probe pass mutes fd 2 to hide
    # libmpg123's ID3 chatter, which would swallow these too.
    def progress(phase: str, done: int, total: int) -> None:
        if phase == "probe" and total:
            print(f"\r  probing {done}/{total}", end="", flush=True)

    summary = lib.refresh(progress)
    print()
    elapsed = time.perf_counter() - started
    for key, value in summary.items():
        print(f"{key:>18}: {value}")
    counts = lib.counts()
    print(f"{'by kind':>18}: {counts['by_kind']}")
    print(f"{'elapsed':>18}: {elapsed:.2f}s")
    print(f"{'database':>18}: {config.db_path()}")
    return 0


def cmd_search(lib: Library, args) -> int:
    started = time.perf_counter()
    hits = lib.search(
        text=" ".join(args.query),
        kind=args.kind,
        favorites_only=args.favorites,
        limit=args.limit,
    )
    elapsed = (time.perf_counter() - started) * 1000
    for item in hits:
        star = "*" if item.favorite else " "
        print(
            f"{star} {item.kind:<5} {_fmt_duration(item.duration)}  "
            f"{item.stem[:58]:<58}  {item.rel_dir}"
        )
    print(
        f"\n{len(hits)} hit(s) of {len(lib.items)} items in {elapsed:.1f} ms",
        file=sys.stderr,
    )
    return 0


def cmd_roots(lib: Library, args) -> int:
    if args.add:
        lib.add_root(args.add, args.label)
        print(f"added {args.add}")
    if args.remove:
        lib.remove_root(args.remove)
        print(f"removed {args.remove}")
    counts: dict[str, int] = {}
    for item in lib.items:
        counts[item.root] = counts.get(item.root, 0) + 1
    for root in lib.roots():
        flag = " " if root["enabled"] else "-"
        print(f"{flag} {counts.get(root['path'], 0):>6}  {root['label']:<12} {root['path']}")
    return 0


def cmd_tags(lib: Library, args) -> int:
    for tag, count in lib.top_tags(lib.items, limit=args.limit):
        print(f"{count:>6}  {tag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stashlib", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="rescan roots and probe new files")

    search = sub.add_parser("search", help="ranked search")
    search.add_argument("query", nargs="*", default=[])
    search.add_argument("--kind", choices=["audio", "video", "image"])
    search.add_argument("--favorites", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    roots = sub.add_parser("roots", help="list or edit library roots")
    roots.add_argument("--add", metavar="PATH")
    roots.add_argument("--label", metavar="NAME")
    roots.add_argument("--remove", metavar="PATH")

    tags = sub.add_parser("tags", help="most common tags")
    tags.add_argument("--limit", type=int, default=40)

    args = parser.parse_args(argv)
    lib = Library()
    try:
        return {
            "scan": cmd_scan,
            "search": cmd_search,
            "roots": cmd_roots,
            "tags": cmd_tags,
        }[args.command](lib, args)
    finally:
        lib.close()


if __name__ == "__main__":
    raise SystemExit(main())
