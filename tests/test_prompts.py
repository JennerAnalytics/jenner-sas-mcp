"""Tests for the prompt templates.

A prompt only earns its place if it tells the model something it does not
already know. So most of what is asserted here is *content* — that the four
things a model cannot know are actually present, and that nothing stated is
false. A prompt that confidently teaches something wrong is worse than no
prompt at all.

The guards worth understanding:

* ``test_no_unreleased_features_taught`` — the templates must not advise syntax
  the public API rejects. Two constructs are deliberately excluded because they
  are not live there yet; if someone adds them before they ship, this fails.
* ``test_storage_default_is_stated_as_avro`` — THE divergence. A model that
  assumes SAS's sas7bdat default writes subtly wrong code.
* ``test_orientation_leads_with_sas_knowledge_applying`` — ordering, not
  presence. Meeting a list of differences before being told its existing
  knowledge transfers makes a model hedge and invent syntax.
"""

from __future__ import annotations

import re

from jenner_sas_mcp.prompts import (
    JENNER_AFFORDANCES,
    JENNER_ORIENTATION,
    SERVER_INSTRUCTIONS,
)
from jenner_sas_mcp.server import mcp

# Prompts that ask the model to WRITE or CHANGE SAS must carry the orientation
# block; a diagnostic or advisory prompt need not.
CODE_WRITING = {"jenner_orientation", "port_sas_program"}

EXPECTED = {
    "jenner_orientation",
    "jenner_beyond_sas",
    "port_sas_program",
    "choose_storage_engine",
    "debug_jenner_log",
}


async def _render(name: str, **kwargs: str) -> str:
    result = await mcp.get_prompt(name, kwargs)
    return "\n".join(
        m.content.text for m in result.messages if hasattr(m.content, "text")
    )


async def _render_required_only(name: str) -> str:
    p = next(x for x in await mcp.list_prompts() if x.name == name)
    return await _render(name, **{a.name: "X" for a in (p.arguments or []) if a.required})


async def test_all_prompts_registered() -> None:
    names = {p.name for p in await mcp.list_prompts()}
    assert names == EXPECTED


async def test_registering_prompts_does_not_disturb_tools() -> None:
    names = {t.name for t in await mcp.list_tools()}
    assert names == {"run_sas", "validate_sas", "get_run", "dataset_preview"}


async def test_every_prompt_renders_with_required_args_only() -> None:
    for p in await mcp.list_prompts():
        text = await _render_required_only(p.name)
        assert text.strip(), f"{p.name} rendered empty"


async def test_optional_args_change_the_rendering() -> None:
    # An optional argument that is silently ignored is a bug, not a nicety.
    without = await _render("jenner_beyond_sas")
    with_goal = await _render("jenner_beyond_sas", goal="MARKER_GOAL")
    assert with_goal != without
    assert "MARKER_GOAL" in with_goal

    without = await _render("debug_jenner_log", log_text="ERROR: x")
    with_sev = await _render("debug_jenner_log", log_text="ERROR: x", severity="ERROR")
    assert with_sev != without


async def test_arguments_are_interpolated_not_dropped() -> None:
    text = await _render("port_sas_program", sas_code="MARKER_SAS_CODE")
    assert "MARKER_SAS_CODE" in text

    text = await _render("choose_storage_engine", scenario="MARKER_SCENARIO")
    assert "MARKER_SCENARIO" in text

    text = await _render("debug_jenner_log", log_text="MARKER_LOG_TEXT")
    assert "MARKER_LOG_TEXT" in text


async def test_code_writing_prompts_carry_the_orientation() -> None:
    for name in CODE_WRITING:
        text = await _render_required_only(name)
        assert JENNER_ORIENTATION in text, f"{name} omits the orientation block"


# --- point 3: the model's SAS knowledge transfers -------------------------


def test_orientation_leads_with_sas_knowledge_applying() -> None:
    # Ordering matters. "Here is how this differs" before "your knowledge
    # applies" produces a model that hedges on ordinary SAS and invents
    # Jenner-specific syntax to be safe.
    low = JENNER_ORIENTATION.lower()
    assert low.startswith("your sas knowledge applies")
    assert low.index("your sas knowledge applies") < low.index("differences")


def test_orientation_says_most_programs_run_unchanged() -> None:
    low = JENNER_ORIENTATION.lower()
    assert "run unchanged" in low
    assert "do not invent jenner-specific syntax" in low


# --- point 1: where to learn more -----------------------------------------


def test_orientation_points_at_the_docs() -> None:
    # The model has no idea this site exists. Every URL below was checked to
    # resolve on 2026-08-04.
    for path in (
        "https://docs.jenneranalytics.com/getting-started/",
        "https://docs.jenneranalytics.com/getting-started/sas-differences/",
        "https://docs.jenneranalytics.com/language/",
        "https://docs.jenneranalytics.com/language/file-formats/",
        "https://docs.jenneranalytics.com/data-access/",
    ):
        assert path in JENNER_ORIENTATION, f"orientation omits {path}"


# --- point 2: getting started with what SAS does not have -----------------


async def test_beyond_sas_names_the_jenner_only_features() -> None:
    # A model has no prior for these; if nothing names them they will never be
    # reached for.
    text = await _render("jenner_beyond_sas")
    for feature in ("PROC FSQL", "PROC GQL", "PROC S3", "PROC AI"):
        assert feature in text, f"jenner_beyond_sas omits {feature}"
    # ...and a reference for each, since guessing the syntax is the failure
    # mode this prompt exists to prevent.
    assert text.count("https://docs.jenneranalytics.com/") >= 4


