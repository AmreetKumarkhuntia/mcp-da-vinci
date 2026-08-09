"""Ranked in-memory search.

A full scored pass over every item costs single-digit milliseconds at this
library's size, which is why sqlite is never queried and why the Qt layer can
re-rank on every keystroke without a debounce timer. It also means the result
can be *ranked* rather than merely filtered — the thing a
QSortFilterProxyModel structurally cannot do.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import MediaItem
from .normalize import normalize

# Per-token scores. Exact beats prefix beats substring; a hit on a tag counts
# for less than a hit in the name itself.
_EXACT = 100.0
_PREFIX = 70.0
_SUBSTRING = 35.0
_TAG_EXACT = 60.0
_TAG_PREFIX = 40.0

_PHRASE_BONUS = 150.0
_FAVORITE_BONUS = 45.0
_USED_BONUS = 12.0
_POSITION_PENALTY = 2.0  # earlier tokens in the name matter more
_LENGTH_PENALTY = 1.5  # prefer concise names over rambling ripper titles


@dataclass(slots=True)
class Query:
    text: str
    kind: str | None = None
    tags: frozenset[str] = frozenset()
    favorites_only: bool = False
    roots: frozenset[str] = frozenset()


def _score_tokens(item: MediaItem, tokens: list[str]) -> float | None:
    """Score one alternative phrasing. ``None`` means the item is not a match.

    All query tokens must land somewhere (AND semantics) — with 5,000 items an
    OR would return everything for any two-word query.
    """
    item_tokens = item.tokens()
    total = 0.0
    for query_token in tokens:
        best = 0.0
        for position, token in enumerate(item_tokens):
            if token == query_token:
                candidate = _EXACT - position * _POSITION_PENALTY
            elif token.startswith(query_token):
                candidate = _PREFIX - position * _POSITION_PENALTY
            elif query_token in token:
                candidate = _SUBSTRING - position * _POSITION_PENALTY
            else:
                continue
            best = max(best, candidate)
        if best < _TAG_EXACT:
            for tag in item.tags:
                if tag == query_token:
                    best = max(best, _TAG_EXACT)
                elif tag.startswith(query_token):
                    best = max(best, _TAG_PREFIX)
        if best <= 0:
            return None
        total += best
    return total


def search(
    items: list[MediaItem],
    query: Query,
    alias_groups: list[frozenset[str]] | None = None,
    limit: int = 300,
) -> list[MediaItem]:
    text = normalize(query.text)
    tokens = text.split()

    # "bruh" should find "Bass Boost" — score against every interchangeable
    # phrasing and keep the best.
    alternatives: list[list[str]] = [tokens] if tokens else []
    if tokens and alias_groups:
        for group in alias_groups:
            if text in group:
                alternatives.extend(member.split() for member in group if member != text)

    scored: list[tuple[float, MediaItem]] = []
    for item in items:
        if query.kind and item.kind != query.kind:
            continue
        if query.favorites_only and not item.favorite:
            continue
        if query.roots and item.root not in query.roots:
            continue
        if query.tags and not query.tags <= item.tags:
            continue

        if not alternatives:
            score = 0.0
        else:
            best = None
            for alternative in alternatives:
                value = _score_tokens(item, alternative)
                if value is not None and (best is None or value > best):
                    best = value
            if best is None:
                continue
            score = best
            if text and text in item.norm:
                score += _PHRASE_BONUS

        if item.favorite:
            score += _FAVORITE_BONUS
        if item.play_count:
            score += min(item.play_count, 5) * _USED_BONUS
        score -= len(item.tokens()) * _LENGTH_PENALTY
        scored.append((score, item))

    if tokens:
        # Ties are common; fall back to name so the grid does not reshuffle
        # arbitrarily between identical-scoring runs.
        scored.sort(key=lambda pair: (-pair[0], pair[1].stem.lower()))
    else:
        # Empty query means "browse". Newest first is far more useful than
        # alphabetical, which just surfaces whatever begins with a digit.
        scored.sort(key=lambda pair: (-pair[0], -pair[1].mtime))
    return [item for _score, item in scored[:limit]]


def top_tags(items: list[MediaItem], limit: int = 24) -> list[tuple[str, int]]:
    """Most common tags in a result set — the source for the category chips."""
    counts: dict[str, int] = {}
    for item in items:
        for tag in item.tags:
            counts[tag] = counts.get(tag, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return ranked[:limit]
