"""Fusion node-graph tools: build the graph, pull node config, set params, animate.

Operates on a timeline clip's Fusion composition (the playhead clip by default,
or one targeted by ``clip_name`` / ``comp_index`` / ``comp_name``). Nodes are
addressed by their Fusion name (e.g. ``Blur1``); ``fusion_get_node`` reveals the
valid input IDs + datatypes for a node so params can be set correctly.
"""

from __future__ import annotations

import re

from resolve.app import mcp
from resolve.connection import (
    comp_lock,
    find_fusion_tool,
    get_bmd,
    get_comp,
    get_current_video_item,
    to_jsonable,
)

# Datatypes that carry a readable scalar value (others are image/mask connections).
_SCALAR_TYPES = {"Number", "Text", "FuID", "Point", "Color"}

# Friendly node names -> Fusion registry ids (lights use Light* ids, not UI names).
_NODE_TYPE_ALIASES = {
    "DirectionalLight": "LightDirectional",
    "AmbientLight": "LightAmbient",
    "PointLight": "LightPoint",
    "SpotLight": "LightSpot",
}
# 3D primitives that spawn at the origin (0,0,0) where Camera3D sits — warn callers.
_ORIGIN_WARN_TYPES = {"Shape3D"}


def _tool_name(tool) -> str:
    return tool.GetAttrs().get("TOOLS_Name")


def _tool_type(tool) -> str:
    return tool.GetAttrs().get("TOOLS_RegID")


def _iter_tools(comp):
    return list((comp.GetToolList() or {}).values())


def _input_obj(tool, input_id: str):
    """Return the Input object on ``tool`` whose INPS_ID matches, or raise."""
    for inp in (tool.GetInputList() or {}).values():
        if inp.GetAttrs().get("INPS_ID") == input_id:
            return inp
    valid = [i.GetAttrs().get("INPS_ID") for i in (tool.GetInputList() or {}).values()]
    raise RuntimeError(
        f"Node {_tool_name(tool)!r} has no input {input_id!r}. "
        f"Valid IDs (see fusion_get_node): {valid[:40]}{' …' if len(valid) > 40 else ''}"
    )


def _inputs_by_suffix(tool, suffix: str) -> list:
    """Return (input_id, Input) pairs whose INPS_ID is ``suffix`` or ends '.'+suffix.

    Lets the 3D conveniences address ids that may be top-level (``MotionBlur``) or
    nested under a renderer prefix (``RendererSoftware.LightingEnabled``) without the
    caller knowing which renderer is active. Exact-id matches sort first.
    """
    exact, nested = [], []
    for inp in (tool.GetInputList() or {}).values():
        iid = inp.GetAttrs().get("INPS_ID")
        if iid == suffix:
            exact.append((iid, inp))
        elif iid and iid.endswith("." + suffix):
            nested.append((iid, inp))
    return exact + nested


def _fuid_options(inp) -> list:
    """Option values of a combo/MultiButton FuID input, from its attr tables.

    Fusion exposes a combo control's choices as attribute tables keyed
    ``INPIDT_<Control>_ID`` (the option FuIDs) alongside ``INPST_<Control>_String``
    (human labels). Returns ``[{"id", "label"}]`` when labels are present, else a
    flat list of ids; empty when the input carries no option table (so callers see
    no ``options`` key rather than a wrong one).
    """
    attrs = inp.GetAttrs() or {}
    ids = next(
        (v for k, v in attrs.items()
         if isinstance(v, dict) and re.fullmatch(r"INPIDT_.+_ID", str(k))),
        None,
    )
    if not ids:
        return []
    labels = next(
        (v for k, v in attrs.items()
         if isinstance(v, dict) and re.fullmatch(r"INPST_.+_String", str(k))),
        {},
    )
    opts = []
    for k in sorted(ids, key=lambda x: (isinstance(x, str), x)):
        oid = to_jsonable(ids[k])
        lbl = labels.get(k) if isinstance(labels, dict) else None
        opts.append({"id": oid, "label": to_jsonable(lbl)} if lbl is not None else oid)
    return opts


def _main_input_id(tool) -> str:
    main = tool.FindMainInput(1)
    if main is None:
        raise RuntimeError(f"Node {_tool_name(tool)!r} has no primary (image) input.")
    return main.GetAttrs().get("INPS_ID")


