[![MseeP.ai Security Assessment Badge](https://mseep.net/pr/jenneranalytics-jenner-sas-mcp-badge.png)](https://mseep.ai/app/jenneranalytics-jenner-sas-mcp)

# Jenner SAS MCP Server

Run and validate **SAS®** programs from any [Model Context Protocol](https://modelcontextprotocol.io)
client — Claude Desktop, Claude Code, Cursor, and others — without a SAS
Institute licence. This server wraps the public Jenner run API
(`https://api.jenneranalytics.com`), which executes SAS-compatible programs in
a locked-down sandbox and returns the log, listing, output files, WORK
datasets, and diagnostics as structured JSON.

[Jenner](https://jenneranalytics.com) is a SAS-compatible engine: write
standard SAS (DATA steps, PROCs, macros) and it runs as-is.

## What the model can do

| Tool | What it does |
|------|--------------|
| `run_sas` | Execute a SAS/Jenner program; returns status, SAS log, listing, WORK datasets (rows/columns + preview URL), output files (PNG/SVG/CSV), and diagnostics. |
| `validate_sas` | Parse-check a program (~10s, no execution) — confirm syntax before running, or lint generated code. |
| `get_run` | Re-fetch a completed run by id with the **full** (unclipped) log and listing. |
| `dataset_preview` | Preview the rows of a WORK dataset produced by a run. |

## Orientation: what the model cannot already know

A model already knows how to write SAS, profile a dataset, and read a log.
Telling it how to do those is padding. What it genuinely cannot know is:

1. **Where to learn more** — it has no idea `docs.jenneranalytics.com` exists.
2. **How to get started with what Jenner has and SAS does not** — `PROC FSQL`,
   `PROC GQL`, `PROC S3`, `PROC AI`, native database `LIBNAME`s. No training
   data covers these, so an unaided model invents the syntax.
3. **That its SAS knowledge transfers.** Told only "this is a different
   engine", a model turns cautious and hedges on ordinary SAS. Most programs
   run unchanged, and saying so *first* measurably improves first attempts.
4. **The affordances of this server** — that a run returns every WORK dataset
   with a preview URL, that logs are clipped with `get_run` to fetch the rest,
   that determinism is a flag, and that **WORK does not persist between
   `run_sas` calls**.

Those four are delivered two ways.

**Server instructions**, handed to the model at `initialize` whether or not a
human does anything. This is the only channel that reaches an autonomous
model, so it carries the irreducible core of all four points — including the
one divergence most likely to produce a silently unusable artifact: **Avro,
not SAS7BDAT, is the default storage engine.** It is kept under 2 KB because
it is paid for on every session.

**Prompt templates**, the long forms, for when the detail is actually needed:

| Prompt | What it does |
|--------|--------------|
| `jenner_orientation` | The full briefing: what carries over from SAS, where the docs are, what the tools return. |
| `jenner_beyond_sas` | Getting started with the Jenner-only surface — FSQL, GQL, S3, AI, databases — with a reference for each. Optional `goal`. |
| `port_sas_program` | Adapt an existing SAS program, changing as little as possible and reporting every change. |
| `choose_storage_engine` | Pick between Avro, CSV, Parquet, SAS7BDAT and XPT for a scenario, with the traps for each. |
| `debug_jenner_log` | Diagnose a run log, including the four causes a SAS reading would never suggest. |

Every Jenner-specific claim is verified against the live public API before it
is written down, every documentation URL is checked to resolve, and a test
enforces that nothing advises syntax the deployed engine rejects. If you add a
claim, run it through `run_sas` first.

## Quickstart

The server speaks MCP over stdio. The fastest way to run it is with
[`uv`](https://docs.astral.sh/uv/) (no manual install step — `uvx` fetches and
runs it on demand):

```bash
uvx jenner-sas-mcp
```

Or install it into an environment with pip:

```bash
pip install jenner-sas-mcp
jenner-sas-mcp        # starts the stdio server
```

> Until the package is published to PyPI, install from this repository:
> `uvx --from git+https://github.com/JennerAnalytics/jenner-sas-mcp jenner-sas-mcp`
> or `pip install git+https://github.com/JennerAnalytics/jenner-sas-mcp`.

## Requirements

Python 3.10+ and the `mcp` SDK. **Both mcp 1.x and 2.x are supported** — 2.0
removed `mcp.server.fastmcp` and renamed `FastMCP` to `MCPServer`, so the
package selects the right server class at import time
(`src/jenner_sas_mcp/_compat.py`). CI runs the suite against both majors.

## Configuration

All configuration is via environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `JENNER_API_KEY` | *(none)* | Bearer token. Without it you run as the **Anonymous** tier — shorter timeouts, lower observation caps, stricter rate limits. Provide a key for higher limits. |
| `JENNER_API_URL` | `https://api.jenneranalytics.com` | Override to point at a self-hosted gateway or a local dev instance (`http://127.0.0.1:3000`). |
| `JENNER_MAX_LOG_CHARS` | `40000` | Per-field cap (log/listing) returned to the model, to protect the context window. The full artifacts stay retrievable via `get_run`. |

## Connect a client

### Claude Desktop

Edit your `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`) and add:

```json
{
  "mcpServers": {
    "jenner-sas": {
      "command": "uvx",
      "args": ["jenner-sas-mcp"],
      "env": {
        "JENNER_API_KEY": "your-api-key-optional"
      }
    }
  }
}
```

Restart Claude Desktop. The `jenner-sas` tools appear in the tools menu.
(A copy of this config lives in [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json).)

### Claude Code

```bash
claude mcp add jenner-sas --env JENNER_API_KEY=your-key -- uvx jenner-sas-mcp
```

Or, for a project-scoped server checked into the repo, add it to `.mcp.json`:

```json
{
  "mcpServers": {
    "jenner-sas": { "command": "uvx", "args": ["jenner-sas-mcp"] }
  }
}
```

### Any other MCP client

Launch `uvx jenner-sas-mcp` (or `jenner-sas-mcp`) as a stdio server. Pass the
environment variables above through your client's server configuration.

## Try it

Once connected, ask the model things like:

- *"Run this SAS program and show me the means: `proc means data=sashelp.class; var height weight; run;`"*
- *"Validate this program before we run it, then fix any errors."*
- *"Simulate 1000 draws from a normal, summarize them, and don't make it deterministic."*
- *"Run my regression and preview the `outstat` dataset."*

A minimal first call the model makes under the hood:

```python
run_sas(script="data a; x=1; output; run; proc print data=a; run;")
# -> { "ok": true, "exit_code": 0, "log": "...", "listing": "Obs  x\n 1   1",
#      "datasets": [{ "name": "a", "rows": 1, "columns": ["x"], ... }], ... }
```

## How results come back

`run_sas` returns a compact, model-friendly summary of the
[run-result JSON](https://api.jenneranalytics.com):

- `ok` / `exit_code` — `exit_code` is the SAS severity (0 clean, 1 warnings
  but still ok, ≥2 error); `ok` is the boolean `exit_code < 2`.
- `log` — the SAS log (the first place to read errors and `NOTE:`/`WARNING:`
  lines). Clipped head+tail if very large; use `get_run` for the full text.
- `listing` — printed/stdout output (e.g. PROC PRINT, PROC MEANS tables).
- `datasets` — each WORK dataset's `name`, `rows`, `columns`, and a
  `preview_url`/`download_url`.
- `files` — output artifacts (PNG/SVG/CSV/…) with a download `url`.
- `diagnostics` — parse and runtime warnings.
- `run_id` + `access_token` — pass these to `get_run` / `dataset_preview` to
  retrieve full artifacts later.

Determinism is **on by default**: the RNG is seeded and `today()`/`datetime()`
are frozen so the same program yields identical output. Set
`deterministic=false` for genuine randomness.

## Requirements

Python 3.10+ and the `mcp` SDK. **Both mcp 1.x and 2.x are supported** — 2.0
removed `mcp.server.fastmcp` and renamed `FastMCP` to `MCPServer`, so the
package selects the right server class at import time and CI runs the suite
against both majors.

## Development

```bash
git clone https://github.com/JennerAnalytics/jenner-sas-mcp
cd jenner-sas-mcp
uv sync --extra dev          # or: pip install -e ".[dev]"
pytest                       # unit tests (no network)
```

To reproduce a specific major locally:

```bash
uv pip install "mcp[cli]<2"   # or ">=2"
pytest -q
```

Run the server against a local gateway:

```bash
JENNER_API_URL=http://127.0.0.1:3000 uv run jenner-sas-mcp
```

Inspect the tools interactively with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector uvx jenner-sas-mcp
```

## License

Apache-2.0 — see [LICENSE](LICENSE).

---

SAS and all other SAS Institute Inc. product or service names are registered
trademarks or trademarks of SAS Institute Inc. in the USA and other countries.
® indicates USA registration. Jenner is not affiliated with or endorsed by SAS
Institute Inc.
