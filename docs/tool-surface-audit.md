# Tool surface: audit against the SAS Viya MCP server

An audit of [`sassoftware/sas-mcp-server`](https://github.com/sassoftware/sas-mcp-server)
(69 tools, 10 modules) against what the Jenner engine and platform can actually
back today, and a proposal for which tools are worth building here.

Written 2026-08-04 against `sas-mcp-server` @ 2026-08-03 and `jenner-language` @ dev.

Every "Jenner has this" claim below was verified against the source or by running
it, not inferred from documentation. Where something was checked by execution the
evidence is quoted.

---

## The shape of the difference

SAS Viya is a constellation of separately-addressed services — Compute, CAS, Job
Execution, Information Catalog, Model Manager, Intelligent Decisioning, Visual
Analytics. Each has its own REST API, so the MCP server needs a distinct tool per
door. That is why there are 69 of them, and 19 in discovery alone.

Jenner is one engine. A model that can execute SAS reaches most of that surface by
*writing SAS*, with no tool required:

```sas
proc sql; select libname, memname, nobs, nvar from dictionary.tables; quit;
```

Verified live — `DICTIONARY.TABLES` and `DICTIONARY.COLUMNS` both return rows
through `run_sas` today. So `list_compute_libraries`, `list_compute_tables` and
`list_compute_columns` are already reachable without adding a tool.

**This is the central design point.** Tool count is a proxy for how fragmented the
backend is, not for how much the model can do. Adding 19 discovery tools to wrap
queries the model can already write would spend context budget to buy nothing.

A discrete tool earns its place only when one of these holds:

1. **It cannot be expressed in SAS.** File upload/download, run retrieval, quota.
2. **It needs out-of-band state.** Async job control, session lifecycle.
3. **It is high-frequency enough that the round trip matters.** Schema
   introspection during iterative code generation.
4. **It encodes a policy the model should not have to know.** Tier limits,
   deterministic execution.

---

## Audit: all 69, by whether Jenner can back them

### Backed today — reachable with existing engine/platform capability (28)

| Their tool | What backs it in Jenner |
|---|---|
| `execute_sas_code` (compute) | `POST /v1/run` — already shipped as `run_sas` |
| `execute_sas_code` (workbench) | same |
| `list_compute_libraries` | `DICTIONARY.TABLES` / `VLIBNAM` — **verified live** |
| `list_compute_tables` | `DICTIONARY.TABLES` — **verified live**, returns libname/memname/nobs/nvar |
| `list_compute_columns` | `DICTIONARY.COLUMNS` — **verified live**, returns name/type/length |
| `list_cas_servers` | `MYCAS` MemoryEngine (`src/runtime/library.rs`) |
| `list_caslibs` | MEMORY-engine librefs |
| `list_castables` | `PROC DATASETS` listing on a MEMORY libref |
| `get_castable_info` | `PROC CONTENTS` (obs/vars/engine/physical name) |
| `get_castable_columns` | `PROC CONTENTS` / `DICTIONARY.COLUMNS` |
| `get_castable_data` | `GET /v1/run/:run_id/datasets/:name` — already shipped as `dataset_preview` |
| `list_source_tables` | `PROC DATASETS` on a file libref |
| `promote_table_to_memory` | `libname x memory;` + a DATA step copy |
| `list_files` | `GET /api/workspaces/{id}/files` |
| `upload_file` | `POST /api/workspaces/{id}/files/upload` |
| `download_file` | `GET /api/workspaces/{id}/files/download` |
| `upload_data` | `/v1/run` multipart already accepts input files alongside the script |
| `upload_inline_data` | a DATA step with `DATALINES`, or `/v1/quick` |
| `list_reports` | workspace files (ODS output lands there) |
| `get_report` | same |
| `export_report` | ODS emits HTML, PDF, RTF, EXCEL, POWERPOINT, MARKDOWN, CSVALL |
| `list_compute_contexts` | `/api/workspaces` |
| `reset_compute_session` | `/api/workspaces/{id}/launch` + `/heartbeat` |
| `catalog_download_table_profile` | `PROC CONTENTS` + `PROC MEANS`/`PROC FREQ` |
| `catalog_search` | `DICTIONARY.TABLES` with a `WHERE` |
| `catalog_search_helper` | same |
| `catalog_find_instance` | same |
| `score_data` | `PROC SCORE` (`src/runtime/procs/score.rs`), `PROC ASTORE`, `PROC PLM` |

### Buildable, but needs real work (11)

| Their tool | Missing piece |
|---|---|
| `submit_batch_job` | The Run API is synchronous (`/v1/run`, `/v1/quick`). Async needs a job model — submit returns an id, poll for completion. `/v1/run/stream` is the closest existing thing. |
| `get_job_status` | ditto |
| `list_jobs` | ditto — plus per-caller job history |
| `cancel_job` | ditto — plus cancellation in the sandbox |
| `get_job_log` | `GET /v1/run/:run_id` already returns the log; needs the job id mapping |
| `list_ml_projects` | Jenner has the algorithms (`forest`, `hpforest`, `hpsplit`, `glmselect`, `nnet`, `svmachine`) but no "project" abstraction |
| `create_ml_project` | ditto |
| `run_ml_project` | ditto |
| `catalog_run_agent` | needs a profiling/agent runner |
| `catalog_get_agent_history` | ditto |
| `catalog_run_adhoc_analysis` / `catalog_get_adhoc_analysis` | ditto |

### Belongs to a different SAS product — not ours to match (27)

**Decisioning (22)** — SAS Intelligent Decisioning: business rulesets, rules,
decision flows, revision locking, DS2 code generation, MAS publishing. A separate
licensed product. Jenner has no analog and should not grow one to match a tool count.

**Model Manager (5)** — `list_registered_models`, `list_publishing_destinations`,
`list_mas_modules`, `get_mas_module_step_signature`, and the registry half of
`register_ml_champion_model` / `publish_ml_champion_model`. Jenner can *score*
(PROC SCORE / ASTORE / PLM) but has no model registry or publishing destinations.

---

## Proposal: the tools worth building

Fourteen, in three waves. The test each one passes is the four-part rule above —
not "SAS has one."

### Wave 1 — close the genuine gaps (6)

These cannot be expressed in SAS. They are the real holes in the current server.

| Tool | Why it can't be SAS | Backing |
|---|---|---|
| `upload_file` | The model cannot put bytes on the server by writing SAS | `/v1/run` multipart; `/api/workspaces/{id}/files/upload` |
| `download_file` | Retrieving an artifact is out-of-band | `/v1/run/:run_id/datasets/:name/download` |
| `list_run_files` | Discovering what a run produced | `/v1/run/:run_id` |
| `get_quota` | Tier limits are policy the model should not guess at | `GET /v1/quota` |
| `list_workspaces` | Platform state, not engine state | `/api/workspaces` |
| `workspace_files` | Persistent storage across runs | `/api/workspaces/{id}/files` |

### Wave 2 — async execution (4)

Requires a job model on the Run API. Worth it: the current 60s synchronous
default makes long analyses impossible, which is a capability gap rather than a
tool gap.

`submit_job`, `get_job_status`, `get_job_log`, `cancel_job`

### Wave 3 — schema introspection (2)

Technically expressible in SAS, but earns a tool under rule 3: a model writing a
join asks "what columns does this have?" constantly, and a round trip through
`run_sas` costs a full sandbox execution each time.

| Tool | Note |
|---|---|
| `describe_dataset` | columns, types, lengths, formats, labels, nobs — one call |
| `list_datasets` | what exists in a run's WORK, or a workspace library |

### Deliberately not building (2 categories)

**Discovery-as-tools.** The 19-tool discovery module is Viya's service
fragmentation showing through. `DICTIONARY.TABLES` reaches it in one query.
Wave 3 adds two tools for the high-frequency cases and stops there.

**Decisioning and Model Manager.** Different products. If Jenner ever grows a
model registry, `score_data` becomes worth exposing as a tool rather than a
`PROC SCORE` snippet — until then it is not.

---

## Two things to steal outright

Independent of tool count, both are cheap and both are things the SAS server does
better today:

**Prompt templates.** They ship 8 `@mcp.prompt` templates; we ship none. Prompts
that teach a model Jenner's actual idioms would raise first-try code quality more
than any tool would — particularly the places Jenner diverges from SAS:

- Avro is the default storage engine, not SAS7BDAT
- `LIBNAME` engine keywords (`avro`, `csv`, `parquet`, `sas7bdat`, `xport`)
- working end to end in SAS7BDAT vs. using it only at the boundaries
- `PROC FSQL` / `PROC GQL` / `PROC S3`, which have no SAS equivalent

**Tool tiering.** `MCP_TIERS=0-4` lets a caller expose a subset. Unnecessary at 4
tools; necessary at 18. Worth adding when Wave 2 lands, not before.

---

## Summary

| | Count |
|---|---|
| Their tools | 69 |
| Backed by Jenner today | 28 |
| Buildable with real work | 11 |
| Different SAS product | 27 |
| **Proposed for Jenner** | **14** (4 existing + 10 new) |

The gap is not capability. It is that Viya needs a tool per service and Jenner
does not — so the useful target is ~18 tools total, not 69, and the work that
actually moves the needle is Wave 1 plus prompt templates.
