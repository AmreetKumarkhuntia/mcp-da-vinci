# mcp-da-vinci

An [MCP](https://modelcontextprotocol.io) server that exposes the **DaVinci Resolve**
scripting API to an LLM. Covers **inspection**, **core editing** (import media, build
timelines, markers, playhead), the **render queue**, the **Fusion node graph** (motion
graphics: nodes, keyframes with easing, motion paths, modifiers), and **frame capture** —
`grab_frame` returns the rendered timeline frame as an image, so the model can *see* what
it just edited.

## How it connects (read this first)

Resolve scripting imports `DaVinciResolveScript`, which loads the native
`fusionscript.dll` and talks to the running Resolve process over local IPC. That DLL is a
**Windows** binary, so **the server must be run by Windows Python** — a Linux/WSL
interpreter cannot load it. The source lives in WSL; Claude Code launches the Windows
interpreter (`python.exe`) to run it.

```
mcp-da-vinci/
├── server.py            # FastMCP entrypoint + transport selection
├── cli.py               # dev CLI: call any tool as python.exe cli.py <tool> --arg v
├── console.py           # interactive REPL with one warm Resolve connection
├── resolve/
│   ├── app.py           # shared FastMCP instance
│   └── connection.py    # get_resolve(): loads the API, env fallbacks, helpers
├── tools/
│   ├── inspect.py       # read-only tools
│   ├── edit.py          # media-pool + timeline mutations, playhead, pages
│   ├── render.py        # render-queue tools
│   ├── fusion.py        # Fusion node graph: build, inspect, animate
│   └── frames.py        # grab_frame: timeline frame -> MCP image content
├── .mcp.json            # Claude Code registration (project scope)
└── requirements.txt
```

## Project tooling

- **Python deps** are declared in `pyproject.toml` (locked in `uv.lock`). Note the runtime
  twist below: the server must run under **Windows Python**, which uv (in WSL) does not
  manage — so deps still get installed into Windows Python with `pip`. `uv` is for
  dependency declaration/dev work; `requirements.txt` is kept as a pip-friendly mirror.
- **Node tooling** (the MCP Inspector) is in `package.json`. `npm install`, then
  `npm run inspector`.

## Prerequisites

1. **Install the deps into Windows Python** (the interpreter that can reach Resolve):
   ```
   python.exe -m pip install "mcp[cli]" pillow     # or: python.exe -m pip install -r requirements.txt
   ```
   (`pillow` is used by `grab_frame` to downscale/re-encode captured frames.)
2. In Resolve: **Preferences → System → General → External scripting using → `Local`**,
   then restart Resolve.
3. Resolve must be **running** for any tool call to work.
4. External scripting — which is what this server does — requires **DaVinci Resolve Studio**.
   The free edition still scripts happily *from inside Resolve* (`Workspace > Scripts`, the
   Fusion Console), where the host injects `resolve` and `project`; it just won't hand an
   application object to an outside process. If the connection test below fails on the free
   edition, this is why.

This machine's verified paths (already baked into `.mcp.json` and as fallbacks in
`resolve/connection.py`):

| | Path |
|---|---|
| Resolve DLL | `D:\Program Files\DaVinci 21\fusionscript.dll` (Resolve 21; `connection.py` discovers it across known locations and registers its folder with `os.add_dll_directory` so sibling DLLs load) |
| Scripting API root | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` |
| Windows Python | `E:\Python\python.exe` (a.k.a. `python.exe` from WSL) |

> **Edition caveat:** the v21 build installed here is the **free** edition, so the connection
> test below is not expected to pass until **Resolve Studio 21** is installed/activated.
>
> Two failure modes get confused here; they are different problems.
>
> - `SystemError: initialization of fusionscript failed` is **the interpreter, not the
>   edition.** Probed live: `E:\Python` 3.12.8, Blender's 3.13.9 and UE 5.8's 3.11.8 all fail;
>   the MS Store `python3.13.exe` (3.13.14) imports the same DLL cleanly. The root cause of
>   the difference is unknown and wasn't worth chasing — just use an interpreter that works.
> - `scriptapp("Resolve")` returning `None` is the real edition/permission signal. Set
>   `External scripting using` → `Local` and restart before blaming the edition; that pref
>   has not been ruled out on this machine.

## Verify

With Resolve running, from the repo dir in WSL:

```bash
# 1. Bare connection test (catches prefs / Studio issues before MCP is involved)
python.exe -c "import resolve.connection as c; print(c.get_resolve().GetProductName())"
# -> DaVinci Resolve

# 2. Call any tool like a function via the dev CLI (fastest debug loop)
python.exe cli.py                                   # list all tools (grouped by module)
python.exe cli.py get_timeline_info --name "Timeline 1"
python.exe cli.py <tool> --help                     # show a tool's parameters
python.exe cli.py import_media --paths "D:\\a.mp4" --paths "D:\\b.mp4"   # repeat flag for arrays
python.exe cli.py <tool> ... --debug                # full traceback on error
# or via npm:  npm run cli -- get_timeline_info --name "Timeline 1"

