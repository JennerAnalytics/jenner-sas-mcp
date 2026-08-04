"""MCP server exposing the Jenner SAS-compatible run API as tools.

The Jenner engine runs SAS/Jenner programs in a locked-down sandbox and
returns structured results (log, listing/stdout, output files, WORK
datasets, diagnostics). This server wraps the public HTTP API at
``https://api.jenneranalytics.com`` so any MCP-capable client (Claude
Desktop, Claude Code, etc.) can run and validate SAS programs without a SAS
Institute licence.

Configuration (environment variables):

* ``JENNER_API_URL``  Base URL of the API. Default
  ``https://api.jenneranalytics.com``.
* ``JENNER_API_KEY``  Optional bearer token. Without it the caller is the
  Anonymous tier (shorter timeouts, lower observation caps, stricter
  rate limits).
* ``JENNER_MAX_LOG_CHARS``  Per-field cap (log/output) returned to the
  model, to protect the context window. Default ``40000``. The full
  artifacts remain retrievable via ``get_run`` using the run id + token.
"""

from __future__ import annotations

import csv
import io
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx

from ._compat import make_server
from .prompts import SERVER_INSTRUCTIONS, register_prompts

__all__ = ["mcp", "main"]

try:
    __version__ = version("jenner-sas-mcp")
except PackageNotFoundError:  # running from a source tree, not installed
    __version__ = "0.0.0+source"

DEFAULT_API_URL = "https://api.jenneranalytics.com"
# Generous default so the network round-trip dominates, not the engine.
HTTP_TIMEOUT = 120.0


def _api_url() -> str:
    return os.environ.get("JENNER_API_URL", DEFAULT_API_URL).rstrip("/")


def _max_log_chars() -> int:
    try:
        return int(os.environ.get("JENNER_MAX_LOG_CHARS", "40000"))
    except ValueError:
        return 40000


def _auth_headers() -> dict[str, str]:
    key = os.environ.get("JENNER_API_KEY", "").strip()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _clip(text: str | None) -> str | None:
    """Trim a large text field so a 5 MB log cannot blow the context window.

    Keeps the head and tail (where errors usually live) and notes the cut.
    """
    if text is None:
        return None
    cap = _max_log_chars()
    if cap <= 0 or len(text) <= cap:
        return text
    head = cap // 2
    tail = cap - head
    omitted = len(text) - cap
    return (
        f"{text[:head]}\n\n"
        f"... [{omitted} characters omitted — retrieve the full artifact with "
        f"get_run(run_id, access_token)] ...\n\n"
        f"{text[-tail:]}"
    )


def _summarize_run(data: dict[str, Any]) -> dict[str, Any]:
    """Reshape the raw run-result JSON into a compact, model-friendly dict.

    Drops nothing the model needs to reason about (status, severity, log,
    listing, dataset/file summaries, diagnostics) but clips the two
    unbounded text fields and flattens the dataset/file lists.
    """
    exit_code = data.get("exit_code")
    datasets = [
        {
            "name": d.get("name"),
            "rows": d.get("rows"),
            "columns": d.get("columns"),
            "file_format": d.get("file_format"),
            "preview_url": d.get("preview_url"),
            "download_url": d.get("download_url"),
        }
        for d in data.get("datasets", []) or []
    ]
    files = [
        {
            "name": f.get("name"),
            "content_type": f.get("content_type"),
            "size_bytes": f.get("size_bytes"),
            "url": f.get("url"),
        }
        for f in data.get("files", []) or []
    ]
    return {
        "run_id": data.get("run_id"),
        "status": data.get("status"),
        # exit_code follows SAS severity: 0 clean, 1 warnings (still ok),
        # >= 2 error. `ok` collapses that to a single boolean.
        "ok": isinstance(exit_code, int) and exit_code < 2,
        "exit_code": exit_code,
        "jenner_version": data.get("jenner_version"),
        "duration_ms": data.get("duration_ms"),
        "log": _clip(data.get("log")),
        "log_truncated": bool(data.get("log_truncated")),
        "listing": _clip(data.get("output")),
        "listing_truncated": bool(data.get("output_truncated")),
        "datasets": datasets,
        "files": files,
        "diagnostics": data.get("diagnostics", {}),
        # Capability token needed to fetch full artifacts / dataset rows.
        "access_token": data.get("access_token"),
    }


