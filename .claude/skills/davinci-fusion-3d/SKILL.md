---
name: davinci-fusion-3d
description: Build and light a 3D Fusion scene (Camera3D + Merge3D + Renderer3D + Text3D/Shape3D + lights, with motion blur) in DaVinci Resolve through the mcp-da-vinci tools. Use for 3D titles, extruded text, camera moves/fly-throughs, or any true-3D motion graphics — not flat 2D comps.
metadata:
  tags: davinci, resolve, fusion, 3d, motion-graphics, mcp
---

## When to use
Any time the result needs **real 3D** — a moving `Camera3D`, perspective/depth, extruded
text, or 3D motion blur. For flat 2D titles/lower-thirds use the 2D recipes in CLAUDE.md instead.

This skill is the **toolbox** (nodes, wiring, lighting, motion blur, gotchas). For *how the
camera moves through the scene*, see `davinci-3d-camera-move` — and read the next section first.

## Don't assume the staging — clarify it
3D layout is a creative choice and most requests are ambiguous. "A 3D fly-over of these
words" could mean floating elements in a corridor, objects on a table/ground, a top-down map
route, an orbit, a push-in… each implies a *different* scene layout, camera path, and lighting.
**Surface the options and confirm before building** (offer a recommended default), e.g. with
`AskUserQuestion`. Treat every coordinate below as something to derive from the chosen staging
and verify with `grab_frame`, never a fixed default. Common stagings:
- **Corridor fly-through** — elements float in depth (−Z), camera flies forward through them.
- **Fly-over a surface** — a ground plane / table / map; camera high, pitched down, moving across.
- **Top-down route** — overhead map look, a line tracing a path between points.
- **Orbit / arc** — camera circles a hero object or cluster.
- **Push-in / reveal** — dolly toward a single hero element.

## Golden rules (verified live, Resolve 19.1.3 Studio)
- **Prototype on a throwaway timeline** — there is no undo over scripting:
  `create_timeline` → `open_page edit` → `insert_fusion_composition` (5 s / 120f generator
  with only `MediaOut1`) → `set_playhead` onto the clip (the comp is only scriptable while
  loaded under the playhead) → `fusion_get_comp_info` for the frame mapping.
- **Discover input ids live** — never assume. `fusion_get_node --name X --filter <substring>`
  (3D nodes have 100–260 inputs; always filter). A verified starting-point cheatsheet of the
  common nodes' input ids/defaults is in the **`davinci-fusion-node-reference`** skill — read it
  instead of re-probing (saves tokens); still confirm anything load-bearing (version/font-dependent).
- **Verify numerically then visually** — `fusion_sample_input` for curves,
  `grab_frame --frame <timeline_frame>` for the render. `timeline_frame = timeline_start_frame
  + (comp_frame − global_start)`.

## Node registry ids (the ones that aren't the UI name)
- 3D core: `Camera3D`, `Merge3D`, `Renderer3D`, `Text3D`, `Shape3D`.
- Lights: **`LightDirectional`, `LightAmbient`** (also `LightPoint`, `LightSpot`) —
  *not* `DirectionalLight`/`AmbientLight`, those fail.

## Scene graph & wiring
```
[Camera3D, geometry…, LightDirectional, LightAmbient] → Merge3D → Renderer3D
Renderer3D → (optionally over a 2D Background via a Merge) → MediaOut1
```
- **Merge3D combines everything**, including the camera and lights. Connect each object to
  `SceneInput1`, `SceneInput2`, … **strictly in order** — each connect grows the next empty
  slot, so skipping ahead or connecting in parallel fails.
- `Renderer3D` scene input id is `SceneInput`. Its `Camera` auto-selects the one camera in
  the scene.
- For a backdrop: add a `Background` (set `TopLeftRed/Green/Blue`, default Solid black) and a
  2D `Merge`; wire `Background → Merge.Background`, `Renderer3D → Merge.Foreground`,
  `Merge → MediaOut1.Input`.