# 3. Interactive tool testing via the MCP Inspector
npm install        # one-time
npm run inspector  # launches @modelcontextprotocol/inspector against python.exe server.py
```

Arg types (int / array / optional) are coerced automatically from each tool's JSON schema.

### Interactive console (`console.py`)

Prefer a long-running session? `console.py` holds one warm Resolve connection and takes
slash commands until you `/quit`:

```text
$ python.exe console.py          # or: npm run console
Connected: DaVinci Resolve Studio 19.1.3.7
51 tools loaded. Type /help for the list, /quit to exit.
resolve> /list_timelines
resolve> /get_timeline_info --name "Timeline 1"
resolve> /help create_timeline
resolve> /create_timeline --name smoke-test
resolve> /quit
```

Same arg syntax as the CLI (`--key value`, repeat a flag for arrays, `--debug` for tracebacks).
Bad args / tool errors are printed but don't drop the session.

## Use from Claude Code

`.mcp.json` registers the server at project scope. Restart Claude Code (or run `/mcp`) so it
loads, then ask things like *"list my Resolve timelines"* or *"create a timeline called
Test"*. If you cloned to a different WSL distro/path, update the UNC path in `.mcp.json`
(`\\wsl.localhost\<distro>\<path>\server.py`).

## Tools

**Inspect** — `get_resolve_info`, `list_projects`, `get_current_project_info`,
`list_timelines`, `get_timeline_info`, `list_media_pool`, `get_render_queue`

**Edit** — `import_media`, `create_timeline`, `create_timeline_from_clips`,
`append_clips_to_timeline`, `set_current_timeline`, `add_timeline_marker`, `open_page`,
`set_playhead` (timecode or absolute frame; rejected on the fusion/media pages),
`insert_fusion_composition` (empty Fusion generator clip — the blank canvas for titles)

**Render** — `list_render_formats`, `list_render_codecs`, `set_render_format_and_codec`,
`add_render_job`, `start_render`, `stop_render`, `get_render_status`

**Frames** — `grab_frame [--timecode | --frame] [--max_width] [--jpeg_quality]`: captures the
rendered timeline frame (grades + Fusion output included) and returns it as MCP image
content, so the model can see its edit. Round-trips through the gallery
(`GrabStill → ExportStills → cleanup`); briefly switches to the color page only when the
playhead must move while on the fusion/media pages, and restores the page after. Via the
CLI/console the image is saved to a temp file and its path printed.

**Fusion** (node graph on a timeline clip's comp — defaults to the playhead clip; target others
with `--clip_name` / `--comp_index` / `--comp_name`)
- *Comps* — `fusion_list_comps`, `fusion_add_comp`, `fusion_set_active_comp`,
  `fusion_get_comp_info` (comp time ranges + timeline mapping — read this before animating),
  `fusion_set_comp_time`
- *Graph* — `fusion_list_nodes`, `fusion_add_node`, `fusion_insert_node` (auto-wires
  `MediaIn1 → node → MediaOut1`), `fusion_connect`, `fusion_delete_node`, `fusion_rename_node`
- *Pull config* — `fusion_get_node` (ids + datatypes + values + animated/expression; use
  `--filter` on huge nodes — TextPlus has ~300 inputs), `fusion_get_node_settings` (full
  `GetCurrentSettings` dump), `fusion_get_keyframes` (rich per-key table for splines),
  `fusion_sample_input` (evaluate an input at given frames — verify animation numerically)
- *Set params* — `fusion_set_value` (Number), `fusion_set_text` (Text/FuID),
  `fusion_set_point` (2D, 0..1 space), `fusion_set_expression`
- *Animate* — `fusion_set_keyframe` (single), `fusion_set_keyframes` (batch, defines the
  whole curve with `--interpolation linear|ease_in|ease_out|ease_in_out|hold`),
  `fusion_set_point_keyframe` (motion paths via XYPath), `fusion_add_modifier`
  (Perturb/Shake/Follower/...), `fusion_delete_animation` (keeps the on-screen value)
- *Presets* — `fusion_save_node_setting`, `fusion_load_node_setting`, `fusion_import_setting`

The edit loop: `fusion_get_comp_info` (frame range) → `fusion_get_node --filter ...` (find the
input id + datatype) → set values / keyframes → `fusion_sample_input` (numeric check) →
`grab_frame` (visual check). Node types use Fusion registry ids (`Blur`, `Merge`, `Transform`,
`TextPlus`, …); input ids vary per node (a Blur's strength is `XBlurSize`, not `Blur`).

```bash
python.exe cli.py fusion_insert_node --node_type Blur --name MyBlur   # splice into the chain
python.exe cli.py fusion_get_node --name MyBlur --filter blur         # discover input ids
python.exe cli.py fusion_set_keyframes --node MyBlur --input_id XBlurSize \
    --frames 0 --frames 24 --values 25 --values 0 --interpolation ease_out
python.exe cli.py grab_frame --frame 86412                            # look at the result
```

> Notes: a clip's comp is only scriptable while it is the **loaded** comp (playhead on the
> clip, topmost visible track) — the tools raise a clear error otherwise. Read tools
> (`fusion_list_*`, `fusion_get_*`, `fusion_sample_input`) are non-destructive; all others
> mutate the open project — test graph edits on a throwaway clip first.

## OpenAI-compatible / HTTP transport (future)

The same server runs over streamable HTTP for an OpenAI-function-calling bridge:

```bash
RESOLVE_MCP_TRANSPORT=streamable-http python.exe server.py
```

No code changes needed beyond the transport switch already in `server.py`.
