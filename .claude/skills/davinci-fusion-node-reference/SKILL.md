---
name: davinci-fusion-node-reference
description: Verified input-id cheatsheet for the common DaVinci Fusion nodes used in 3D motion graphics (Camera3D, Merge3D, Renderer3D, Text3D, Shape3D, LightDirectional/Ambient, Background, Merge), probed live via the mcp-da-vinci tools. Consult this BEFORE re-probing — fusion_get_node on these nodes returns 100–260 inputs each, so reading this instead saves tokens and time. Confirm load-bearing ids live since they are version/font-dependent.
metadata:
  tags: davinci, resolve, fusion, 3d, reference, input-ids, mcp
---

## When to use
Whenever you need a Fusion node's input id (to `fusion_set_value` / `fusion_connect` /
`fusion_set_keyframes` / `fusion_set_text`). Read the relevant block here instead of calling
`fusion_get_node` on a 100–260-input node and paying for the dump. These were probed live on
**Resolve 19.1.3.7 Studio**; ids are version/font-dependent, so confirm anything load-bearing
with `fusion_get_node --name X --filter <substring>`. For the build recipes see the
`davinci-fusion-3d` and `davinci-3d-camera-move` skills.

Format: `id` (datatype, default) — note. Every 3D node also carries the shared `Transform3DOp.*`
block (bottom).

---

## Camera3D  (~149 inputs)
- `AoV` (Number, 19.26) — angle of view °; `AovType` (Number, 0 = horizontal).
- `Fit` / `ResolutionGateFit` (FuID, "Height"), `ProjectionFitMethod` (FuID, "Inside").
- `PlaneOfFocus` (Number, 4.0), `PlaneOfFocusVis` (0) — DoF focus distance.
- `ImagePlaneEnabled` (Number, 1) — camera's built-in image plane (renders an image wired to the
  camera, sized via `SurfacePlaneInputs.*`); harmless when nothing is connected.
- Aim/target: **not probed** — discover with `--filter target` / `aim` before using.
- Move/orient via `Transform3DOp.Translate.*` / `Transform3DOp.Rotate.*`.

## Merge3D  (~38+ inputs) — the 3D scene combiner
- `SceneInput1`, `SceneInput2`, … (DataType3D) — connect each child (geometry, camera, lights)
  **strictly in order**; every connection grows one new empty trailing slot. No skip/parallel.
- Has its own `Transform3DOp.*` — transforms the whole merged scene at once.

## Renderer3D  (~110 inputs) — 3D → 2D image
- `SceneInput` (DataType3D) — scene in (from Merge3D); auto-selects the scene's Camera3D.
- `RendererType` (FuID, "RendererSoftware") — software is required for motion blur.
- `RendererSoftware.LightingEnabled` (Number, **0**) — OFF by default → geometry flat; set 1
  for shading. `RendererSoftware.ShadowsEnabled` (0). `RendererSoftware.Channels.*` aux passes.
- Motion blur: `MotionBlur` (Number, 0) → 1; then `Quality` (Number, **2** → ~16),
  `ShutterAngle` (Number, 180), `SampleSpread` (Number, 1).

## Text3D  (~257 inputs) — auto-spawns a `…ExtrusionProfile` LUTBezier helper node
- Text: `StyledText` (Text, "") — the string. `TextText` (Number, 1).
- Size: `Size` (Number, 1.0) is the font size (ignore the many other `*Size*` inputs).
- 3D depth: `ExtrusionDepth` (Number, **0** = flat — set ~0.12); `Extrusion`, `ExtrusionStyle`,
  `ExtrusionSubdivisions`, `CustomExtrusionSubdivisions` (40), `BevelTexture` (Image).
- Fill colour: `Red1` / `Green1` / `Blue1` (Number, 1.0), `Alpha1`; bevel/spec variants exist.
- `Transform3DOp.ScaleLock` (Number, 1) — set 0 to keyframe `Scale.X/Y/Z` independently.
- **Justification is inert via scripting**: `HorizontalJustificationCenter/Left/Right`, `…New`
  (3), `Vertical*` — setting them does NOT change the render (verified pixel-identical). Text
  stays left/baseline anchored → center geometrically (a 4-digit string at `Size 1` ≈ 0.89
  world units wide; origin `X = center − width/2`, `Y ≈ −0.12`).

## Shape3D  (~105–146 inputs, varies by shape)
- `Shape` (FuID, "SurfacePlaneInputs") — set `SurfaceCubeInputs` for a cube (other surfaces
  follow `Surface<Name>Inputs`: Sphere/Cylinder/Cone/Torus — confirm names live).
- Plane dims under `SurfacePlaneInputs.*`; cube under `SurfaceCubeInputs.Width/Height/Depth`
  (Number, 1) with `SurfaceCubeInputs.SizeLock` (Number, **1** → 0 for independent dims).
- Per-shape: `…Inputs.Visibility.IsVisible` (1), `…Inputs.BlendMode.SW.BlendMode` (FuID,
  **"Additive"**), subdivisions, matte, lighting flags.
- **Gotcha:** a fresh Shape3D spawns at the origin `(0,0,0)` where Camera3D also sits; with the
  additive default the camera is inside it → whole frame renders white. Move/size it out first.

## LightDirectional (~67) / LightAmbient (~41)
- Directional: `Intensity` (Number, 1.0); aim with `Transform3DOp.Rotate.X/Y/Z` (shines down local −Z).
- Ambient: `Intensity` (Number, 0.2); flat fill, no direction.
- (`LightPoint`, `LightSpot` exist — not probed this session.)

## Background (2D, ~113) / Merge (2D) / MediaOut
- Background: `Type` (FuID, "Solid"); `GradientType` (FuID, "Linear"); solid colour
  `TopLeftRed/Green/Blue/Alpha` (Number; 0,0,0,1).
- Merge: `Background`, `Foreground` image inputs; `Blend` (opacity). Composite Renderer3D
  (Foreground) over Background, then → `MediaOut1.Input`.
- MediaOut1: input id is `Input`.

---

## Shared `Transform3DOp.*` (on every 3D node)
- `Transform3DOp.Translate.X/Y/Z` (Number, 0)
- `Transform3DOp.Rotate.X/Y/Z` (Number, 0); `Transform3DOp.Rotate.RotOrder` (FuID, "XYZ")
- `Transform3DOp.Scale.X/Y/Z` (Number, 1); `Transform3DOp.ScaleLock` (Number, 1 → 0 for non-uniform)
- `Transform3DOp.Pivot.*` — scale/rotate pivot offset (e.g. to grow a rod from one end).

## Environment
- `insert_fusion_composition` → 5 s / 120f generator, comp has only `MediaOut1`; at 1080p/24fps
  the clip starts at timeline frame **86400**, comp frames are 0-relative
  (`timeline_frame = timeline_start_frame + comp_frame − global_start`).
- **Clip length is fixed at 5 s and can't be resized via script** (`TimelineItem` has no resize),
  so a longer request (8 s, 16 s, …) can't be done purely in code — author at 120f, or have the
  user drag-extend the generator clip then re-time the keyframes. (Open TODO: `docs/fusion-3d-notes.md` #9.)
- `grab_frame` returns a JPEG downscaled to `max_width` (default 1280 → 1280×720 for 16:9).

## Adding to this cheatsheet
When you probe a node/input not listed here (or find a default changed), append it in the same
`id (datatype, default) — note` format so the next run doesn't re-probe it.
