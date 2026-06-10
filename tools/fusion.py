"""Fusion node-graph tools: build the graph, pull node config, set params, animate.

Operates on a timeline clip's Fusion composition (the playhead clip by default,
or one targeted by ``clip_name`` / ``comp_index`` / ``comp_name``). Nodes are
addressed by their Fusion name (e.g. ``Blur1``); ``fusion_get_node`` reveals the
valid input IDs + datatypes for a node so params can be set correctly.
"""

from __future__ import annotations

from resolve.app import mcp
from resolve.connection import (
    comp_lock,
    find_fusion_tool,
    get_comp,
    get_current_video_item,
    to_jsonable,
)

# Datatypes that carry a readable scalar value (others are image/mask connections).
_SCALAR_TYPES = {"Number", "Text", "FuID", "Point", "Color"}


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


def _main_input_id(tool) -> str:
    main = tool.FindMainInput(1)
    if main is None:
        raise RuntimeError(f"Node {_tool_name(tool)!r} has no primary (image) input.")
    return main.GetAttrs().get("INPS_ID")


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

    Optionally rename it. Returns the node's final name and type.
    """
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
    return {"name": _tool_name(tool), "type": _tool_type(tool)}


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
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Read a node's inputs: id, datatype, current value, animated?, expression.

    The readable summary to decide edits. Image/mask inputs are reported as
    connections (set those with fusion_connect, not the scalar setters).
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, name)

    inputs = []
    for inp in (tool.GetInputList() or {}).values():
        attrs = inp.GetAttrs()
        input_id = attrs.get("INPS_ID")
        datatype = attrs.get("INPS_DataType")
        entry = {"id": input_id, "datatype": datatype}
        if datatype in _SCALAR_TYPES:
            try:
                entry["value"] = to_jsonable(tool.GetInput(input_id))
            except Exception:
                entry["value"] = None
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

    return {"name": _tool_name(tool), "type": _tool_type(tool), "inputs": inputs}


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
    """Read keyframes for one input (if ``input_id`` given) or the whole node."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, name)
    if input_id:
        return {
            "node": name,
            "input": input_id,
            "keyframes": to_jsonable(_input_obj(tool, input_id).GetKeyFrames()),
        }
    return {"node": name, "keyframes": to_jsonable(tool.GetKeyFrames())}


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
    """Key a numeric input to ``value`` at ``frame``.

    Auto-animates the input (adds a BezierSpline) on the first keyframe.
    """
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    with comp_lock(comp):
        if inp.GetConnectedOutput() is None:  # not yet animated
            tool.AddModifier(input_id, "BezierSpline")
        tool.SetInput(input_id, value, frame)
    return {"node": node, "input": input_id, "frame": frame, "value": value}


@mcp.tool()
def fusion_delete_animation(
    node: str,
    input_id: str,
    clip_name: str | None = None,
    comp_index: int = 1,
    comp_name: str | None = None,
) -> dict:
    """Remove animation from an input (deletes its modifier), reverting to static."""
    comp = get_comp(clip_name, comp_index, comp_name)
    tool = find_fusion_tool(comp, node)
    inp = _input_obj(tool, input_id)
    output = inp.GetConnectedOutput()
    if output is None:
        return {"node": node, "input": input_id, "animated": False}
    with comp_lock(comp):
        output.GetTool().Delete()
    return {"node": node, "input": input_id, "animated": False}


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
    import BlackmagicFusion as bmd  # provided by the Fusion scripting runtime

    comp = get_comp(clip_name, comp_index, comp_name, create=True)
    content = bmd.readfile(path)
    if not content:
        raise RuntimeError(f"Could not read settings file {path!r}.")
    with comp_lock(comp):
        comp.Paste(content)
    return {"imported": path, "nodes": [_tool_name(t) for t in _iter_tools(comp)]}
