# Stash — findings & friction log

Companion to `docs/fusion-3d-notes.md`. Everything here was measured on this
machine (Resolve 21.0.0.48 **free** edition, Windows Python `E:\Python\python.exe`
3.12.8) — don't re-derive it.

## Phase 0 — the drag gate: PASSED

The whole panel rests on one assumption: Qt's `QDrag` produces a Windows
`CF_HDROP` that Resolve accepts, exactly like an Explorer drag. There is **no
drag-and-drop API anywhere** in Resolve's scripting README — `grep -i 'drag\|drop'`
over all 1129 lines matches only "Drop Frame". So this had to be proven, not assumed.

`scripts/spike_drag.py` is the harness; it stays in the repo permanently. When a
Resolve update breaks dragging, it is the 10-second bisect.

Result — seven drops across two runs, **every one returned `DropAction.CopyAction`**,
including the 3-file multi-selection:

```
[drop] 1 file(s) -> action=<DropAction.CopyAction: 1>   x6
[drop] 3 file(s) -> action=<DropAction.CopyAction: 1>
```

Notes:

- Multi-file drag works — no need for a one-at-a-time fallback.
- `Qt.WindowStaysOnTopHint` does not interfere: OLE targets the window under the
  cursor regardless of Z-order.
- Fading the window to 25 % opacity during `drag.exec()` (so the drop target is
  visible underneath) does not break the drag.
- **The integrity-level probe in `spike_drag.py` is unreliable** — it reported
  "access denied" for our *own* process as well as Resolve's, so its UIPI verdict
  is meaningless. Ignore it. It only matters if drags stop working, and then the
  real check is whether Resolve was launched elevated.

## Phase 1 — core measurements

| Thing | Measured |
|---|---|
| Items indexed | **5,063** — 4,875 audio, 165 video, 23 image |
| Cold scan + probe, 6 threads | **9.35 s** (the plan estimated 30 s) |
| Warm rescan, no changes | **0.14 s** — cheap enough to run unconditionally on every launch |
| Probe failures | 37 of 5,063 (0.7 %) — malformed ID3 / truncated mp3s; they stay listed and searchable, just without a duration |
| Search, full ranked pass | **0.1–10 ms** over all 5,063 items |
| Database | `C:\Users\Amreet khuntia\AppData\Local\Stash\library\index.db` |

Consequences that changed the design:

- **No lazy probing, no priority queue, no LRU eviction.** A full pass is 9 s;
  the machinery to avoid it would cost more than it saves.
- **No FTS5, no sqlite on the query path.** Load all rows into RAM at startup
  (~3 MB) and score in pure Python. This also lets results be *ranked* rather
  than merely filtered — which is why `QSortFilterProxyModel` is rejected in the
  Qt layer.
- **No `watchdog` dependency.** A 0.14 s rescan on launch plus a manual button
  covers it.

## Phase 3-5 — panel measurements & corrections

| Renderer | Cost (measured) | Output |
|---|---|---|
| video thumbnail (`imageio_ffmpeg`, seek then 1 frame) | 47–216 ms | ~5–20 KB JPEG |
| image thumbnail (Pillow) | 5–44 ms | ~8–14 KB JPEG |
| audio waveform (`soundfile` + numpy peaks → Pillow) | ~4 ms warm | **under 1 KB** PNG |

Corrections to earlier assumptions:

- **Waveform strips are genuinely useful, not decoration.** The prediction was
  that sub-second effects would all render as identical blobs at tile size. They
  do not — `Anvil`, `Bass`, `Bruh` and `calmdownjamal` are instantly
  distinguishable in a 178 px tile. Waveforms are drawn as the primary tile art
  for audio, letterboxed over the kind wash rather than cropped to fill.
- **PySide6 6.11's multimedia backend is FFmpeg**, not Windows Media Foundation.
  It handles mp3 / mp4 / wmv / avi out of the box, so no per-format fallback was
  needed. It is chatty on stdout when opening a file — harmless.
- **Do not autoplay on the programmatic selection.** `set_items()` selects row 0,
  which fired an audition on launch and on every keystroke. Guarded with a
  `_suppress_autoplay` flag around `setCurrentIndex`; only real arrow-key
  navigation auditions.
