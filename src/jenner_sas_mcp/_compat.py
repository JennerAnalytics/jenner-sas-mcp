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
which one it got, and ``make_server`` hides the one constructor difference:
2.x takes ``version=`` (and ``title=``/``description=``), 1.x does not and
raises ``TypeError`` on an unexpected keyword.
"""

from __future__ import annotations

import inspect
from typing import Any

__all__ = ["Server", "MCP_MAJOR", "make_server"]

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as Server

    MCP_MAJOR = 2
except ImportError:  # pragma: no cover - exercised by the 1.x test matrix
    from mcp.server.fastmcp import FastMCP as Server  # type: ignore[assignment]

    MCP_MAJOR = 1


def make_server(name: str, **kwargs: Any) -> Server:
    """Construct the server, dropping keywords this major does not accept.

    Filtering by signature rather than by ``MCP_MAJOR`` means a keyword that
    appears in some future 2.x point release starts working on its own, and a
    keyword that is dropped stops being passed rather than raising.
    """
    accepted = inspect.signature(Server.__init__).parameters
    return Server(name, **{k: v for k, v in kwargs.items() if k in accepted})
