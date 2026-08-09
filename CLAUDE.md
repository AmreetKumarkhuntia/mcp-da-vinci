# CLAUDE.md

MCP server exposing DaVinci Resolve's scripting API. Everything here runs under
**Windows Python** (`python.exe` from WSL) because `fusionscript.dll` is a Windows
binary — never use a WSL `python` for server, CLI, or one-off probes.

## Architecture

`server.py` imports `resolve/app.py`'s shared FastMCP instance, then the `tools/*`
modules, whose `@mcp.tool()` decorators register everything. `resolve/connection.py`
owns the Resolve handle (`get_resolve()`, cached) plus comp/clip helpers. Dev loop:
`python.exe cli.py <tool> --arg value` (one-shot) or `python.exe console.py` (warm
REPL, slash commands). Windows paths everywhere a file reaches Resolve.

## Fusion: the two time domains

- **Timeline frames are absolute**: `get_timeline_info.start_frame` is e.g. 86400
  (= 01:00:00:00 @ 24 fps). `set_playhead --frame` and `grab_frame --frame` use these.
- **Fusion keyframes are comp-relative**: usually 0..duration-1. Always call
  `fusion_get_comp_info` first; it returns `render_start/render_end` (valid key range)
  and the mapping: `timeline_frame = timeline_start_frame + (comp_frame - global_start)`.

## The motion-graphics loop

1. `fusion_get_comp_info` — frame range + timeline mapping.
2. `fusion_get_node --name X --filter <substring>` — discover input ids + datatypes
   (always filter on big nodes; TextPlus has ~300 inputs).
3. Set: `fusion_set_value` / `fusion_set_text` / `fusion_set_point` (statics),
   `fusion_set_keyframes` (whole curve incl. easing), `fusion_set_point_keyframe`
   (motion paths).
4. Verify numerically: `fusion_sample_input --frames a --frames b ...`.
5. Verify visually: `grab_frame --frame <timeline_frame>` — you get the rendered image.
   To judge *motion* across a sequence in one round-trip, `grab_frames --frames a
   --frames b …` returns a single labeled contact sheet (≤16 frames).
6. Adjust and repeat.

## Verified API facts (probed live on Resolve 19.1.3, don't rediscover)

- Script-created keyframes interpolate **linearly** by default. Easing comes from
  BezierSpline handle tables — `fusion_set_keyframes --interpolation` handles this;
  the spline `Flags` route (`Linear`/`StepIn`) does NOT work over remote scripting.
- A clip's comp is scriptable only while **loaded** (clip under the playhead on the
  topmost visible track). Other clips' comp handles answer with an empty tool list;
  `get_comp` raises an actionable error for this. Fix: `set_playhead` onto the clip.
- Modifier registry ids: `PerturbNumber` / `PerturbPoint` (UI "Perturb"), `Shake`,
  `StyledTextFollower` (UI "Follower"), `XYPath`, `Path`. `fusion_add_modifier`
  aliases `Perturb`/`Follower` to the right ids. Modifiers appear in
  `fusion_list_nodes` and are addressable by name like any node.
- `fusion_add_node` aliases friendly light names to registry ids
  (`DirectionalLight`→`LightDirectional`, plus `AmbientLight`/`PointLight`/`SpotLight`).
- `fusion_get_node` lists a FuID (combo) input's selectable `options` when Fusion
  exposes them (e.g. `Renderer3D.RendererType`, `Shape3D.Shape`) — pick from those
  rather than guessing the FuID string.
- `SetCurrentTimecode` is rejected on the fusion/media pages (`grab_frame` and
  `set_playhead` know this; `grab_frame` does the page dance itself).
- `GrabStill` works from any page; `ExportStills` also emits a `.drx` sidecar.
- Common input ids: Blur strength = `XBlurSize`; Transform = `Center`/`Size`/`Angle`;
  Merge opacity = `Blend`; TextPlus text = `StyledText`, size = `Size`, color =
  `Red1`/`Green1`/`Blue1`/`Alpha1`.

## Timeline editing & cuts (Resolve 21)

`tools/editing.py` does assembly/cut editing, not just Fusion. Resolve **21** added the
native primitives (reachable only over *external* scripting, so Studio in
practice — see Editions below): `detect_scene_cuts` splits one continuous
recording into per-take clips; `delete_timeline_clips --indices N --ripple true` drops
clips and closes the gap (DESTRUCTIVE — no undo, prototype on a throwaway timeline);
`set_clip_enabled` mutes a take reversibly; read the current cut with `get_timeline_edl`.
Transcript-driven rough cut: `transcribe_timeline` → `get_transcript` → pick bad clips →
`delete_timeline_clips`. There is still **no** in-place blade/trim/slip at an arbitrary
frame, so cutting a bad span out of the *middle* of one take uses
`build_timeline_from_segments` (rebuild the kept ranges). The DLL moved to
`D:\Program Files\DaVinci 21\fusionscript.dll`; `connection.py` auto-discovers it and
`os.add_dll_directory`s its folder.

