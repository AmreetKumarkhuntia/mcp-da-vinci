"""Tag derivation and the hand-editable sidecar.

Three sources merge into one lowercase tag set per item:

1. the root's label plus every path component below it — this is what makes
   ``SFX Pack\\Alarm & Chime\\x.mp3`` searchable as "alarm" or "chime" for free;
2. explicit ``path_tags`` from the sidecar;
3. the user's own per-file tags, stored in ``user_meta``.

The sidecar also holds ``aliases``, which is what lets "bruh" find
``Bass Boost.mp3`` — the single feature no native Resolve panel offers.
"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import Any

from . import config
from .model import MediaItem

_SPLIT = re.compile(r"[\\/&,+]+")

DEFAULT_SIDECAR: dict[str, Any] = {
    "aliases": {
        "vine boom": ["bass boost", "bruh"],
        "air horn": ["airhorn", "mlg"],
    },
    "path_tags": {
        r"D:\videos\video making stuffs\meme\Green Screen": [
            "greenscreen",
            "chroma",
            "overlay",
        ],
    },
    "hide": ["*.sfk", "*.url", "desktop.ini"],
}


def load_sidecar() -> dict[str, Any]:
    """Read tags.json, creating it with sensible defaults on first run.

    A malformed file must not take the library down — fall back to defaults and
    let the panel surface the problem instead of refusing to start.
    """
    path = config.tags_path()
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_SIDECAR, indent=2), encoding="utf-8")
        return dict(DEFAULT_SIDECAR)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SIDECAR)
    data.setdefault("aliases", {})
    data.setdefault("path_tags", {})
    data.setdefault("hide", [])
    return data


def is_hidden(path: str, patterns: list[str]) -> bool:
    name = path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(name.lower(), p.lower()) for p in patterns)


def derive(item: MediaItem, sidecar: dict[str, Any]) -> frozenset[str]:
    tags: set[str] = set()

    for chunk in (item.root_label, *_SPLIT.split(item.rel_dir)):
        for word in chunk.split():
            word = word.strip("_-").lower()
            if len(word) > 1:
                tags.add(word)

    lowered = item.path.lower()
    for prefix, extra in sidecar.get("path_tags", {}).items():
        if lowered.startswith(prefix.lower()):
            tags.update(t.lower() for t in extra)

    tags.update(t for t in item.user_tags.lower().split() if t)
    tags.add(item.kind)
    return frozenset(tags)


def apply(items: list[MediaItem], sidecar: dict[str, Any]) -> list[MediaItem]:
    """Attach tags to every item and drop anything the sidecar hides."""
    hide = sidecar.get("hide", [])
    kept: list[MediaItem] = []
    for item in items:
        if is_hidden(item.path, hide):
            continue
        item.tags = derive(item, sidecar)
        kept.append(item)
    return kept


def alias_groups(sidecar: dict[str, Any]) -> list[frozenset[str]]:
    """Each group is a set of interchangeable phrases, normalized."""
    from .normalize import normalize

    groups: list[frozenset[str]] = []
    for key, values in sidecar.get("aliases", {}).items():
        members = {normalize(key)} | {normalize(v) for v in values}
        members.discard("")
        if len(members) > 1:
            groups.append(frozenset(members))
    return groups
