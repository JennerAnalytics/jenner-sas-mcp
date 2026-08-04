"""Server-class compatibility across mcp 1.x and 2.x.

mcp 2.0 removed ``mcp.server.fastmcp`` and renamed the class:

    mcp 1.x   from mcp.server.fastmcp import FastMCP
    mcp 2.x   from mcp.server.mcpserver import MCPServer

Nothing else about the surface this package uses changed. The decorator
signatures for ``tool()`` and ``prompt()`` are byte-identical between the two,
``run()`` still defaults to stdio, and ``list_tools`` / ``list_prompts`` /
``get_prompt`` keep their shapes (2.x adds an optional ``context`` argument to
``get_prompt`` and can additionally return ``InputRequiredResult``, neither of
which affects a two-positional-argument call).

So the port is one import, and supporting both versions costs a try/except
rather than a fork. Preferring 2.x means an environment with both resolved
takes the newer path.

``Server`` is exported under a neutral name so nothing downstream has to know
which one it got.
"""

from __future__ import annotations

__all__ = ["Server", "MCP_MAJOR"]

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as Server

    MCP_MAJOR = 2
except ImportError:  # pragma: no cover - exercised by the 1.x test matrix
    from mcp.server.fastmcp import FastMCP as Server  # type: ignore[assignment]

    MCP_MAJOR = 1