## Editions: what the free build can and cannot do

Earlier notes here said the free edition "can't script at all". That is wrong and it blocked
work for a while. The real split:

| | Free | How |
|---|---|---|
| **Internal** scripting — `Workspace > Scripts`, Fusion Console | ✅ works | The host injects `resolve` / `project`; no DLL import, no permission needed |
| **External** scripting — `fusionscript.scriptapp("Resolve")`, i.e. this MCP server | ❌ | Returns `None` from an outside process |

Resolve's own API reference is explicit (`…\Developer\Scripting\README.txt`, "Studio and AI
Scripting APIs"): *"The DaVinci Resolve scripting APIs cover a common superset of functions
for both the Free and Studio versions."* Only named functions are Studio-gated
(`CreateSubtitlesFromAudio`, `TranscribeAudio`, IntelliSearch, `GenerateSpeech`), and some of
those additionally need an Extras download.

`SystemError: initialization of fusionscript failed` is **interpreter-specific, not
edition-specific** — probed live on this machine:

| Interpreter | `import fusionscript` |
|---|---|
| `E:\Python\python.exe` 3.12.8 | ✗ SystemError |
| Blender's 3.13.9, UE 5.8's 3.11.8 | ✗ SystemError |
| MS Store `python3.13.exe` 3.13.14 | ✓ imports clean |

Under the working import, `scriptapp("Resolve")` returns `None`. Two candidate causes remain
unseparated: the free edition, and `Preferences > System > General > External scripting
using` not being set to `Local`. Flip the pref and re-test before concluding it's the edition.

**Practical upshot for anything new:** if it must work on free, put it behind an internal
script (`…\AppData\Roaming\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`,
which lands in `Workspace > Scripts`), not behind this MCP server.

## Recipes (all primitives verified)

- **Blank canvas**: `insert_fusion_composition` on an empty timeline spot → a 5s
  generator clip whose comp has only `MediaOut1`. Build on it: `fusion_add_node`
  TextPlus → `fusion_connect --source Txt1 --dest MediaOut1 --dest_input Input`.
- **Fade in/out**: `fusion_set_keyframes` on the Merge's `Blend` (0→1 in, 1→0 out)
  with `--interpolation ease_in_out`. (TextPlus connected straight to MediaOut has no
  Merge — insert a Merge over a Background, or key TextPlus `Opacity1`.)
- **Slide-in**: `fusion_set_point_keyframe` on `Center`, e.g. (-0.2, 0.5)@0 →
  (0.5, 0.5)@18. Point space is 0..1, (0.5, 0.5) = frame center.
- **Pop/scale**: `fusion_set_keyframes` on `Size` with `ease_out`.
- **Wiggle**: `fusion_add_modifier --node X --input_id Center --modifier_type Perturb`,
  then `fusion_get_node --name Perturb1` and set its `Strength`/`Speed`.
- **Per-character text reveal**: `fusion_add_modifier --node Txt1 --input_id
  StyledText --modifier_type Follower` → inspect `Follower1` with `fusion_get_node`
  (filter `delay`/`opacity`) and key its per-character params.
- **Step/hold animation**: `--interpolation hold` (emulated with a duplicate key one
  frame before each jump).

## Gotchas

- Mutating tools change the open project immediately; there is no undo over scripting.
  Prototype on a throwaway timeline (`create_timeline` + `insert_fusion_composition`).
- `fusion_set_keyframes` REPLACES all existing keys on that input (by design: it
  defines the curve). `fusion_set_keyframe` (singular) only upserts one key.
- `fusion_delete_animation` keeps the current on-screen value as the new static value.
- If a node you just added isn't found a moment later, the comp was reloaded by
  concurrent UI activity (page switches) — re-check with `fusion_list_nodes` once
  before assuming it's gone.
- `.setting` paths and render/import paths are Windows paths on the Resolve machine.

## 3D motion graphics — use the skills, don't re-derive

3D work (camera moves, extruded text, motion blur) lives in skills so sessions stay cheap —
prefer them over re-probing or re-deriving:
- `davinci-fusion-node-reference` — verified node input-id cheatsheet; read it **instead of**
  `fusion_get_node` on 100–260-input nodes (saves tokens).
- `davinci-fusion-3d` — 3D scene toolbox (wiring, lighting, motion blur, gotchas).
- `davinci-3d-camera-move` — staging-first camera-move recipe (clarify the staging first).
- `docs/fusion-3d-notes.md` — known limits + tooling TODOs. Notably: the generator clip is a
  fixed **5 s** and has **no script resize**, so 8 s/16 s requests need a manual drag-extend + re-time.
- 3D conveniences (prefer over raw setters): `fusion_connect_scene` (next free Merge3D
  `SceneInput`), `fusion_enable_lighting` / `fusion_enable_motion_blur` (one-shot Renderer3D
  setup), `fusion_set_xyz` / `fusion_set_scale3d` (clears ScaleLock) / `fusion_set_color`.