- **`QPixmap` may only be constructed on the GUI thread.** Thumbnail workers emit
  a `QImage` and the main thread converts. The pixmap is parked on the
  `MediaItem` itself, which is shared across searches, so each file renders at
  most once per session.
- **`SetForegroundWindow` cannot steal focus** — an attempt to screenshot the
  panel photographed Resolve instead. Use `PrintWindow` with
  `PW_RENDERFULLCONTENT` (2) to capture an occluded window. Registering a global
  hotkey *does* grant foreground rights when that hotkey fires, which is why
  Ctrl+Shift+M can raise the panel over Resolve.

## The drag bug that cost a day — read this before touching the view

Dragging out of the grid did nothing. Items selected normally, no exception, no
error, nothing in any log. `startDrag()` was simply never called.

**Cause:** `LibraryModel` did not override `flags()`. `QAbstractListModel`
returns `Enabled | Selectable` by default — **not `Qt.ItemIsDragEnabled`**. Qt
only enters `DraggingState` when `selectedDraggableIndexes()` is non-empty, and
that list filters on exactly that flag. So the view selected fine and silently
refused to drag.

```python
def flags(self, index):
    base = super().flags(index)
    return base | Qt.ItemIsDragEnabled if index.isValid() else base
```

**Why the spike didn't catch it:** `scripts/spike_drag.py` drags from a
`QPushButton` with a hand-built `QDrag` — no item model involved. It proved the
*mechanism* (Resolve accepts Qt's `CF_HDROP`) but never exercised the *view*.
A green spike does not mean a green feature; the gap between them was this flag.

**Blind alley:** `setMovement(QListView.Static)` was blamed first and removed.
It was not the cause. Static is harmless here.

Verified end to end afterwards — real drops into Resolve returned `CopyAction`
for all three kinds:

```
CopyAction  ...\Meme Sound Effects\Reeeee sound effect.mp3
CopyAction  ...\gifs\like.mp4
CopyAction  ...\gifs\memes\lol.png
```

### Diagnosing drag problems

`panel/debug.py` logs presses, `startDrag` entry and the `drag.exec` result to
`%LOCALAPPDATA%\Stash\library\panel-debug.log`. Turn it on by creating an
empty `debug.on` next to that log, then read the three-line signature:

| Log shows | Meaning |
|---|---|
| no `startDrag` line | the *view* never began a drag — model flags, `dragEnabled`, or hit-testing |
| `startDrag` then `IgnoreAction` | drag works; the drop target refused it |
| `startDrag` then `CopyAction` | it landed |

**`MEMESFX_DEBUG=1` set from WSL does nothing** — WSL environment variables do
not cross into Windows processes without `WSLENV`. That is why the marker file
exists, and it is also the reason the first diagnostic round produced an empty
log. Same trap applies to shortcuts and the frozen .exe.

A drag can also be tested without touching Resolve: float the window topmost and
synthesise press/move/release inside its own client area with `SetCursorPos` +
`mouse_event`. `startDrag` firing with `IgnoreAction` is the expected pass —
the drop lands on nothing.

## `sys.stderr` is None in a --windowed frozen build

Audio waveforms rendered fine under Python and produced **zero** files in the
PyInstaller app — 29 jpg, 0 png. Video and image thumbnails were unaffected.

Cause: `probe.silence_native_stderr()` called `sys.stderr.flush()`, and a
`--windowed` PyInstaller build sets `sys.stderr` to `None`. The resulting
`AttributeError` escaped the context manager into `_render_waveform`, which
`thumbs.ensure()` caught and turned into "no thumbnail". Only the audio path
used that helper, which is exactly why only audio broke.

Guard any `sys.stdout`/`sys.stderr` use with a None check in code that can run
frozen. Test it the cheap way rather than by rebuilding:

```python
import sys; sys.stderr = None    # what --windowed does
```

**Lesson:** verify the *shipped artifact*, not just the source. Two bugs in
this project — this one and the `ItemIsDragEnabled` flag — were invisible in
the environment they were developed in.

## Gotchas

- **`QtMultimedia` is NOT in `PySide6-Essentials`** (checked on 6.11.1 — it ships
  22 Qt modules and multimedia is not among them). Audition and video preview
  need `PySide6-Addons` as well. Both are installed.
- **libmpg123 writes ID3 warnings straight to file descriptor 2**, under
  libsndfile, so they cannot be filtered with `logging` and they bury hundreds of
  lines of real output. `probe.silence_native_stderr()` redirects the descriptor
  around the whole probe pass. Anything that wants to print progress during that
  window must use **stdout**.
- **The cache dir must be resolved from `%LOCALAPPDATA%`, never relative to the
  repo.** The source is reached from Windows as `\\wsl.localhost\Ubuntu\...` and
  sqlite locking over that path is broken and slow.
- **The username contains a space** (`Amreet khuntia`) — pass subprocess args as
  a list, never as a shell string.
- **`.sfk` files are Sound Forge peak sidecars** and make `soundfile` throw; they
  are blocklisted in `config.BLOCKED_EXTS` along with `.url`, `.ini` and friends.
- The SFX pack has an undocumented **`_Unorganised`** category folder, so the
  category list is derived at scan time and never hardcoded.

## Filename normalization

`stashlib/normalize.py` — the highest-value 60 lines in the project. The library
mixes incompatible naming regimes and naive matching fails on all of them:

| Raw stem | Normalized |
|---|---|
| `WaterPourChalice_S011WR.87` | `water pour chalice` |
| `MMFX_CHIME BRIGHT PERCUSSIVE_SB01.174` | `chime bright percussive` |
| `MarimbaAscend_BWU.148` | `marimba ascend` |
| `yt1s.com - Best Rage Of The Day  Episode 11_1080p` | `best rage of the day episode 11` |
| `Ah Shit Here We Go Again - GTA Sound Effect (HD) ( 160kbps )` | `ah shit here we go again gta` |
| `AYAYAYAYYYY - AWAKEN - Green Screen [Mpgun.com]` | `ayayayayyyy awaken green screen pantalla verde` |

Two subtleties that cost a debugging cycle each:

1. The vendor-serial pattern must allow **no digits** before the dot —
   `_BWU.148` is as valid as `_AP1.758`.
2. **Punctuation must be flattened before noise removal.** `_` is a regex word
   character, so in `Episode 11_1080p` there is no word boundary before `1080p`
   and `\b\d{3,4}p\b` silently fails to match.

Golden set: `CORPUS` in `stashlib/normalize.py`, run with
`python.exe -m stashlib.normalize` (20/20). Re-run after any pattern change.

## Golden search queries

`python.exe -m stashlib.cli search <query>` — all verified working:

| Query | Top hit | Proves |
|---|---|---|
| `air horn` | `Air Horn sound effect` | basic ranking |
| `water pour` | `WaterPour_AP1.1343` | CamelCase + vendor-serial normalization |
| `vine boom` | `Vine Boom`, with `Bass Boost` at #4 | alias expansion from `tags.json` |
| `green screen` | `Green Screen - Nice !!` | folder-derived tags |
| `whoosh` | `WhooshFastWipe_S011IE.447` | nested category folders |
| `explosion` | `Explosion` | exact-match beats prefix |

Favorites survive `DELETE FROM items` + a full rescan — verified. That is the
point of keeping `user_meta` in its own table keyed by **path** rather than by an
items rowid.

## TODO

- **MCP surface** (`tools/library.py`: `library_scan` / `library_search` /
  `library_insert`), registered by appending `library` to `server.py`'s
  `from tools import ...` line. `library_search` would work on the free edition
  since it never touches Resolve, and would give the `video-edit` skill a way to
  actually find "the airhorn". Deferred by choice, ~90 min.
- **Studio-only actions** — insert at playhead, import to bin. Note that
  `Project.InsertAudioToCurrentTrackAtPlayhead(path, 0, 0)` takes a **file path
  directly** with no media-pool import, which is strictly better than dragging
  for SFX. Untestable until Studio is installed.
- **`resolve/connection.py` helpers** — `ensure_bin(path)` and a
  `current_folder(folder)` contextmanager modelled on `comp_lock`. `ImportMedia()`
  targets whatever bin happens to be selected with no way to specify one, which
  makes `tools/edit.py:import_media` a latent bug today.
