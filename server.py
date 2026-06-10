"""DaVinci Resolve MCP server entrypoint.

Must be run by **Windows Python** so it can load Resolve's fusionscript.dll.
Importing the tool modules registers their @mcp.tool() functions on the shared
FastMCP instance. Transport is selectable via RESOLVE_MCP_TRANSPORT so the same
server can run over stdio (Claude Code) or streamable-http (OpenAI-compatible
bridge) without code changes.
"""

import os
import sys

# Make package imports resolve even when launched by absolute/UNC path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from resolve.app import mcp

# Importing these modules registers the @mcp.tool() decorators. noqa: F401
from tools import inspect, edit, render, fusion  # noqa: E402, F401


def main() -> None:
    transport = os.getenv("RESOLVE_MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
