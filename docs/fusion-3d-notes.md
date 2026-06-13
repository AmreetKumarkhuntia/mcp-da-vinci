# Fusion 3D — challenges & tooling TODOs

Notes from building a 3D camera fly-through (4 extruded year-markers, motion blur,
per-marker pops, a drawn "path-trace" line) entirely through the `fusion_*` / edit
MCP tools. Verified live on **Resolve 19.1.3.7 Studio**. The existing CLAUDE.md covers
2D Fusion well; this captures the **3D** friction and what would make it smoother.

Each item: what bit, the root cause, the current workaround, and a concrete TODO.

## Challenges faced

### 1. Text3D can't be centered via scripting
- **Symptom:** years rendered left/baseline-anchored and overlapping; impossible to
  frame a single date centrally.
- **Cause:** the justification inputs (`HorizontalJustificationCenter`, `…New`,
  `Vertical…`) are **inert when set via `SetInput`** — pixel-identical renders before/after.
- **Workaround:** center geometrically. Read `Camera3D.AoV` (was 19.26° horizontal,
  `AovType=0`), compute px-per-world-unit ≈ `(imgWidth/2)/(d·tan(AoV/2))`, measure glyph
  width (a 4-digit year at `Size 1` ≈ 0.89 world units), then set origin
  `X = desiredCenter − width/2`, `Y ≈ −0.12` to vertically center.
- **TODO:** `fusion_set_text_alignment(node, h="center", v="center")` that drives the
  layout the way the UI does (or recomputes via `comp:SetText`); and/or expose
  `fusion_get_text_extents(node)` so callers don't need AoV math at all.
- **Won't fix (probed live 2026-06-13):** justification is inert via `LoadSettings` too. Setting
  `Txt.Inputs.HorizontalJustificationNew.Value` in the `SaveSettings()` table and `LoadSettings`-ing
  it leaves the render **byte-identical** (same md5 for values 0/1/2/3) and `GetInput` still reads
  3.0 — the input is computed/locked, not writable. `LoadSettings` itself works (a `Green1` change
  applied the same way took effect), so the inertness is specific to the justification inputs. The
  geometric-centering workaround above is the answer.

### 2. A fresh Shape3D/cube spawns at the origin — on top of the camera
- **Symptom:** whole frame rendered **solid white** after adding cubes.
- **Cause:** new `Shape3D` (and `Camera3D`) both sit at `(0,0,0)`; with the default
  **additive** blend the camera is *inside* the cube → full-white wash. Cost a confusing
  debug pass (hiding nodes one by one).
- **Workaround:** immediately move/scale new 3D primitives away from the origin.
- **TODO:** `fusion_add_node` could nudge new 3D primitives off-origin (or warn), or a
  `fusion_add_shape3d(shape="cube", x,y,z, w,h,d)` helper with sane non-overlapping defaults.
- **Done:** `fusion_add_node` returns a `note` warning the origin/white-frame trap for
  `Shape3D`; reposition cheaply with `fusion_set_xyz` / `fusion_set_scale3d`.

### 3. Light node registry ids are non-obvious
- **Symptom:** `fusion_add_node DirectionalLight` / `AmbientLight` both failed.
- **Cause:** Fusion ids are `LightDirectional`, `LightAmbient` (also `LightPoint`,
  `LightSpot`), not the UI names.
- **Workaround:** use the `Light*` ids.
- **TODO:** extend the existing modifier-alias pattern in `fusion_add_modifier` to
  `fusion_add_node` — map friendly `DirectionalLight/AmbientLight/PointLight/SpotLight`
  → registry ids. Or a dedicated `fusion_add_light(type, intensity, ...)`.
- **Done:** `fusion_add_node` aliases `DirectionalLight/AmbientLight/PointLight/SpotLight`
  → `Light*` ids (`_NODE_TYPE_ALIASES`).

