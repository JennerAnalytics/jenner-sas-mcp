"""Tests for the prompt templates.

The point of these prompts is to state Jenner's divergences from SAS
accurately. A prompt that confidently teaches something false is worse than no
prompt at all, so most of what is asserted here is content, not plumbing.

The two guards worth understanding:

* ``test_no_unreleased_features_taught`` — the templates must not advise syntax
  that the public API rejects. Two constructs are deliberately excluded because
  they are not live there yet; if someone adds them before they ship, this
  fails.
* ``test_storage_default_is_stated_as_avro`` — this is THE divergence. A model
  that assumes SAS's sas7bdat default writes subtly wrong code, so every
  code-writing prompt has to carry it.
"""

from __future__ import annotations

import re

from jenner_sas_mcp.prompts import JENNER_DIFFERENCES
from jenner_sas_mcp.server import mcp

# Prompts that ask the model to WRITE or CHANGE code must carry the
# orientation block; a diagnostic prompt need not.
CODE_WRITING = {"jenner_vs_sas", "write_jenner_program", "port_sas_program"}

EXPECTED = {
    "jenner_vs_sas",
    "write_jenner_program",
    "port_sas_program",
    "debug_jenner_log",
    "choose_storage_engine",
    "explore_dataset",
    "federated_query",
    "review_jenner_program",
}


async def _render(name: str, **kwargs: str) -> str:
    result = await mcp.get_prompt(name, kwargs)
    return "\n".join(
        m.content.text for m in result.messages if hasattr(m.content, "text")
    )


async def test_all_prompts_registered() -> None:
    names = {p.name for p in await mcp.list_prompts()}
    assert names == EXPECTED


async def test_registering_prompts_does_not_disturb_tools() -> None:
    names = {t.name for t in await mcp.list_tools()}
    assert names == {"run_sas", "validate_sas", "get_run", "dataset_preview"}


async def test_every_prompt_renders_with_required_args_only() -> None:
    for p in await mcp.list_prompts():
        required = {a.name: "PLACEHOLDER" for a in (p.arguments or []) if a.required}
        text = await _render(p.name, **required)
        assert text.strip(), f"{p.name} rendered empty"


async def test_optional_args_change_the_rendering() -> None:
    # An optional argument that is silently ignored is a bug, not a nicety.
    without = await _render("explore_dataset", dataset="work.a")
    with_focus = await _render("explore_dataset", dataset="work.a", focus="age")
    assert with_focus != without
    assert "age" in with_focus

    without = await _render("debug_jenner_log", log_text="ERROR: x")
    with_sev = await _render("debug_jenner_log", log_text="ERROR: x", severity="ERROR")
    assert with_sev != without


async def test_arguments_are_interpolated_not_dropped() -> None:
    text = await _render("write_jenner_program", task="MARKER_TASK_TEXT")
    assert "MARKER_TASK_TEXT" in text

    text = await _render("port_sas_program", sas_code="MARKER_SAS_CODE")
    assert "MARKER_SAS_CODE" in text


async def test_code_writing_prompts_carry_the_differences() -> None:
    for name in CODE_WRITING:
        required = {
            a.name: "X"
            for a in (
                next(p for p in await mcp.list_prompts() if p.name == name).arguments
                or []
            )
            if a.required
        }
        text = await _render(name, **required)
        assert JENNER_DIFFERENCES in text, f"{name} omits the orientation block"


def test_storage_default_is_stated_as_avro() -> None:
    # The single most consequential divergence. State it, and state that
    # SAS7BDAT still works — a model that concludes "sas7bdat unsupported"
    # is as wrong as one that assumes it is the default.
    low = JENNER_DIFFERENCES.lower()
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


def test_differences_block_names_the_jenner_only_procs() -> None:
    # A model has no prior for these; if the block omits them they will never
    # be reached for.
    for proc in ("PROC FSQL", "PROC GQL", "PROC S3", "PROC AI"):
        assert proc in JENNER_DIFFERENCES


async def test_prompts_point_at_the_tools_they_need() -> None:
    # A prompt that tells the model to run something should name the tool.
    for name in ("write_jenner_program", "explore_dataset", "federated_query"):
        p = next(x for x in await mcp.list_prompts() if x.name == name)
        required = {a.name: "X" for a in (p.arguments or []) if a.required}
        text = await _render(name, **required)
        assert "run_sas" in text, f"{name} never names the run tool"
