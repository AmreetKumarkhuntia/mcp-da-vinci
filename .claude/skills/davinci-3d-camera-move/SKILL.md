---
name: davinci-3d-camera-move
description: Animate a 3D camera move over a set of elements (markers, dates, words, objects, chapters) in DaVinci Resolve via the mcp-da-vinci tools — fly-through, fly-over a surface/table/map, orbit, push-in or top-down route, with optional per-element pops, a traced path line, and motion blur. Use for any "fly over / fly through / 3D reveal / camera move past these things" request.
metadata:
  tags: davinci, resolve, fusion, 3d, camera, motion-graphics, mcp
---

## When to use
Requests for a 3D camera move past/over a sequence of things: "fly-over of these dates",
"fly through these words", a 3D timeline/countdown/montage, a route between points, an orbit
or reveal. Built on the **`davinci-fusion-3d`** skill — read that for node ids, wiring,
lighting, motion blur and the gotchas. This skill is the **staging + camera path + timing**.

## Step 0 — clarify the staging (do not assume)
"Camera fly" is subjective. The *same* labels can be staged completely differently, and the
choice drives the scene layout, camera path, lighting, and whether a "path line" even makes
sense. **Ask before building** (`AskUserQuestion`), offering these with a recommended default:

| Staging | Layout | Camera path |
|---|---|---|
| **Corridor fly-through** | elements float in depth (−Z), weaving | translate forward through them |
| **Fly-over a surface** (table / ground / floor) | elements stand/lie on a `Shape3D` plane | high camera, pitched down, translating across |
| **Top-down route / map** | overhead; points on a plane, a line traces the route | high, looking straight down, drifting along the route |
| **Orbit / arc** | a hero object or tight cluster | camera circles a pivot (or uses Camera3D aim) |
| **Push-in / reveal** | one hero element | dolly toward it, optional slight arc |

Also worth clarifying when unclear: duration, do the labels appear one-at-a-time or all up
front, is there a connecting path/route line, and the look (dark/space vs lit room vs map).
Pick sensible defaults and say what you chose; don't stall on every detail.

## Step 1 — stage the scene (per the choice)
Use `davinci-fusion-3d`. Only build what the staging needs:
- **Surface stagings** add a ground/table: a large `Shape3D` plane (`Shape=SurfacePlaneInputs`)
  or `ImagePlane3D`; place labels *on* it (rest on the surface, often standing upright/billboarded).
- **Corridor / push-in / orbit** usually need no surface — elements float; the depth + camera
  move carry the 3D.
- Spacing, weave and scale are derived from the staging and **tuned via `grab_frame`**, not fixed.

## Step 2 — camera path (per the choice)
Keyframe `Camera3D.Transform3DOp.Translate.*` (and `Rotate.*`). Then **`fusion_sample_input`
the path** to find the frame the camera reaches each element — that anchors all timing.
- *Corridor*: animate `Translate.Z` forward; tiny `Translate.X/Y` weave; `ease_in_out`.
- *Fly-over surface*: lift `Translate.Y`, pitch `Rotate.X` down ~30–60°, translate across the
  surface axis; keep elements in the lower/centre frame.
- *Top-down*: high `Translate.Y`, `Rotate.X ≈ -90`, drift along the route.
- *Orbit*: animate position around a pivot (or set Camera3D's target/aim — discover its ids
  with `fusion_get_node --filter target/aim` rather than assuming).

## Step 3 — element animation (optional, shared primitives)
These work in any staging (see `davinci-fusion-3d` for exact ids):
- **Pop-in**: `Transform3DOp.Scale.X/Y/Z` `[0,1.15,1.0]`, `ease_out`, starting shortly before
  the camera reaches that element; hold the first key at 0 so it's hidden until its moment.
- **Traced path/route line** (only if the staging calls for one): thin `Shape3D` cube rods
  (`SizeLock=0`, `Width/Height` small, `Depth=segment length`) between consecutive points,
  yawed to point along each segment (`Rotate.Y ≈ atan2(ΔX, ΔZ)`; verify sign in a grab).
  Draw them on by keyframing `SurfaceCubeInputs.Depth` `0→length`, `ease_out`, **sequenced**
  so the route builds ahead of the camera.
- **Motion blur** comes free from the camera speed (`davinci-fusion-3d`).

## Step 4 — verify
Grab the key beats — first reveal, a mid pass/over, each transition, the final hero frame —
and tune layout, path, timing and lights from the renders.

## Worked example — ONE staging (corridor fly-through, 4 markers, 120f / 24fps)
*Illustrative numbers, not defaults — re-derive for the staging and length you actually build.*
- Markers at z = −6/−14/−22/−30, X weave ±0.4–0.6 (small — a big weave throws them off-screen
  at close range), centered via the AoV trick; last marker a few units past the camera's end → hero shot.
- Camera `Translate.Z +2 → −26`, `ease_in_out`; sampling shows it reaches the markers ≈ f43/f65/f91.
- Pops start ≈ f6/f34/f58/f82 (`[start, +5, +11]`); rods draw ≈ f17–40/f45–68/f70–93.
- Markers stay full-size after their pop and whoosh past naturally (don't scale them back down).

## Reminders
- Default 5 s clip can't be resized via script — for another length the user drag-extends the
  generator clip, then re-time keyframes proportionally.
- No undo over scripting → throwaway timeline.