### 4. Renderer3D lighting is OFF by default → flat, non-3D look
- **Symptom:** extruded `Text3D` looked flat (no depth shading) even with `ExtrusionDepth`.
- **Cause:** `RendererSoftware.LightingEnabled = 0` by default; geometry renders flat-lit.
- **Workaround:** set it to 1 and add a `LightDirectional` (+ `LightAmbient`).
- **TODO:** document in the renderer setup; optional `fusion_enable_lighting(node)` helper.
- **Done:** `fusion_enable_lighting(node, lighting=True, shadows=None)` flips
  `LightingEnabled` (and `ShadowsEnabled`) on whichever renderer slot is present.

### 5. Motion blur: low default samples + split parameters
- **Symptom:** had to know four separate ids and that the default `Quality=2` is too low
  (choppy blur).
- **Cause:** params spread across `MotionBlur`, `Quality`, `ShutterAngle`, `SampleSpread`.
- **TODO:** `fusion_enable_motion_blur(node, quality=16, shutter=180, spread=1)` one-shot.
- **Done:** `fusion_enable_motion_blur(node, quality=16, shutter_angle=180, sample_spread=1)`.

### 6. Merge3D scene inputs must be connected strictly sequentially
- **Symptom:** can only connect to `SceneInput{N}` once `SceneInput{N-1}` is filled (each
  connection grows the next empty slot); parallel/skip-ahead connects fail.
- **Workaround:** connect objects one at a time in order.
- **TODO:** `fusion_connect_scene(source, merge3d)` that auto-appends to the next free
  `SceneInput`, so callers don't track slot numbers (and can't race).
- **Done:** `fusion_connect_scene(source, merge3d)` picks the lowest free `SceneInput{N}`
  and verifies the connect took.

### 7. Vector / color edits are one-float-at-a-time
- **Symptom:** positioning each object took 3 `fusion_set_value` calls
  (`Transform3DOp.Translate.X/Y/Z`); same for scale, rotate, and RGB color.
- **TODO:** convenience setters — `fusion_set_xyz(node, "Transform3DOp.Translate", x,y,z)`,
  `fusion_set_scale3d(node, s)` (uniform), `fusion_set_color(node, r,g,b[,a])`.
- **Done:** `fusion_set_xyz(node, input_prefix, x,y,z)`, `fusion_set_scale3d(node, scale)`,
  `fusion_set_color(node, r,g,b[,a], red_id="Red1")` (green/blue/alpha ids derived from `red_id`).

### 8. Text3D ScaleLock blocks scripted uniform scaling
- **Symptom:** uniform pop scaling didn't reliably propagate from `Scale.X`.
- **Cause:** `Transform3DOp.ScaleLock=1`; the lock mirrors in the UI but not dependably
  under `SetInput`.
- **Workaround:** set `ScaleLock=0` and keyframe `Scale.X/Y/Z` together.
- **TODO:** folded into the `fusion_set_scale3d` helper above.
- **Done (static):** `fusion_set_scale3d` clears `ScaleLock` and sets Scale X/Y/Z. An
  animated pop still needs `fusion_set_keyframes` on each `Transform3DOp.Scale` axis after
  the unlock — the helper's docstring spells this out.

### 9. Fixed 5 s generator length — can't honor an 8 s request via script
- **Symptom:** user asked for 8 s; `insert_fusion_composition` makes a fixed 5 s (120f)
  generator and `TimelineItem` has no resize, so the shot was authored at 5 s.
- **TODO (investigate):** `insert_fusion_composition(duration_seconds=…)` by (a) setting the
  project "standard generator duration" before insert, or (b) `AppendToTimeline` with an
  explicit `endFrame`, or (c) a `set_clip_duration` trim. Confirm which the API allows.