def _spline_of(inp):
    """Return the BezierSpline tool animating ``inp``, or None."""
    out = inp.GetConnectedOutput()
    if out is None:
        return None
    tool = out.GetTool()
    return tool if tool.GetAttrs().get("TOOLS_RegID") == "BezierSpline" else None


def _ensure_animated(comp, tool, inp, input_id: str, frame: float) -> None:
    """Animate ``input_id`` with a BezierSpline whose seeded key lands on ``frame``.

    AddModifier seeds a keyframe at comp.CurrentTime holding the old static
    value; parking CurrentTime on the target frame first lets the caller's
    write at ``frame`` overwrite the seed instead of leaving a stray key.
    Call inside comp_lock.
    """
    if inp.GetConnectedOutput() is not None:
        return
    saved = comp.GetAttrs()["COMPN_CurrentTime"]
    comp.CurrentTime = float(frame)
    try:
        tool.AddModifier(input_id, "BezierSpline")
    finally:
        comp.CurrentTime = saved


# --- Comps / targeting ---------------------------------------------------------
@mcp.tool()
def fusion_list_comps(clip_name: str | None = None) -> dict:
    """List the Fusion compositions on a timeline clip (playhead clip by default)."""
    item = get_current_video_item(clip_name)
    return {
        "clip": item.GetName(),
        "count": item.GetFusionCompCount(),
        "names": item.GetFusionCompNameList(),
    }


@mcp.tool()
def fusion_add_comp(clip_name: str | None = None) -> dict:
    """Add a new (empty) Fusion composition to a timeline clip and return its name."""
    item = get_current_video_item(clip_name)
    comp = item.AddFusionComp()
    if comp is None:
        raise RuntimeError("Failed to add a Fusion composition.")
    return {"clip": item.GetName(), "comps": item.GetFusionCompNameList()}


@mcp.tool()
def fusion_set_active_comp(comp_name: str, clip_name: str | None = None) -> dict:
    """Load the named Fusion composition as the active one on a clip."""
    item = get_current_video_item(clip_name)
    if item.LoadFusionCompByName(comp_name) is None:
        raise RuntimeError(
            f"No comp {comp_name!r} on {item.GetName()!r}. "
            f"Available: {item.GetFusionCompNameList()}"
        )
    return {"clip": item.GetName(), "active": comp_name}


@mcp.tool()
def fusion_get_comp_info(
    clip_name: str | None = None, comp_index: int = 1, comp_name: str | None = None
) -> dict:
    """Read a comp's time ranges + the clip's timeline placement.

    Keyframe frames are in COMP time: the valid range is render_start..render_end
    (usually 0..clip duration-1). Map to absolute timeline frames with
    ``timeline_frame = timeline_start_frame + (comp_frame - global_start)``.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    attrs = comp.GetAttrs()
    info = {
        "current_time": attrs.get("COMPN_CurrentTime"),
        "render_start": attrs.get("COMPN_RenderStart"),
        "render_end": attrs.get("COMPN_RenderEnd"),
        "global_start": attrs.get("COMPN_GlobalStart"),
        "global_end": attrs.get("COMPN_GlobalEnd"),
        "clip": None,
    }
    try:
        item = get_current_video_item(clip_name)
        info["clip"] = item.GetName()
        info["timeline_start_frame"] = item.GetStart()
        info["timeline_end_frame"] = item.GetEnd()
    except RuntimeError:
        pass  # Fusion-page fallback comp with no current video item
    return info


@mcp.tool()
def fusion_set_comp_time(
    frame: float,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Move the comp's current time (scrubs the Fusion-page preview)."""
    comp = get_comp(clip_name, comp_index, comp_name)
    comp.CurrentTime = float(frame)  # not locked: Lock() would suppress the preview
    return {"current_time": comp.GetAttrs()["COMPN_CurrentTime"]}


# --- Graph build / edit --------------------------------------------------------
@mcp.tool()
def fusion_list_nodes(
    clip_name: str | None = None, comp_index: int = 1, comp_name: str | None = None
) -> list[dict]:
    """List the nodes (tools) in a Fusion comp as {name, type}."""
    comp = get_comp(clip_name, comp_index, comp_name)
    return [{"name": _tool_name(t), "type": _tool_type(t)} for t in _iter_tools(comp)]


