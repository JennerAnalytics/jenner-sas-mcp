# Jenner SAS MCP Server

Run and validate **SAS** from any [Model Context Protocol](https://modelcontextprotocol.io)
client — Claude Desktop, Claude Code, Cursor, and others — without a SAS
licence. This server wraps the public Jenner run API
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

- *"Run this SAS and show me the means: `proc means data=sashelp.class; var height weight; run;`"*
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

## Development

```bash
git clone https://github.com/JennerAnalytics/jenner-sas-mcp
cd jenner-sas-mcp
uv sync --extra dev          # or: pip install -e ".[dev]"
pytest                       # unit tests (no network)
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