# --- point 4: the affordances of the system -------------------------------


def test_affordances_describe_what_a_run_returns() -> None:
    low = JENNER_AFFORDANCES.lower()
    for field in ("log", "exit_code", "listing", "datasets", "files", "diagnostics"):
        assert field in low, f"affordances omit the {field} field"
    assert "preview_url" in low
    assert "deterministic" in low


def test_affordances_state_that_work_does_not_persist() -> None:
    # The single most likely wrong assumption about this transport: that
    # successive calls share a session, as a SAS Compute session would.
    low = JENNER_AFFORDANCES.lower()
    assert "does not persist" in low
    assert "fresh sandbox" in low


def test_affordances_name_every_tool_the_server_exposes() -> None:
    for tool in ("run_sas", "validate_sas", "get_run", "dataset_preview"):
        assert tool in JENNER_AFFORDANCES, f"affordances omit {tool}"


async def test_prompts_point_at_the_tools_they_need() -> None:
    # A prompt that tells the model to run something should name the tool.
    for name in ("jenner_orientation", "jenner_beyond_sas", "port_sas_program"):
        text = await _render_required_only(name)
        assert "run_sas" in text, f"{name} never names the run tool"


# --- server instructions --------------------------------------------------
#
# Prompts only reach the model if a human invokes them. Instructions arrive at
# initialize unconditionally, so the irreducible core of all four points has to
# survive here or an autonomous model never sees any of it.


def test_server_carries_the_instructions() -> None:
    assert mcp.instructions == SERVER_INSTRUCTIONS


def test_instructions_cover_all_four_points() -> None:
    low = SERVER_INSTRUCTIONS.lower()
    # 3 — SAS knowledge transfers, stated before anything else.
    assert "without a sas" in low.split("\n\n")[0]
    assert "run unchanged" in low
    # 1 — where to look.
    assert "docs.jenneranalytics.com/getting-started/sas-differences/" in low
    # 2 — what SAS does not have.
    for feature in ("proc fsql", "proc gql", "proc s3", "proc ai"):
        assert feature in low, f"instructions omit {feature}"
    # 4 — affordances, including the assumption most likely to be wrong.
    assert "does not persist" in low
    assert "run_sas" in low and "validate_sas" in low
    # ...and THE divergence.
    assert "default is avro" in low
    assert "not sas7bdat" in low


def test_instructions_stay_small() -> None:
    # Paid for on every session, unlike a prompt. Detail belongs in the
    # templates; this is a budget, deliberately generous but finite.
    assert len(SERVER_INSTRUCTIONS) < 2000, (
        f"instructions grew to {len(SERVER_INSTRUCTIONS)} chars — "
        "move detail into a prompt template"
    )


def test_instructions_name_the_prompts_that_expand_them() -> None:
    # A summary is only safe if the long form is discoverable from it.
    for name in ("choose_storage_engine", "jenner_beyond_sas"):
        assert name in SERVER_INSTRUCTIONS
        assert name in EXPECTED


# --- accuracy -------------------------------------------------------------


def test_storage_default_is_stated_as_avro() -> None:
    # The single most consequential divergence. State it, and state that
    # SAS7BDAT still works — a model that concludes "sas7bdat unsupported" is
    # as wrong as one that assumes it is the default.
    low = JENNER_ORIENTATION.lower()
    assert "default is avro" in low
    assert "not sas7bdat" in low
    assert "sas7bdat is fully supported" in low


def test_no_unreleased_features_taught() -> None:
    """The templates must not advise syntax the public API rejects.

    Verified against https://api.jenneranalytics.com on 2026-08-04:
      libname x avro "d";                    -> parse error (not deployed)
      select * from "file.sas7bdat"          -> planning error (not deployed)

    Both have landed on dev but are not live. The prompts teach the forms that
    DO work: omit the engine to get the Avro default, and use a LIBNAME for a
    SAS7BDAT source in PROC SQL. Drop these guards when the API ships them.
    """
    import inspect

    from jenner_sas_mcp import prompts as mod

    # Strip the module docstring: it documents the exclusion on purpose.
    src = inspect.getsource(mod).replace(mod.__doc__ or "", "", 1)

    assert not re.search(r"libname\s+\w+\s+avro", src, re.I), (
        "prompts advise `libname <ref> avro`, which the public API rejects"
    )
    assert not re.search(r'from\s+"[\w./]+\.sas7bdat"', src, re.I), (
        "prompts advise a quoted .sas7bdat source in PROC SQL, "
        "which the public API rejects"
    )


def test_compat_shim_resolves_a_server_class() -> None:
    """The package must import under both mcp 1.x and 2.x.

    mcp 2.0 removed ``mcp.server.fastmcp`` outright, so a package importing it
    directly does not load at all on a current index — which is what shipped
    before this shim existed:

        ModuleNotFoundError: No module named 'mcp.server.fastmcp'

    ``_compat`` picks the right class per major. This asserts the shim resolved
    to a real server class exposing the surface this package uses, whichever
    major is installed; the CI matrix runs it under both.
    """
    from jenner_sas_mcp._compat import MCP_MAJOR, Server

    assert MCP_MAJOR in (1, 2)
    assert Server.__name__ in ("FastMCP", "MCPServer")
    for attr in ("tool", "prompt", "run", "list_tools", "list_prompts", "get_prompt"):
        assert callable(getattr(Server, attr, None)), f"server class lacks {attr}"