@mcp.tool()
def fusion_add_node(
    node_type: str,
    name: str | None = None,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Add a node by its Fusion registry id (e.g. Blur, Merge, Transform, TextPlus).

    Friendly light names are aliased to their registry ids (DirectionalLight ->
    LightDirectional, AmbientLight -> LightAmbient, PointLight -> LightPoint,
    SpotLight -> LightSpot). Optionally rename it. Returns the node's final name
    and type, plus a ``note`` for 3D primitives that spawn at the origin.
    """
    node_type = _NODE_TYPE_ALIASES.get(node_type, node_type)
    comp = get_comp(clip_name, comp_index, comp_name, create=True)
    with comp_lock(comp):
        tool = comp.AddTool(node_type)
        if tool is None:
            raise RuntimeError(
                f"Failed to add node of type {node_type!r} "
                "(check the Fusion registry id, e.g. Blur, Merge, Transform)."
            )
        if name:
            tool.SetAttrs({"TOOLS_Name": name})
    result = {"name": _tool_name(tool), "type": _tool_type(tool)}
    if node_type in _ORIGIN_WARN_TYPES:
        result["note"] = (
            "Spawns at the origin (0,0,0) where Camera3D also sits; with the "
            "default additive blend the camera renders inside it (whole frame "
            "white). Move/scale it out with fusion_set_xyz / fusion_set_scale3d."
        )
    return result


@mcp.tool()
def fusion_insert_node(
    node_type: str,
    name: str | None = None,
    after: str = "MediaIn1",
    before: str = "MediaOut1",
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Add a node and wire it inline: ``after`` -> new node -> ``before``.

    Defaults splice into the standard MediaIn1 -> MediaOut1 chain.
    """
    node_type = _NODE_TYPE_ALIASES.get(node_type, node_type)
    comp = get_comp(clip_name, comp_index, comp_name, create=True)
    with comp_lock(comp):
        src = find_fusion_tool(comp, after)
        dst = find_fusion_tool(comp, before)
        tool = comp.AddTool(node_type)
        if tool is None:
            raise RuntimeError(f"Failed to add node of type {node_type!r}.")
        if name:
            tool.SetAttrs({"TOOLS_Name": name})
        # new.mainInput <- after ; before.mainInput <- new
        tool.ConnectInput(_main_input_id(tool), src)
        dst.ConnectInput(_main_input_id(dst), tool)
    return {
        "name": _tool_name(tool),
        "type": _tool_type(tool),
        "wired": f"{after} -> {_tool_name(tool)} -> {before}",
    }


@mcp.tool()
def fusion_connect(
    source: str,
    dest: str,
    dest_input: str = "Input",
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Connect ``source`` node's output into ``dest`` node's ``dest_input``.

    Common inputs: "Input" (most), "Background"/"Foreground" (Merge), "EffectMask".
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    src = find_fusion_tool(comp, source)
    dst = find_fusion_tool(comp, dest)
    with comp_lock(comp):
        dst.ConnectInput(dest_input, src)
    return {"connected": f"{source} -> {dest}.{dest_input}"}


@mcp.tool()
def fusion_connect_scene(
    source: str,
    merge3d: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Connect a 3D node into the next free SceneInput slot of a Merge3D.

    Merge3D grows one new SceneInput slot per connection, so slots must be filled
    in order. This finds the lowest-numbered free ``SceneInput{N}`` and connects
    ``source`` there — callers don't track slot numbers (and can't race a
    skip-ahead connect, which Fusion rejects). Connect the camera, lights, and
    every object this way.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    src = find_fusion_tool(comp, source)
    dst = find_fusion_tool(comp, merge3d)
    slots = []
    for inp in (dst.GetInputList() or {}).values():
        m = re.fullmatch(r"SceneInput(\d+)", inp.GetAttrs().get("INPS_ID") or "")
        if m:
            slots.append((int(m.group(1)), inp.GetAttrs().get("INPS_ID"), inp))
    slots.sort()
    free = next((s for s in slots if s[2].GetConnectedOutput() is None), None)
    if free is None:
        raise RuntimeError(
            f"No free SceneInput on {merge3d!r} — is it a Merge3D? "
            f"Found slots: {[s[1] for s in slots] or 'none'}."
        )
    n, input_id, inp = free
    with comp_lock(comp):
        dst.ConnectInput(input_id, src)
    if inp.GetConnectedOutput() is None:
        raise RuntimeError(
            f"ConnectInput({input_id!r}) did not take — confirm {source!r} has a "
            "3D output and is not already wired elsewhere."
        )
    return {"connected": f"{source} -> {merge3d}.{input_id}", "slot": n}


@mcp.tool()
def fusion_delete_node(
    name: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Delete a node from the comp."""
    comp = get_comp(clip_name, comp_index, comp_name)
    with comp_lock(comp):
        find_fusion_tool(comp, name).Delete()
    return {"deleted": name}


@mcp.tool()
def fusion_rename_node(
    old: str,
    new: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Rename a node."""
    comp = get_comp(clip_name, comp_index, comp_name)
    with comp_lock(comp):
        find_fusion_tool(comp, old).SetAttrs({"TOOLS_Name": new})
    return {"renamed": f"{old} -> {new}"}


# --- Pull config / inspect -----------------------------------------------------
@mcp.tool()
def fusion_get_node(
    name: str,
    filter: str | None = None,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Read a node's inputs: id, datatype, current value, animated?, expression.

    The readable summary to decide edits. Image/mask inputs are reported as
    connections (set those with fusion_connect, not the scalar setters).
    Pass ``filter`` (case-insensitive substring of the input id or label) to
    tame huge nodes — TextPlus has ~700 inputs.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, name)

    needle = filter.lower() if filter else None
    total = 0
    inputs = []
    for inp in (tool.GetInputList() or {}).values():
        attrs = inp.GetAttrs()
        input_id = attrs.get("INPS_ID")
        datatype = attrs.get("INPS_DataType")
        total += 1
        if needle and (
            needle not in str(input_id or "").lower()
            and needle not in str(attrs.get("INPS_Name") or "").lower()
        ):
            continue
        entry = {"id": input_id, "datatype": datatype}
        if datatype in _SCALAR_TYPES:
            try:
                entry["value"] = to_jsonable(tool.GetInput(input_id))
            except Exception:
                entry["value"] = None
            if datatype == "FuID":
                opts = _fuid_options(inp)
                if opts:
                    entry["options"] = opts
        else:
            entry["connection"] = True
        try:
            entry["animated"] = inp.GetConnectedOutput() is not None
            expr = inp.GetExpression()
            if expr:
                entry["expression"] = expr
        except Exception:
            pass
        inputs.append(entry)

    result = {"name": _tool_name(tool), "type": _tool_type(tool), "inputs": inputs}
    if needle:
        result["total_inputs"] = total
        result["matched"] = len(inputs)
    return result


@mcp.tool()
def fusion_get_node_settings(
    name: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Pull a node's COMPLETE config (all inputs, modifiers, keyframes) as a dict.

    This is the full ``GetCurrentSettings()`` dump — verbose by design; use it to
    capture a node's exact state before modifying it.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, name)
    return to_jsonable(tool.GetCurrentSettings())


@mcp.tool()
def fusion_get_keyframes(
    name: str,
    input_id: str | None = None,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Read keyframes for one input (if ``input_id`` given) or the whole node.

    For a BezierSpline-animated input the result is the rich per-key table
    ``{frame: {"1": value, "LH"/"RH": relative handle offsets}}``; otherwise
    (e.g. XYPath/modifier-driven) it is the list of key times.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, name)
    if input_id:
        inp = _input_obj(tool, input_id)
        spline = _spline_of(inp)
        keyframes = spline.GetKeyFrames() if spline else inp.GetKeyFrames()
        return {"node": name, "input": input_id, "keyframes": to_jsonable(keyframes)}
    return {"node": name, "keyframes": to_jsonable(tool.GetKeyFrames())}


@mcp.tool()
def fusion_sample_input(
    node: str,
    input_id: str,
    frames: list[float],
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Evaluate an input at the given frames — verify an animation numerically.

    Cheaper than rendering: e.g. after a linear 0->90 over 24 frames, sampling
    frame 12 must return 45.0.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    _input_obj(tool, input_id)  # validate id -> clear error listing valid ids
    samples = [
        {"frame": f, "value": to_jsonable(tool.GetInput(input_id, f))} for f in frames
    ]
    return {"node": node, "input": input_id, "samples": samples}


# --- Set params (static) -------------------------------------------------------
@mcp.tool()
def fusion_set_value(
    node: str,
    input_id: str,
    value: float,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Set a numeric input (e.g. Blur 'XBlurSize', Transform 'Size')."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    _input_obj(tool, input_id)  # validate id -> clear error listing valid ids
    tool.SetInput(input_id, value)
    return {"node": node, "input": input_id, "value": to_jsonable(tool.GetInput(input_id))}


@mcp.tool()
def fusion_set_text(
    node: str,
    input_id: str,
    text: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Set a Text or FuID input (e.g. TextPlus 'StyledText', a file path, an enum id)."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    _input_obj(tool, input_id)  # validate id -> clear error listing valid ids
    tool.SetInput(input_id, text)
    return {"node": node, "input": input_id, "value": to_jsonable(tool.GetInput(input_id))}


@mcp.tool()
def fusion_set_point(
    node: str,
    input_id: str,
    x: float,
    y: float,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Set a 2D point/position input (e.g. Transform 'Center'); Fusion space is 0..1."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    _input_obj(tool, input_id)  # validate id -> clear error listing valid ids
    tool.SetInput(input_id, {1: x, 2: y})
    return {"node": node, "input": input_id, "value": [x, y]}


@mcp.tool()
def fusion_set_xyz(
    node: str,
    input_prefix: str,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Set the X/Y/Z parts of a 3D input group in one call (e.g. Transform3DOp.Translate).

    Pass only the axes to change; ``input_prefix`` is the group id without the axis
    suffix (``Transform3DOp.Translate``, ``Transform3DOp.Rotate``). Saves the
    three-call dance of setting ``.X``/``.Y``/``.Z`` separately.
    """
    if x is None and y is None and z is None:
        raise ValueError("Pass at least one of x / y / z.")
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    axes = {"X": x, "Y": y, "Z": z}
    with comp_lock(comp):
        for axis, val in axes.items():
            if val is None:
                continue
            input_id = f"{input_prefix}.{axis}"
            _input_obj(tool, input_id)  # validate -> clear error listing valid ids
            tool.SetInput(input_id, val)
    values = {
        f"{input_prefix}.{axis}": to_jsonable(tool.GetInput(f"{input_prefix}.{axis}"))
        for axis, val in axes.items()
        if val is not None
    }
    return {"node": node, "values": values}


@mcp.tool()
def fusion_set_scale3d(
    node: str,
    scale: float,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Uniformly scale a 3D node: clears Transform3DOp.ScaleLock, sets Scale X/Y/Z together.

    Works around ScaleLock not propagating reliably under scripting. For an animated
    pop (e.g. 0 -> 1.15 -> 1.0), call this once to clear the lock, then
    fusion_set_keyframes each of Transform3DOp.Scale.X/Y/Z with ``ease_out``.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    _input_obj(tool, "Transform3DOp.ScaleLock")  # validate -> "not a 3D node" if absent
    with comp_lock(comp):
        tool.SetInput("Transform3DOp.ScaleLock", 0)
        for axis in ("X", "Y", "Z"):
            tool.SetInput(f"Transform3DOp.Scale.{axis}", scale)
    return {"node": node, "scale": scale}


@mcp.tool()
def fusion_set_color(
    node: str,
    r: float,
    g: float,
    b: float,
    a: float | None = None,
    red_id: str = "Red1",
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Set a node's RGB(A) color in one call; green/blue/alpha ids derived from ``red_id``.

    ``red_id`` is the red-channel input (default ``Red1`` for Text3D/TextPlus fill;
    also ``TopLeftRed`` on Background, or a nested material id). Sibling ids replace
    the last ``Red`` in it with Green/Blue/Alpha. Alpha is set only when ``a`` is
    given and the node has the matching alpha input.
    """
    if "Red" not in red_id:
        raise ValueError(f"red_id {red_id!r} must contain 'Red' (e.g. Red1, TopLeftRed).")
    i = red_id.rfind("Red")
    green_id = red_id[:i] + "Green" + red_id[i + 3:]
    blue_id = red_id[:i] + "Blue" + red_id[i + 3:]
    alpha_id = red_id[:i] + "Alpha" + red_id[i + 3:]
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    ids = {inp.GetAttrs().get("INPS_ID") for inp in (tool.GetInputList() or {}).values()}
    for cid in (red_id, green_id, blue_id):
        if cid not in ids:
            _input_obj(tool, cid)  # raise the standard "no input" error
    set_alpha = a is not None
    if set_alpha and alpha_id not in ids:
        raise RuntimeError(
            f"Node {node!r} has no alpha input {alpha_id!r}; omit ``a`` or check red_id."
        )
    with comp_lock(comp):
        tool.SetInput(red_id, r)
        tool.SetInput(green_id, g)
        tool.SetInput(blue_id, b)
        if set_alpha:
            tool.SetInput(alpha_id, a)
    values = {red_id: r, green_id: g, blue_id: b}
    if set_alpha:
        values[alpha_id] = a
    return {"node": node, "values": values}


# --- 3D conveniences -----------------------------------------------------------
@mcp.tool()
def fusion_enable_motion_blur(
    node: str,
    quality: int = 16,
    shutter_angle: float = 180.0,
    sample_spread: float = 1.0,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Enable + configure motion blur on a Renderer3D in one call.

    Sets MotionBlur=1 plus Quality (samples; the default 2 is choppy), ShutterAngle,
    and SampleSpread — no need to know the four split ids. Motion blur only shows on
    moving geometry.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    wanted = {
        "MotionBlur": 1,
        "Quality": quality,
        "ShutterAngle": shutter_angle,
        "SampleSpread": sample_spread,
    }
    resolved = {}
    for suffix, val in wanted.items():
        matches = _inputs_by_suffix(tool, suffix)
        if not matches:
            raise RuntimeError(
                f"Node {node!r} has no {suffix!r} input — is it a Renderer3D? "
                "(check fusion_get_node --filter)."
            )
        resolved[matches[0][0]] = val  # exact match sorts first
    with comp_lock(comp):
        for input_id, val in resolved.items():
            tool.SetInput(input_id, val)
    return {"node": node, "set": resolved}


@mcp.tool()
def fusion_enable_lighting(
    node: str,
    lighting: bool = True,
    shadows: bool | None = None,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Enable lighting (and optionally shadows) on a Renderer3D — off by default -> flat look.

    Renderer3D ships with LightingEnabled=0, so extruded Text3D renders flat. Turn
    it on, then put an actual light in the scene (fusion_add_node DirectionalLight +
    fusion_connect_scene). Sets every matching renderer slot so it survives a
    renderer-type switch.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    flags = {"LightingEnabled": lighting}
    if shadows is not None:
        flags["ShadowsEnabled"] = shadows
    resolved = {}
    for suffix, val in flags.items():
        matches = _inputs_by_suffix(tool, suffix)
        if not matches:
            raise RuntimeError(
                f"Node {node!r} has no {suffix!r} input — is it a Renderer3D? "
                "(check fusion_get_node --filter)."
            )
        for input_id, _ in matches:
            resolved[input_id] = bool(val)
    with comp_lock(comp):
        for input_id, val in resolved.items():
            tool.SetInput(input_id, 1 if val else 0)
    return {"node": node, "set": resolved}


@mcp.tool()
def fusion_set_expression(
    node: str,
    input_id: str,
    expression: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Set a Fusion expression on an input (e.g. 'time*2'). Empty string clears it."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    _input_obj(tool, input_id).SetExpression(expression or None)
    return {"node": node, "input": input_id, "expression": expression}


# --- Animation / keyframes -----------------------------------------------------
@mcp.tool()
def fusion_set_keyframe(
    node: str,
    input_id: str,
    value: float,
    frame: int,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Key a numeric input to ``value`` at ``frame`` (comp time, linear keys).

    Auto-animates the input (adds a BezierSpline) on the first keyframe.
    For several keys at once — or eased ones — use fusion_set_keyframes.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    with comp_lock(comp):
        _ensure_animated(comp, tool, inp, input_id, frame)
        tool.SetInput(input_id, value, frame)
    return {"node": node, "input": input_id, "frame": frame, "value": value}


_INTERPOLATIONS = ("linear", "ease_in", "ease_out", "ease_in_out", "smooth", "hold")


@mcp.tool()
def fusion_set_keyframes(
    node: str,
    input_id: str,
    frames: list[float],
    values: list[float],
    interpolation: str = "linear",
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Define a numeric input's complete animation: keys at ``frames``/``values``.

    Replaces any existing keys on the input. ``interpolation``: "linear",
    "ease_in" (slow start), "ease_out" (slow end), "ease_in_out"/"smooth"
    (slow both — flat tangents at every key), or "hold" (value jumps at each
    key; emulated with a duplicate key one frame before the next).
    """
    if len(frames) != len(values) or not frames:
        raise ValueError("frames and values must be equal-length, non-empty lists.")
    if interpolation not in _INTERPOLATIONS:
        raise ValueError(
            f"Unknown interpolation {interpolation!r}. One of {list(_INTERPOLATIONS)}."
        )
    pairs = sorted(zip(map(float, frames), map(float, values)))

    # Per-key spline table; handles are RELATIVE (frame offset, value offset)
    # at 1/3 of the segment: colinear -> linear motion, flat (dv=0) -> ease.
    table: dict = {}
    last = len(pairs) - 1
    for i, (f, v) in enumerate(pairs):
        entry: dict = {1: v}
        if interpolation == "hold":
            if i < last and pairs[i + 1][0] - f > 1:
                table[pairs[i + 1][0] - 1] = {1: v}
        else:
            if i > 0:
                dt = (f - pairs[i - 1][0]) / 3.0
                dv = (v - pairs[i - 1][1]) / 3.0
                flat = interpolation in ("ease_in_out", "smooth") or (
                    interpolation == "ease_out" and i == last
                )
                entry["LH"] = {1: -dt, 2: 0.0 if flat else -dv}
            if i < last:
                dt = (pairs[i + 1][0] - f) / 3.0
                dv = (pairs[i + 1][1] - v) / 3.0
                flat = interpolation in ("ease_in_out", "smooth") or (
                    interpolation == "ease_in" and i == 0
                )
                entry["RH"] = {1: dt, 2: 0.0 if flat else dv}
        table[f] = entry

    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    with comp_lock(comp):
        _ensure_animated(comp, tool, inp, input_id, pairs[0][0])
        spline = _spline_of(inp)
        if spline is None:
            mod = inp.GetConnectedOutput().GetTool()
            raise RuntimeError(
                f"Input {input_id!r} is driven by {_tool_type(mod)!r} "
                f"({_tool_name(mod)!r}), not a keyframe spline. Key that modifier's "
                "inputs instead, or fusion_delete_animation first."
            )
        spline.SetKeyFrames(table, True)  # replace: this call defines the curve
    return {
        "node": node,
        "input": input_id,
        "count": len(pairs),
        "frames": [f for f, _ in pairs],
        "interpolation": interpolation,
    }


@mcp.tool()
def fusion_set_point_keyframe(
    node: str,
    input_id: str,
    x: float,
    y: float,
    frame: float,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Key a 2D point input (e.g. Transform 'Center') at ``frame`` — motion paths.

    Attaches an XYPath modifier on first use, then keys its X/Y at each call.
    Fusion point space is 0..1 (0.5, 0.5 = frame center). The returned modifier
    name is addressable like a node (e.g. fusion_get_keyframes on its X input).
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    datatype = inp.GetAttrs().get("INPS_DataType")
    if datatype != "Point":
        raise RuntimeError(
            f"Input {input_id!r} is {datatype!r}, not Point. "
            "Use fusion_set_keyframe(s) for Number inputs."
        )
    with comp_lock(comp):
        out = inp.GetConnectedOutput()
        if out is None:
            # Park time on the target frame so XYPath's seeded keys land there.
            saved = comp.GetAttrs()["COMPN_CurrentTime"]
            comp.CurrentTime = float(frame)
            try:
                if not tool.AddModifier(input_id, "XYPath"):
                    raise RuntimeError(f"Failed to attach XYPath to {input_id!r}.")
            finally:
                comp.CurrentTime = saved
            out = inp.GetConnectedOutput()
        mod = out.GetTool()
        if _tool_type(mod) != "XYPath":
            raise RuntimeError(
                f"Input {input_id!r} is already driven by {_tool_type(mod)!r} "
                f"({_tool_name(mod)!r}). Key that modifier directly, or "
                "fusion_delete_animation first."
            )
        mod.SetInput("X", x, frame)
        mod.SetInput("Y", y, frame)
    return {
        "node": node,
        "input": input_id,
        "frame": frame,
        "value": [x, y],
        "modifier": _tool_name(mod),
    }


@mcp.tool()
def fusion_add_modifier(
    node: str,
    input_id: str,
    modifier_type: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Attach a modifier to an input and return its node name.

    Useful types: Perturb (wiggle — aliased to PerturbNumber/PerturbPoint by
    the input's datatype), Shake, Follower (= StyledTextFollower, per-character
    TextPlus animation), XYPath, Path, BezierSpline. The returned name is
    addressable like any node — tune it with fusion_get_node / fusion_set_value
    / fusion_set_keyframes.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    # Friendly aliases -> real registry ids (Perturb is registered per-datatype).
    if modifier_type == "Perturb":
        datatype = inp.GetAttrs().get("INPS_DataType")
        modifier_type = "PerturbPoint" if datatype == "Point" else "PerturbNumber"
    elif modifier_type == "Follower":
        modifier_type = "StyledTextFollower"
    with comp_lock(comp):
        if not tool.AddModifier(input_id, modifier_type):
            raise RuntimeError(
                f"AddModifier({modifier_type!r}) failed — check the Fusion registry "
                "id (e.g. PerturbNumber, PerturbPoint, Shake, StyledTextFollower, "
                "XYPath, Path, BezierSpline) and that it suits the input's datatype."
            )
    out = inp.GetConnectedOutput()
    if out is None:
        raise RuntimeError(
            f"Modifier {modifier_type!r} reported success but did not connect."
        )
    mod = out.GetTool()
    return {
        "node": node,
        "input": input_id,
        "modifier": _tool_name(mod),
        "type": _tool_type(mod),
    }


@mcp.tool()
def fusion_delete_animation(
    node: str,
    input_id: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Remove animation from an input (deletes its modifier), keeping the current
    on-screen value as the new static value."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    output = inp.GetConnectedOutput()
    if output is None:
        return {"node": node, "input": input_id, "animated": False}
    snap = to_jsonable(tool.GetInput(input_id, comp.GetAttrs()["COMPN_CurrentTime"]))
    with comp_lock(comp):
        output.GetTool().Delete()
        if isinstance(snap, dict):  # Point tables come back as {"1": x, "2": y, ...}
            try:
                tool.SetInput(input_id, {int(k): v for k, v in snap.items()})
            except (TypeError, ValueError):
                snap = None
        elif snap is not None:
            tool.SetInput(input_id, snap)
    return {"node": node, "input": input_id, "animated": False, "value": snap}


# --- Settings / preset import-export -------------------------------------------
@mcp.tool()
def fusion_save_node_setting(
    node: str,
    path: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Save a node's settings to a .setting file (path on the Resolve machine)."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    if not tool.SaveSettings(path):
        raise RuntimeError(f"Failed to save settings to {path!r}.")
    return {"node": node, "saved": path}


@mcp.tool()
def fusion_load_node_setting(
    node: str,
    path: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Apply a .setting preset file onto an existing node."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    with comp_lock(comp):
        tool.LoadSettings(path)
    return {"node": node, "loaded": path}


@mcp.tool()
def fusion_import_setting(
    path: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Paste a saved .setting / tool macro into the comp as new node(s)."""
    import builtins
    import collections

    # fusionscript's readfile evals the .setting expecting OrderedDict to be a
    # builtin; without this it NameErrors and returns nothing.
    if not hasattr(builtins, "OrderedDict"):
        builtins.OrderedDict = collections.OrderedDict

    comp = get_comp(clip_name, comp_index, comp_name, create=True)
    content = get_bmd().readfile(path)
    if not content:
        raise RuntimeError(f"Could not read settings file {path!r}.")
    before = {_tool_name(t) for t in _iter_tools(comp)}
    with comp_lock(comp):
        comp.Paste(content)
    new = [n for n in (_tool_name(t) for t in _iter_tools(comp)) if n not in before]
    if not new:
        raise RuntimeError(
            f"Paste added no nodes — {path!r} may not be a valid .setting file."
        )
    return {"imported": path, "new_nodes": new}
