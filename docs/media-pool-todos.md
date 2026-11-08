# Media pool & library — open tooling TODOs

Companion to `fusion-3d-notes.md`, which covers the Fusion/comp side. This file
is the media-pool side: importing, bins, and the library the `video-edit` skill
searches.

These three items were written up in the Stash repo's `NOTES.md` while that
plugin was still part of this checkout. They describe `tools/`, `server.py` and
`resolve/connection.py`, none of which exist in Stash, so they live here now.
Verified still open on 2026-08-15.

## 1. MCP surface for the Stash library

`tools/library.py` exposing `library_scan` / `library_search` / `library_insert`,
registered by appending `library` to `server.py`'s `from tools import ...` line
(currently `inspect, edit, render, fusion, frames, editing`).

`library_search` would work on the **free** edition, since it never touches
Resolve — it only reads Stash's sqlite index. That is the point: it gives the
`video-edit` skill a way to actually find "the airhorn" instead of guessing at
filenames.

Stash is a separate repo now (`../stash`), so this means importing `stashlib`
across checkouts or depending on it properly — decide which when picking it up.
Deferred by choice, ~90 min.

## 2. Studio-only actions — insert at playhead, import to bin

`Project.InsertAudioToCurrentTrackAtPlayhead(path, 0, 0)` takes a **file path
directly**, with no media-pool import step. For SFX that is strictly better
than dragging: no bin clutter, no import round trip.

Untestable until Studio is installed — external scripting itself is
Studio-gated (`resolve/connection.py:131`, `README.md:55`).

## 3. `resolve/connection.py` helpers — and the bug they fix

`ensure_bin(path)` plus a `current_folder(folder)` contextmanager modelled on
the existing `comp_lock` (`resolve/connection.py:338`).

**This is a latent bug today, not just a nicety.** `MediaPool.ImportMedia()`
has no way to specify a target bin — it imports into whatever folder happens to
be selected in the UI. So `tools/edit.py:import_media` (line 20) silently
scatters imports depending on where the user last clicked, and there is no
argument the caller can pass to control it.
