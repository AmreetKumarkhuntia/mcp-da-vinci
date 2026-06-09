"""Shared FastMCP instance.

Kept in its own module so ``server.py`` and every tool module can ``from
resolve.app import mcp`` without creating a circular import.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("davinci-resolve")
