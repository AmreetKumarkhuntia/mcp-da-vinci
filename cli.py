#!/usr/bin/env python
"""Dev CLI for poking at the DaVinci Resolve MCP tools directly.

Calls the registered @mcp.tool() functions by name with ``--arg value`` pairs and
pretty-prints the result — no MCP protocol, no Inspector, just fast feedback.
Must be run with Windows Python (python.exe) so it can reach Resolve.

Examples
--------
    python.exe cli.py                       # list all tools
    python.exe cli.py get_timeline_info     # call with no args
    python.exe cli.py get_timeline_info --name "Timeline 1"
    python.exe cli.py create_timeline --name smoke-test
    python.exe cli.py import_media --paths "D:\\a.mp4" --paths "D:\\b.mp4"
    python.exe cli.py add_render_job --target_dir "D:\\out" --custom_name take1
    python.exe cli.py <tool> --help         # show a tool's parameters
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback

import server  # importing registers every @mcp.tool()

_TOOLS = {t.name: t for t in server.mcp._tool_manager.list_tools()}


# --- schema helpers ------------------------------------------------------------
def _json_type(prop: dict) -> str:
    """The effective JSON type of a parameter (unwrapping Optional/anyOf)."""
    if "type" in prop:
        return prop["type"]
    for sub in prop.get("anyOf", []):
        if sub.get("type") and sub["type"] != "null":
            return sub["type"]
    return "string"


def _coerce_scalar(val: str, jtype: str):
    if jtype == "integer":
        return int(val)
    if jtype == "number":
        return float(val)
    if jtype == "boolean":
        return str(val).lower() in ("1", "true", "yes", "y", "on")
    return val


def _properties(tool) -> dict:
    return tool.parameters.get("properties", {})


def _required(tool) -> list[str]:
    return tool.parameters.get("required", [])


# --- output --------------------------------------------------------------------
def _print_image(img) -> None:
    """Save MCP Image content to a temp file and print where it landed."""
    import tempfile

    data = img.data if img.data is not None else open(img.path, "rb").read()
    suffix = f".{img._format.lower()}" if getattr(img, "_format", None) else ".png"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        path = fh.name
    dims = ""
    try:
        from PIL import Image as PILImage

        with PILImage.open(path) as im:
            dims = f" {im.width}x{im.height}"
    except Exception:  # noqa: BLE001 - dimensions are decoration only
        pass
    print(f"[image{suffix}{dims}, {len(data)} bytes] -> {path}")


def _print(obj) -> None:
    from mcp.server.fastmcp import Image as MCPImage

    if isinstance(obj, MCPImage):
        _print_image(obj)
    elif isinstance(obj, (list, tuple)) and any(
        isinstance(item, MCPImage) for item in obj
    ):
        for item in obj:
            _print(item)
    elif isinstance(obj, (dict, list)):
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(obj)


def _list_tools() -> None:
    by_module: dict[str, list] = {}
    for tool in _TOOLS.values():
        module = getattr(tool.fn, "__module__", "tools").split(".")[-1]
        by_module.setdefault(module, []).append(tool)

    print(f"{len(_TOOLS)} tools (call: python.exe cli.py <name> [--arg value ...])\n")
    for module in sorted(by_module):
        print(f"[{module}]")
        for tool in sorted(by_module[module], key=lambda t: t.name):
            summary = (tool.description or "").strip().splitlines()[0]
            print(f"  {tool.name:<28} {summary}")
        print()


def _help_tool(tool) -> None:
    print(f"{tool.name}\n  {(tool.description or '').strip()}\n")
    props = _properties(tool)
    if not props:
        print("  (no parameters)")
        return
    required = _required(tool)
    print("  parameters:")
    for name, prop in props.items():
        jtype = _json_type(prop)
        if jtype == "array":
            jtype = f"array<{prop.get('items', {}).get('type', 'string')}> (repeat --{name})"
        tag = "required" if name in required else f"default={prop.get('default')!r}"
        print(f"    --{name:<20} {jtype:<28} {tag}")


# --- arg parsing ---------------------------------------------------------------
def _parse_args(tool, argv: list[str]) -> dict:
    """Turn ``--key value`` / ``--key=value`` tokens into kwargs, typed per schema."""
    props = _properties(tool)
    kwargs: dict = {}
    i = 0
    while i < len(argv):
        token = argv[i]
        if not token.startswith("--"):
            raise SystemExit(f"Unexpected argument {token!r} (expected --name value).")
        if "=" in token:
            key, value = token[2:].split("=", 1)
            i += 1
        else:
            key = token[2:]
            if i + 1 >= len(argv):
                raise SystemExit(f"Missing value for --{key}.")
            value = argv[i + 1]
            i += 2

        if key not in props:
            raise SystemExit(
                f"Unknown arg --{key} for {tool.name}. Try: python.exe cli.py {tool.name} --help"
            )

        prop = props[key]
        if _json_type(prop) == "array":
            item_type = prop.get("items", {}).get("type", "string")
            kwargs.setdefault(key, []).append(_coerce_scalar(value, item_type))
        else:
            kwargs[key] = _coerce_scalar(value, _json_type(prop))
    return kwargs


# --- main ----------------------------------------------------------------------
def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-l", "--list", "list", "-h", "--help"):
        _list_tools()
        return 0

    name, rest = argv[0], argv[1:]
    tool = _TOOLS.get(name)
    if tool is None:
        print(f"Unknown tool {name!r}. Run with no args to list tools.", file=sys.stderr)
        return 2

    if any(a in ("-h", "--help") for a in rest):
        _help_tool(tool)
        return 0

    debug = "--debug" in rest
    rest = [a for a in rest if a != "--debug"]

    try:
        kwargs = _parse_args(tool, rest)
        result = (
            asyncio.run(tool.fn(**kwargs)) if tool.is_async else tool.fn(**kwargs)
        )
        _print(result)
        return 0
    except Exception as exc:  # surface tool errors the way a client would see them
        if debug:
            traceback.print_exc()
        else:
            print(f"ERROR ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