def _error(exc: Exception) -> dict[str, Any]:
    """Convert a transport/HTTP failure into a structured tool result.

    Returning (rather than raising) lets the model read the status code
    and message and decide what to do next.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        body = exc.response.text
        if len(body) > 2000:
            body = body[:2000] + " ...[truncated]"
        return {
            "error": "http_error",
            "status_code": exc.response.status_code,
            "message": body,
        }
    if isinstance(exc, httpx.TimeoutException):
        return {
            "error": "timeout",
            "message": (
                "The Jenner API did not respond within "
                f"{HTTP_TIMEOUT:.0f}s. The run may be too large for the "
                "caller's tier, or the service may be busy."
            ),
        }
    return {"error": "request_failed", "message": str(exc)}


def _parse_dataset_preview(resp: httpx.Response) -> dict[str, Any]:
    """Normalize a dataset-preview response into a structured dict.

    The Jenner API serves dataset previews as **CSV** (``text/csv``)
    regardless of the dataset's on-disk format (Avro, Parquet, …). Earlier
    this tool called ``resp.json()`` directly, which raised ``JSONDecodeError``
    on the CSV body — surfacing to the model as a failed/empty preview (the
    rough edge users hit on a 1-row Avro dataset). Parse the CSV into the
    documented ``{columns, rows, row_count}`` shape instead, while still
    passing through a genuine JSON body if the API ever serves one.

    Values are returned as strings (CSV carries no type information); the
    dataset's row/column metadata and true row count come from the run's
    ``datasets`` entry. ``row_count`` here is the number of rows in this
    preview sample, which may be fewer than the dataset's total.
    """
    content_type = resp.headers.get("content-type", "")
    if "json" in content_type.lower():
        return resp.json()

    records = list(csv.reader(io.StringIO(resp.text or "")))
    if not records:
        return {"columns": [], "rows": [], "row_count": 0, "format": "csv"}
    columns = records[0]
    rows = [dict(zip(columns, values)) for values in records[1:] if values]
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "format": "csv",
    }


mcp = make_server(
    "jenner-sas",
    version=__version__,
    # Delivered to the model at initialize, unprompted — the only orientation
    # channel that does not depend on a human invoking a prompt. See
    # prompts.py for why this and not just the templates.
    instructions=SERVER_INSTRUCTIONS,
)

# Prompt templates: the long forms of what the instructions summarise, for
# when the model (or the user) needs the detail. See prompts.py.
register_prompts(mcp)


@mcp.tool()
async def run_sas(
    script: str,
    deterministic: bool = True,
    timeout: int | None = None,
    max_obs: int | None = None,
) -> dict[str, Any]:
    """Run a SAS/Jenner program on the Jenner engine and return its results.

    Jenner is a SAS-compatible engine: write standard SAS (DATA steps,
    PROCs, macros) and it executes without a SAS licence. Use this to run
    a program and inspect what it produced.

    Args:
        script: The SAS/Jenner source code to execute.
        deterministic: When true (default), the RNG is seeded and
            ``today()``/``datetime()`` are frozen so repeated runs of the
            same program produce identical output. Set false for genuine
            randomness (e.g. simulations you want to vary).
        timeout: Wall-clock budget in seconds. Defaults to the server's
            policy (60s) and is capped by the caller's tier.
        max_obs: Cap on observations processed. Only honoured within the
            caller's tier policy. Leave unset for the tier default.

    Returns:
        A dict with: ``run_id``, ``status`` ("ok"/"error"), ``ok`` (bool:
        SAS severity < 2), ``exit_code`` (SAS severity), ``log`` (the SAS
        log — the primary place to read errors and notes), ``listing``
        (printed/stdout output), ``datasets`` (each WORK dataset's name,
        row count, columns, and a ``preview_url``), ``files`` (output
        artifacts such as PNG/SVG/CSV with download ``url``s),
        ``diagnostics``, and an ``access_token`` for later retrieval.
        Large ``log``/``listing`` fields are clipped (head+tail); fetch
        the full text with ``get_run``.
    """
    data: dict[str, str] = {"deterministic": "true" if deterministic else "false"}
    if timeout is not None:
        data["timeout"] = str(timeout)
    if max_obs is not None:
        data["max_obs"] = str(max_obs)

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_api_url()}/v1/run",
                files={"script": ("program.sas", script)},
                data=data,
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            return _summarize_run(resp.json())
    except Exception as exc:  # noqa: BLE001 - surfaced to the model as data
        return _error(exc)


@mcp.tool()
async def validate_sas(script: str) -> dict[str, Any]:
    """Parse-check a SAS/Jenner program without running it.

    Fast (fixed ~10s parse budget), no data, no execution, no licensing.
    Use it to confirm syntax before a full run, or to lint generated code.

    Args:
        script: The SAS/Jenner source to validate.

    Returns:
        ``{"valid": bool, "diagnostics": [{"severity", "message"}, ...]}``.
        An invalid script is a normal result, not an error — read the
        diagnostics to see what to fix.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{_api_url()}/v1/validate",
                files={"script": ("program.sas", script)},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool()
async def get_run(run_id: str, access_token: str) -> dict[str, Any]:
    """Retrieve a completed run by id, with the full (unclipped) artifacts.

    Use this after ``run_sas`` when the ``log`` or ``listing`` was clipped
    and you need the complete text, or to revisit an earlier run.

    Args:
        run_id: The ``run_id`` returned by ``run_sas``.
        access_token: The ``access_token`` returned by ``run_sas`` (a
            capability token scoped to this run).

    Returns:
        The same summarized shape as ``run_sas`` — but here the ``log``
        and ``listing`` are returned in full (still subject to the 5 MB /
        10 MB API caps).
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_api_url()}/v1/run/{run_id}",
                params={"token": access_token},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            # Retrieval should not re-clip; the caller explicitly wants the
            # full text. Temporarily bypass clipping by formatting directly.
            data = resp.json()
            summary = _summarize_run(data)
            summary["log"] = data.get("log")
            summary["listing"] = data.get("output")
            return summary
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool()
async def dataset_preview(
    run_id: str,
    dataset: str,
    access_token: str,
) -> dict[str, Any]:
    """Preview the rows of a WORK dataset produced by a run.

    Args:
        run_id: The ``run_id`` returned by ``run_sas``.
        dataset: The dataset name (as listed in the run's ``datasets``).
        access_token: The ``access_token`` returned by ``run_sas``.

    Returns:
        ``{"columns": [...], "rows": [{col: value, ...}, ...], "row_count":
        N, "format": "csv"}``. Values are strings (the preview is served as
        CSV, which carries no type information); ``row_count`` is the number
        of rows in this sample, which may be fewer than the dataset's total.
        For the complete, typed dataset use the ``download_url`` from the
        run's ``datasets`` entry.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{_api_url()}/v1/run/{run_id}/datasets/{dataset}",
                params={"token": access_token},
                headers=_auth_headers(),
            )
            resp.raise_for_status()
            return _parse_dataset_preview(resp)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def main() -> None:
    """Console-script entry point. Serves over stdio (the MCP default)."""
    mcp.run()


if __name__ == "__main__":
    main()