- **Won't fix (probed live 2026-06-13):** confirmed infeasible via scripting, all three routes dead.
  (a) `project.GetSetting('')` returns 157 keys with **no** standard-generator-duration — that
  Project Settings ▸ Editing field isn't script-exposed, so set→insert→restore is impossible.
  (b) the `Insert*…IntoTimeline` methods (`InsertFusionCompositionIntoTimeline`, `…Generator…`,
  `…Title…`, `InsertGeneratorIntoTimeline`, OFX) all take **no** duration arg; generators aren't
  `MediaPoolItem`s, so the `AppendToTimeline(clipInfo endFrame)` route doesn't apply. (c) the
  inserted `TimelineItem` has only `Get*` for duration — its `Set*` methods are color/CDL/LUT/
  cache/`SetProperty` (transform), **no resize**. So the 5 s clip stands: the user drag-extends
  the generator, then re-time keys proportionally.

### 10. Visual feedback is one rendered frame at a time
- **Symptom:** iterating framing/lighting/timing meant many single `grab_frame` renders;
  judging *motion* (blur, pop timing) from stills is indirect.
- **TODO:** `grab_frames(frames=[…])` returning a contact sheet (or a short low-res
  preview clip) for one round-trip review of a whole sequence.
- **Done:** `grab_frames(frames=[…], columns=None, tile_width=None, max_width=1280)` returns
  one labeled contact-sheet JPEG (≤16 frames/call; the page-dance happens once).

### 11. Can't enumerate a combo / FuID input's options
- **Symptom:** `Renderer3D.RendererType` (Software / OpenGL / …), `Shape3D.Shape`, blend-mode
  and other FuID "combo" inputs only expose their *current* value via `fusion_get_node`, so the
  valid options must be known or guessed (e.g. `SurfaceCubeInputs`, `RendererOpenGL`). This is
  exactly what bit picking a 3D renderer or a cube shape.
- **TODO:** surface a combo input's option list (its MultiButton/ComboControl items) — e.g.
  `fusion_get_node` returning an `options` array for FuID inputs, or a `fusion_get_input_options`
  helper. Unblocks reliable renderer/shape/blend selection without trial-and-error. A friendly
  `fusion_set_renderer(node, "software"|"opengl")` could sit on top.
- **Done (verified live):** `fusion_get_node` attaches an `options` array to FuID inputs, read
  from the input's `INPIDT_*_ID` attr tables. Confirmed on `Renderer3D.RendererType` →
  `[RendererOpenGL, RendererOpenGLUV, RendererSoftware]` and `Shape3D.Shape` → the seven
  `Surface*Inputs` shapes. Inputs with no option table simply omit the field (no regression).

## Already-known (in CLAUDE.md), reconfirmed in 3D
- No undo over scripting → always prototype on a throwaway `create_timeline` + comp.
- `fusion_set_keyframes` replaces all keys and applies one easing across the curve; a
  pop overshoot (0 → 1.15 → 1.0) works as 3 keys with `ease_out`.
- Comp frames are 0-relative; map to timeline frames with
  `timeline_frame = timeline_start_frame + (comp_frame − global_start)`.

## Status (2026-06-13)
- **Shipped & verified live** (Resolve 19.1.3.7 Studio — smoke-tested end-to-end, full 3D scene
  built + rendered through these tools): #2 origin note, #3 light aliases, #4 `fusion_enable_lighting`,
  #5 `fusion_enable_motion_blur`, #6 `fusion_connect_scene` (slots 1–4 filled sequentially),
  #7 `fusion_set_xyz`/`fusion_set_scale3d`/`fusion_set_color`, #8 (static, via `fusion_set_scale3d`),
  #10 `grab_frames` (labeled contact sheet), #11 FuID `options` in `fusion_get_node` (returned the
  real `RendererType` / `Shape` option lists).
- **Won't fix (probed live, confirmed infeasible):** #1 text alignment (justification inert via
  `SetInput` *and* `SaveSettings`/`LoadSettings` — use geometric centering) and #9 generator
  duration (no script-exposed duration setting, no `Insert*` duration arg, no `TimelineItem`
  resize — use manual drag-extend). Evidence in each item's Status line.
