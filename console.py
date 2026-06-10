#!/usr/bin/env python
"""Interactive REPL for the DaVinci Resolve MCP tools.

Runs continuously, holding one warm Resolve connection, and lets you fire tools
with slash commands:

    resolve> /help                     list all tools
    resolve> /help get_timeline_info   show one tool's parameters
    resolve> /list_timelines
    resolve> /get_timeline_info --name "Timeline 1"
    resolve> /create_timeline --name smoke-test
    resolve> /import_media --paths "D:\\a.mp4" --paths "D:\\b.mp4"
    resolve> /quit

Reuses the tool registry, schema-typed arg parsing and pretty-printing from
cli.py. Must be run with Windows Python (python.exe) so it can reach Resolve.
"""

from __future__ import annotations

import asyncio
import shlex
import traceback

import cli  # builds the tool registry (imports server, registers @mcp.tool())
from resolve.connection import get_resolve

_META = {"help", "?", "tools", "list", "h"}
_QUIT = {"quit", "exit", "q"}


def _tokenize(line: str) -> list[str]:
    """Split a command line, preserving Windows backslashes; strip outer quotes."""
    tokens = shlex.split(line, posix=False)  # posix=False -> backslashes stay literal
    out = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
            tok = tok[1:-1]
        out.append(tok)
    return out


def run_command(line: str) -> bool:
    """Execute one REPL line. Returns False when the user wants to exit."""
    line = line.strip()
    if not line:
        return True
    if line[0] == "/":
        line = line[1:]

    parts = _tokenize(line)
    if not parts:
        return True
    cmd, rest = parts[0], parts[1:]

    if cmd in _QUIT:
        return False

    if cmd in _META:
        if rest and rest[0] in cli._TOOLS:
            cli._help_tool(cli._TOOLS[rest[0]])
        else:
            cli._list_tools()
            print("meta:  /help [tool]   /quit")
        return True

    tool = cli._TOOLS.get(cmd)
    if tool is None:
        print(f"Unknown command /{cmd} — type /help to list tools.")
        return True

    if any(a in ("-h", "--help") for a in rest):
        cli._help_tool(tool)
        return True

    debug = "--debug" in rest
    rest = [a for a in rest if a != "--debug"]

    try:
        kwargs = cli._parse_args(tool, rest)
        result = asyncio.run(tool.fn(**kwargs)) if tool.is_async else tool.fn(**kwargs)
        cli._print(result)
    except SystemExit as exc:  # _parse_args reports bad args this way
        print(exc)
    except Exception as exc:
        if debug:
            traceback.print_exc()
        else:
            print(f"ERROR ({type(exc).__name__}): {exc}")
    return True


def main() -> int:
    try:
        resolve = get_resolve()
        print(f"Connected: {resolve.GetProductName()} {resolve.GetVersionString()}")
    except Exception as exc:
        print(f"WARNING: not connected to Resolve yet: {exc}")
        print("(Tools will retry the connection when called.)")

    print(f"{len(cli._TOOLS)} tools loaded. Type /help for the list, /quit to exit.")

    try:
        import readline  # noqa: F401  (line editing + history where available)
    except Exception:
        pass

    while True:
        try:
            line = input("resolve> ")
        except EOFError:  # Ctrl-D
            print()
            break
        except KeyboardInterrupt:  # Ctrl-C cancels the line, doesn't quit
            print("^C")
            continue
        if not run_command(line):
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
