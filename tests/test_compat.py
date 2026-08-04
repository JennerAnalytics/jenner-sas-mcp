"""The package must import and serve under both mcp 1.x and 2.x.

mcp 2.0 removed ``mcp.server.fastmcp`` outright, so a package importing it
directly does not load at all against a current index — which is what shipped:

    ModuleNotFoundError: No module named 'mcp.server.fastmcp'

``uv sync`` in CI resolved the same way, so CI was green while ``uvx
jenner-sas-mcp`` — the install path the README leads with — was broken. That is
why these assertions live next to an `mcp-version` CI matrix axis rather than
standing alone: the test only means something when both majors are exercised.
"""

from __future__ import annotations

from jenner_sas_mcp._compat import MCP_MAJOR, Server


def test_shim_resolves_a_server_class() -> None:
    assert MCP_MAJOR in (1, 2)
    assert Server.__name__ in ("FastMCP", "MCPServer")


def test_resolved_class_exposes_the_surface_this_package_uses() -> None:
    # Naming the surface explicitly means a future rename fails here with a
    # readable message, rather than at import time in a user's client.
    for attr in ("tool", "prompt", "run", "list_tools", "list_prompts", "get_prompt"):
        assert callable(getattr(Server, attr, None)), f"server class lacks {attr}"


def test_the_server_module_actually_builds_its_server() -> None:
    # Import-level check: this is the line that was failing in the wild.
    from jenner_sas_mcp.server import mcp

    assert isinstance(mcp, Server)


async def test_tools_register_under_whichever_major_is_installed() -> None:
    # The decorator surface is what the port depends on being unchanged. If
    # `@mcp.tool()` ever behaves differently between majors, the tools quietly
    # vanish rather than erroring — so assert they are actually there.
    from jenner_sas_mcp.server import mcp

    names = {t.name for t in await mcp.list_tools()}
    assert names == {"run_sas", "validate_sas", "get_run", "dataset_preview"}
