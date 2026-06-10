# mcp-da-vinci

An [MCP](https://modelcontextprotocol.io) server that exposes the **DaVinci Resolve**
scripting API to an LLM. v1 covers **inspection**, **core editing** (import media, build
timelines, markers), and the **render queue**.

## How it connects (read this first)

Resolve scripting imports `DaVinciResolveScript`, which loads the native
`fusionscript.dll` and talks to the running Resolve process over local IPC. That DLL is a
**Windows** binary, so **the server must be run by Windows Python** — a Linux/WSL
interpreter cannot load it. The source lives in WSL; Claude Code launches the Windows
interpreter (`python.exe`) to run it.

```
mcp-da-vinci/
├── server.py            # FastMCP entrypoint + transport selection
├── resolve/
│   ├── app.py           # shared FastMCP instance
│   └── connection.py    # get_resolve(): loads the API, env fallbacks, helpers
├── tools/
│   ├── inspect.py       # read-only tools
│   ├── edit.py          # media-pool + timeline mutations
│   └── render.py        # render-queue tools
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

1. **Install the MCP SDK into Windows Python** (the interpreter that can reach Resolve):
   ```
   python.exe -m pip install "mcp[cli]"     # or: python.exe -m pip install -r requirements.txt
   ```
2. In Resolve: **Preferences → System → General → External scripting using → `Local`**,
   then restart Resolve.
3. Resolve must be **running** for any tool call to work.
4. External scripting requires **DaVinci Resolve Studio** (the free edition only allows
   scripting from the Fusion console). If the connection test below fails on the free
   edition, this is why.

This machine's verified paths (already baked into `.mcp.json` and as fallbacks in
`resolve/connection.py`):

| | Path |
|---|---|
| Resolve DLL | `D:\Program Files\BlackMagic\fusionscript.dll` |
| Scripting API root | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting` |
| Windows Python | `E:\Python\python.exe` (a.k.a. `python.exe` from WSL) |

## Verify

With Resolve running, from the repo dir in WSL:

```bash
# 1. Bare connection test (catches prefs / Studio issues before MCP is involved)
python.exe -c "import resolve.connection as c; print(c.get_resolve().GetProductName())"
# -> DaVinci Resolve

# 2. Call any tool like a function via the dev CLI (fastest debug loop)
python.exe cli.py                                   # list all 21 tools (grouped)
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
21 tools loaded. Type /help for the list, /quit to exit.
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
`append_clips_to_timeline`, `set_current_timeline`, `add_timeline_marker`, `open_page`

**Render** — `list_render_formats`, `list_render_codecs`, `set_render_format_and_codec`,
`add_render_job`, `start_render`, `stop_render`, `get_render_status`

**Fusion** (node graph on a timeline clip's comp — defaults to the playhead clip; target others
with `--clip_name` / `--comp_index` / `--comp_name`)
- *Comps* — `fusion_list_comps`, `fusion_add_comp`, `fusion_set_active_comp`
- *Graph* — `fusion_list_nodes`, `fusion_add_node`, `fusion_insert_node` (auto-wires
  `MediaIn1 → node → MediaOut1`), `fusion_connect`, `fusion_delete_node`, `fusion_rename_node`
- *Pull config* — `fusion_get_node` (ids + datatypes + values + animated/expression),
  `fusion_get_node_settings` (full `GetCurrentSettings` dump), `fusion_get_keyframes`
- *Set params* — `fusion_set_value` (Number), `fusion_set_text` (Text/FuID),
  `fusion_set_point` (2D, 0..1 space), `fusion_set_expression`
- *Animate* — `fusion_set_keyframe`, `fusion_delete_animation`
- *Presets* — `fusion_save_node_setting`, `fusion_load_node_setting`, `fusion_import_setting`

The read-current-state-then-edit loop: `fusion_get_node` (find the input id + datatype) →
`fusion_set_value`/`fusion_set_keyframe`. Node types use Fusion registry ids (`Blur`, `Merge`,
`Transform`, `TextPlus`, …); input ids vary per node (a Blur's strength is `XBlurSize`, not `Blur`).

```bash
python.exe cli.py fusion_insert_node --node_type Blur --name MyBlur   # splice into the chain
python.exe cli.py fusion_get_node --name MyBlur                       # discover input ids
python.exe cli.py fusion_set_value --node MyBlur --input_id XBlurSize --value 25
python.exe cli.py fusion_set_keyframe --node MyBlur --input_id XBlurSize --value 0 --frame 0
```

> Note: auto-animating an input (first `fusion_set_keyframe`) seeds an extra keyframe at the
> playhead's current frame. Read tools (`fusion_list_*`, `fusion_get_*`) are non-destructive; all
> others mutate the open project — test graph edits on a throwaway clip first.

## OpenAI-compatible / HTTP transport (future)

The same server runs over streamable HTTP for an OpenAI-function-calling bridge:

```bash
RESOLVE_MCP_TRANSPORT=streamable-http python.exe server.py
```

No code changes needed beyond the transport switch already in `server.py`.
