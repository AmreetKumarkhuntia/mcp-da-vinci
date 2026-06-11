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
- `SetCurrentTimecode` is rejected on the fusion/media pages (`grab_frame` and
  `set_playhead` know this; `grab_frame` does the page dance itself).
- `GrabStill` works from any page; `ExportStills` also emits a `.drx` sidecar.
- Common input ids: Blur strength = `XBlurSize`; Transform = `Center`/`Size`/`Angle`;
  Merge opacity = `Blend`; TextPlus text = `StyledText`, size = `Size`, color =
  `Red1`/`Green1`/`Blue1`/`Alpha1`.

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
