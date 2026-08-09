"""Paths, extension classification, and the seed library roots."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "Stash"

AUDIO_EXTS = frozenset(
    {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff"}
)
VIDEO_EXTS = frozenset(
    {".mp4", ".mov", ".avi", ".wmv", ".mkv", ".webm", ".m4v", ".mpg", ".mpeg", ".flv"}
)
IMAGE_EXTS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".avif"}
)

# .sfk are Sound Forge peak sidecars — soundfile throws on them. The rest is
# the usual litter that accumulates in a downloads-fed media folder.
BLOCKED_EXTS = frozenset(
    {
        ".sfk", ".url", ".ini", ".db", ".lnk", ".txt", ".nfo", ".log",
        ".zip", ".rar", ".7z", ".peak", ".asd", ".reapeaks", ".pek", ".cfa",
    }
)

# Directories never worth walking into.
SKIP_DIRS = frozenset({"$RECYCLE.BIN", "System Volume Information", ".git", "__pycache__"})

# Candidates offered on first run. These are one machine's folders, so every
# one is checked for existence before being seeded — on any other machine the
# panel starts empty and asks the user to add folders instead of silently
# indexing nothing.
CANDIDATE_ROOTS: tuple[tuple[str, str], ...] = (
    (r"D:\videos\sound\SFX Pack", "SFX"),
    (r"D:\videos\video making stuffs\meme", "Memes"),
    (r"D:\videos\video making stuffs\gifs", "GIFs"),
    (r"D:\Thumbnails\Meme", "Thumbnails"),
)


def seed_roots() -> list[tuple[str, str]]:
    """Candidate roots that actually exist on this machine."""
    return [(path, label) for path, label in CANDIDATE_ROOTS if Path(path).is_dir()]


def kind_for(ext: str) -> str | None:
    """Map a lowercase extension to 'audio' / 'video' / 'image', else None."""
    ext = ext.lower()
    if ext in BLOCKED_EXTS:
        return None
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    return None


def cache_dir() -> Path:
    """Where index.db and the thumbnail cache live.

    Must be Windows-local. The repo is reached from Windows as
    \\\\wsl.localhost\\Ubuntu\\... and sqlite locking over that path is broken
    and slow, so never resolve this relative to the source tree.
    """
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".cache"
    path = root / APP_DIR_NAME / "library"
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return cache_dir() / "index.db"


def thumbs_dir() -> Path:
    path = cache_dir() / "thumbs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tags_path() -> Path:
    return cache_dir() / "tags.json"
