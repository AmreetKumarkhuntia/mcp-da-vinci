# Meme & SFX Library

A searchable browser for your meme clips, green screens, sound effects and
overlays — that **drags straight into DaVinci Resolve**.

Everything it needs is in this one folder. It is standalone: it does not import
the MCP server, and it does **not** need DaVinci Resolve Studio. It works on the
free edition, because it talks to Resolve the same way Windows Explorer does.

---

## Install

Double-click **`install.bat`**.

It finds your Python, installs the dependencies (~250 MB of Qt the first time),
draws the app icon, and puts a shortcut on your Desktop and in the Start Menu.

If you'd rather do it by hand:

```
python.exe -m pip install -r requirements.txt
python.exe scripts/make_icon.py
python.exe scripts/install_shortcut.py
```

Needs **Python 3.10+** on Windows. (This repo's Resolve tooling runs under
Windows Python at `E:\Python\python.exe`; the panel uses the same one.)

## Run

Any of these:

- the **Desktop / Start Menu shortcut** created by the installer
- double-click **`run_panel.bat`**
- `python.exe -m panel` from this folder

First launch asks you to pick folders. Point it at anything — memes, SFX packs,
green screens, overlays, gifs, thumbnails. Sub-folders are included and their
names become searchable tags automatically, so a file in
`SFX Pack\Alarm & Chime\` is findable by typing `alarm` or `chime`.

## Getting things into Resolve

**Drag the tile out of the panel and drop it where you want it.** That's it.

| Drop it on | What happens |
|---|---|
| the **Media Pool** | the file is imported as a clip — the reliable path |
| the **timeline** | it lands as a clip at the drop point |
| an **audio track** | drop sound effects straight onto A1/A2 |

Select several tiles with Ctrl or Shift and drag them all at once. The panel
fades to 25% while you drag so you can see what you're aiming at.

There is no Resolve API involved — the panel puts a normal Windows file drag
(`CF_HDROP`) on the clipboard, byte-for-byte what Explorer produces. That is why
it works without Studio, and it is the same trick the commercial panels (SNS
ShareBrowser, Sony Ci) use. Verified with `scripts/spike_drag.py`, which stays
here as the regression harness: if a Resolve update ever breaks dragging, run it
and you'll know in ten seconds whether it's Resolve or the panel.

**Tip:** keep the panel always-on-top (the 📌 button) beside Resolve, or leave it
minimised and summon it with **Ctrl+Shift+M**, type, drag, and it gets out of
the way.

## Keys

| Key | Action |
|---|---|
| type anything | live search |
| `↑ ↓ ← →` | move through results — sounds auto-play as you go |
| `Space` | play / stop the selected item |
| `F` | favourite |
| `Ctrl+1..4` | All / Video / Audio / Image |
| `Ctrl+F` | jump to the search box |
| `Ctrl+C` | copy the file path |
| `Ctrl+R` | rescan folders |
| `Esc` | clear the search, or minimise |
| `Ctrl+Shift+M` | summon the panel over Resolve from anywhere |

Buttons: **★** favourites only · **🔊** auto-play on/off · **▤** compact mode ·
**📌** always on top · **＋** folders · **⟳** rescan.

## Search

Filenames in a real SFX pack are hostile to plain matching, so every name is
normalised first:

| On disk | Searchable as |
|---|---|
| `WaterPourChalice_S011WR.87.mp3` | `water pour chalice` |
| `MMFX_CHIME BRIGHT PERCUSSIVE_SB01.174.mp3` | `chime bright percussive` |
| `Ah Shit Here We Go Again - GTA Sound Effect (HD) ( 160kbps ).mp3` | `ah shit here we go again gta` |
| `yt1s.com - Best Rage Of The Day  Episode 11_1080p.mp4` | `best rage of the day episode 11` |

Vendor serials, ripper-site tags, bitrate/resolution noise and glued CamelCase
all get stripped, so typing what you actually mean finds the file.

**Aliases** let you name things the way you think of them. Edit
`%LOCALAPPDATA%\mcp-da-vinci\library\tags.json`:

```json
{
  "aliases": { "vine boom": ["bass boost", "bruh"] },
  "path_tags": { "D:\\videos\\meme\\Green Screen": ["greenscreen", "chroma"] },
  "hide": ["*.sfk", "*.url", "desktop.ini"]
}
```

Now typing `bruh` finds `Bass Boost.mp3`.

## Folders

Click **＋** to add or remove folders at any time. Removing a folder keeps your
favourites and tags, so re-adding it restores them.

The index and thumbnail cache live in
`%LOCALAPPDATA%\mcp-da-vinci\library\` — never inside this folder, so you can
move or reinstall the plugin without losing anything. Delete that folder to
start clean.

## Distributing it — installer with uninstall

```
python.exe scripts/build_installer.py
```

Produces **one file**, `MemeSFXLibrary-Setup-1.0.0.exe` (~77 MB), under
`%LOCALAPPDATA%\mcp-da-vinci\build\installer\`. Send that to anyone. It:

- installs **per-user, with no admin rights** (into `%LOCALAPPDATA%\Programs`)
- creates Start Menu and optional Desktop shortcuts
- registers properly in **Settings → Apps → Installed apps**, so it uninstalls
  like any other program
- needs **no Python** on the target machine

Needs Inno Setup once on the *build* machine:
`winget install JRSoftware.InnoSetup`. Use `--skip-app` to recompile just the
installer from the last app build (~40 s instead of ~5 min).

Silent install / uninstall, for scripted deployment:

```
MemeSFXLibrary-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
"%LOCALAPPDATA%\Programs\MemeSFXLibrary\unins000.exe" /VERYSILENT
```

**Uninstalling never touches your library data unless you say so.** An
interactive uninstall asks whether to also delete the index, thumbnails,
favourites and tags in `%LOCALAPPDATA%\mcp-da-vinci\library\`, defaulting to
keeping them. A *silent* uninstall always keeps them — `/SUPPRESSMSGBOXES`
answers prompts with Yes regardless of the declared default, so the script skips
the question entirely rather than risk deleting data unattended.

### Just the app folder, no installer

```
python.exe scripts/build_exe.py
```

A one-folder app (~245 MB) under `%LOCALAPPDATA%\mcp-da-vinci\build\dist\`. Zip
and send; they double-click `MemeSFXLibrary.exe`. `--onefile` makes a single
executable (slower to start — it unpacks each run), `--outdir` builds elsewhere.

> Not a DLL, deliberately. A DLL is loaded *by* a host process and cannot be
> launched or installed on its own; there is no host here. Resolve's only
> DLL-shaped plugins are OFX effects, which process frames and cannot draw a
> browser UI.

## Command line

The core (`medialib/`) has no Qt in it and runs on its own — useful for
scripting, and it's how the search ranking gets tuned:

```
python.exe -m medialib.cli scan
python.exe -m medialib.cli search "air horn"
python.exe -m medialib.cli search whoosh --kind audio --limit 10
python.exe -m medialib.cli roots --add "D:\videos\overlays" --label Overlays
python.exe -m medialib.cli tags
python.exe -m medialib.normalize          # filename-normaliser self-test
```

## Layout

```
meme-sfx-library/
├── install.bat            one-time setup: deps + icon + shortcuts
├── run_panel.bat          double-click to launch
├── requirements.txt
├── installer/
│   └── MemeSFXLibrary.iss Inno Setup script -> Setup.exe with uninstaller
├── medialib/              core: scan, index, search, thumbnails  (no Qt)
├── panel/                 the PySide6 window
├── scripts/
│   ├── make_icon.py       draws panel/icon.ico
│   ├── install_shortcut.py  Desktop + Start Menu (--remove to undo)
│   ├── build_exe.py       standalone .exe via PyInstaller
│   ├── build_installer.py distributable Setup.exe via Inno Setup
│   └── spike_drag.py      drag-into-Resolve regression harness
└── NOTES.md               measurements, gotchas, TODOs
```

## If something goes wrong

- **Nothing happens on double-click** — `run_panel.bat` uses `pythonw.exe`,
  which has no console. Check `%TEMP%\meme-sfx-panel.log`.
- **Empty grid** — click **＋** and add a folder, then **⟳**.
- **Drag does nothing** — if Resolve was started *as administrator* and the
  panel wasn't, Windows blocks the drag by design. Run both the same way.
- **`Ctrl+Shift+M` does nothing** — another app owns it; the status bar says so
  at startup. Everything else still works.
- **Rebuilding from scratch** — delete
  `%LOCALAPPDATA%\mcp-da-vinci\library\` and relaunch.
