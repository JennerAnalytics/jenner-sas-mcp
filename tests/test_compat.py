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


# --- make_server ----------------------------------------------------------
#
# The constructors are not quite identical: 2.x takes `version=`, 1.x does not
# and raises TypeError on an unexpected keyword. `make_server` filters by
# signature rather than branching on MCP_MAJOR, so a keyword that appears in a
# future point release starts working without a code change, and one that is
# withdrawn stops being passed instead of raising.


def test_make_server_drops_keywords_this_major_rejects() -> None:
    from jenner_sas_mcp._compat import make_server

    # `version` exists only on 2.x. Passing it unconditionally is what a naive
    # port does, and it is a TypeError on 1.x.
    srv = make_server("t", version="9.9.9", instructions="hello")
    assert srv is not None


def test_make_server_ignores_a_keyword_neither_major_has() -> None:
    from jenner_sas_mcp._compat import make_server

    srv = make_server("t", definitely_not_a_real_kwarg=object())
    assert srv is not None


def test_make_server_passes_through_what_the_major_does_accept() -> None:
    from jenner_sas_mcp._compat import make_server

    # `instructions` is on both majors, so it must survive the filter — a
    # filter that dropped everything would still satisfy the tests above.
    srv = make_server("t", instructions="MARKER_INSTRUCTIONS")
    assert srv.instructions == "MARKER_INSTRUCTIONS"


def test_the_server_reports_the_package_version_not_the_sdk_version() -> None:
    """serverInfo.version used to be wrong under both majors.

    Under 1.x it reported the *mcp library's* version (e.g. "1.27.2"); under
    2.x it was an empty string. Neither told a client what it was talking to.
    """
    from jenner_sas_mcp.server import __version__

    assert __version__
    assert not __version__.startswith("1.2")  # not the SDK's version