## Geometry by staging (build what the chosen staging needs, not a fixed set)
- A **ground/table/map** staging needs a surface: a large `Shape3D` plane (default
  `Shape=SurfacePlaneInputs`) or `ImagePlane3D`, with objects/labels sitting on it.
- A **corridor** staging needs no surface — elements just float in −Z.
- Thin rods/markers/route-lines are `Shape3D` cubes (see below).

## Camera setup & aim
- Move = keyframe `Transform3DOp.Translate.X/Y/Z`; orientation = `Transform3DOp.Rotate.X/Y/Z`.
  A fly-over pitches the camera down (`Rotate.X` negative) and translates across; a corridor
  mostly translates `Z`; an orbit animates position around a pivot.
- To keep the camera *pointed at* something while it moves, Camera3D has a target/aim mode —
  discover its ids live (`fusion_get_node --name Cam --filter target` / `aim`) rather than
  assuming; or animate `Rotate.*` by hand.
- Default `Camera3D.AoV` ≈ 19.26° horizontal (`AovType=0`). Frame check with `grab_frame`.

## Make it actually look 3D (lighting)
`Renderer3D` ships with **`RendererSoftware.LightingEnabled = 0`** → geometry renders flat
(extrusion invisible). To get depth shading:
1. `fusion_set_value R3D RendererSoftware.LightingEnabled 1`
2. Add `LightDirectional` + `LightAmbient`, connect both into Merge3D.
3. Aim the directional (e.g. `Transform3DOp.Rotate.X ≈ -30`, `.Y ≈ 25`, `Intensity ≈ 0.8`),
   ambient `Intensity ≈ 0.4` as fill — tune from grabs for the look you want.
- `RendererType` is already `RendererSoftware` (required for motion blur).

## Motion blur
On the `Renderer3D`: `MotionBlur=1`, then `Quality=16` (default 2 is too choppy),
`ShutterAngle=180`, `SampleSpread=1`. Only shows on moving objects; verify on an animated
frame. Higher `Quality` = slower grabs.

## Text3D
- text = `StyledText`; depth = `ExtrusionDepth` (default 0 = flat — set ~0.12); font size =
  `Size`; fill = `Red1/Green1/Blue1`.
- **Justification inputs are inert via scripting** — text stays left/baseline anchored.
  Center geometrically: px-per-world-unit ≈ `(imgW/2)/(d·tan(AoV/2))`; a 4-digit string at
  `Size 1` ≈ 0.89 world units wide, so set origin `X = center − width/2`, `Y ≈ −0.12`.

## Shape3D (rods, planes, markers, ground)
- Default `Shape` = `SurfacePlaneInputs`; set `Shape = SurfaceCubeInputs` for a cube.
- Independent cube dims need `SurfaceCubeInputs.SizeLock = 0`, then
  `SurfaceCubeInputs.Width/Height/Depth`.
- **Gotcha:** a new Shape3D spawns at `(0,0,0)` where the camera also sits — with the default
  additive blend the camera ends up *inside* it and the **whole frame renders white**. Move/
  size it out of the origin immediately after adding it.

## Animation primitives (reuse across stagings)
- Uniform scale "pop": set `Transform3DOp.ScaleLock=0`, then keyframe `Transform3DOp.Scale.X/Y/Z`
  together to `[0, 1.15, 1.0]` with `ease_out`.
- Camera/object move: keyframe `Transform3DOp.Translate.*` individually; `ease_in_out` for a
  cinematic start/stop, `linear` for constant speed (steadier motion blur).
- `fusion_set_keyframes` **replaces** all keys on an input and applies one easing across the curve.

## Fast debug checklist
- Whole frame white → a Shape3D/cube is at the origin engulfing the camera. Move it.
- Black / flat geometry → lighting enabled but no light connected, or `LightingEnabled` still 0.
- Node "not found" right after adding → comp reloaded by UI page switches; `fusion_list_nodes` once.

See `docs/fusion-3d-notes.md` for the open tooling TODOs that would shorten this recipe.
