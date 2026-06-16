"""Jenner SAS MCP server — run SAS-compatible programs from any MCP client."""

from .server import main, mcp

__version__ = "0.1.0"
__all__ = ["main", "mcp", "__version__"]
