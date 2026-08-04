"""Prompt templates for the Jenner MCP server.

Registered via ``register_prompts(mcp)`` on the server instance.

These exist because a model asked to "write some SAS" writes *SAS*, and Jenner
deliberately diverges from SAS in a few places that silently produce wrong or
non-running code. The most valuable thing a prompt can do here is state those
divergences up front, so the first attempt is right instead of the third.

Every Jenner-specific claim in these templates was checked against the live
public API (``https://api.jenneranalytics.com``) before being written down.
Notably, two things are NOT taught here because they are not yet live there:

* ``libname x avro "dir";`` — naming the Avro engine explicitly. Avro is the
  default, so the templates get it by NOT naming an engine, which works today.
* a quoted ``"file.sas7bdat"`` in a ``PROC SQL`` FROM clause — the templates
  teach the ``LIBNAME`` form, which works today.

If you add a claim here, run it through ``run_sas`` first.
"""

from __future__ import annotations

from ._compat import Server

__all__ = ["register_prompts", "JENNER_DIFFERENCES"]


# The orientation block. Shared by several templates rather than restated, so
# there is one place to correct when the engine changes.
JENNER_DIFFERENCES = """\
Jenner runs standard SAS — DATA steps, PROCs, macros, SQL — without a SAS
licence. Most SAS code runs unchanged. The differences that actually change
what you should write:

STORAGE ENGINES (the one most likely to bite)
  SAS has exactly one dataset format: every permanent dataset is a .sas7bdat.
  Jenner has several, and its DEFAULT is Avro, not SAS7BDAT.

  * WORK, and any library declared without an engine keyword, store Avro.
    You get this by writing nothing special:
        libname mylib "data";        /* members are .avro */
  * SAS7BDAT is fully supported for BOTH reading and writing. It is one
    engine among several rather than the only one:
        libname saslib sas7bdat "sasdata";
        data saslib.adlb; set saslib.raw; run;   /* real .sas7bdat files */
        data "out.sas7bdat"; set work.x; run;    /* a quoted path works too */
  * Other engines: csv, parquet, xport. One engine per library.
  * A step reads whatever its input is and writes whatever its output path
    says, so changing format means changing where you write — no conversion
    step.
  * In PROC SQL, use a LIBNAME for a SAS7BDAT source rather than a quoted
    path.

  Which to use: leave it alone (Avro) for intermediate work — it is faster
  and preserves column types across steps, which CSV does not. Use sas7bdat
  when a SAS user or SAS-based system is on the other end. Use parquet to
  hand off to Python/R. Use xport for FDA/EMA submission.

NUMERIC TYPES
  SAS stores every numeric as an 8-byte double. Jenner distinguishes integers
  from floats, so 5+3 is the integer 8 and 10/3 is a float. This preserves
  IDs above 2^53 exactly, where SAS silently rounds.

VARIABLE NAME CASE IN OUTPUT
  Names are case-insensitive. How a name APPEARS is driven by labels: most
  procs show the case you wrote, PROC PRINT shows uppercase unless you add
  the LABEL option.

NOT IN SAS AT ALL
  PROC FSQL   federated SQL across files, databases and object stores in one
              query
  PROC GQL    graph queries over connected data
  PROC S3     object-store operations
  PROC AI     LLM-powered data processing
  Native CSV/Parquet/Avro I/O and 14 database LIBNAME engines.

NOT IMPLEMENTED
  SAS/SCL and SAS/AF."""


_RUN_ADVICE = """\
Run it with the `run_sas` tool and read the returned `log` — that is where
Jenner reports NOTEs, WARNINGs and ERRORs, exactly as SAS does. `exit_code`
is the SAS severity (0 = clean, >=2 = error) and `diagnostics` separates
parse errors from runtime errors. If you only want a syntax check without
executing, use `validate_sas` first — it is faster and cannot have side
effects."""


def register_prompts(mcp: Server) -> None:
    """Register every prompt template on *mcp*."""

    @mcp.prompt()
    def jenner_vs_sas() -> str:
        """Explain how Jenner differs from SAS before writing or porting code."""
        return (
            "Before writing or changing any code for the Jenner engine, take "
            "account of the following. Do not assume SAS defaults where Jenner "
            "differs.\n\n"
            f"{JENNER_DIFFERENCES}\n\n"
            "Summarise, for the task at hand, which of these differences apply "
            "and what you will do differently because of them."
        )

    @mcp.prompt()
    def write_jenner_program(task: str, storage_format: str | None = None) -> str:
        """Write a Jenner/SAS program for a task, respecting Jenner's defaults."""
        fmt = (
            f"\nStore datasets as {storage_format}. Declare a LIBNAME with that "
            f"engine rather than relying on the default.\n"
            if storage_format
            else "\nUnless the task calls for a specific format, leave storage "
            "alone — WORK defaults to Avro, which is the right choice for "
            "intermediate work.\n"
        )
        return (
            f"Write a program for the Jenner engine that does the following:\n\n"
            f"{task}\n"
            f"{fmt}\n"
            f"{JENNER_DIFFERENCES}\n\n"
            "Write the program, then run it and confirm it produced what the "
            f"task asked for.\n\n{_RUN_ADVICE}"
        )

    @mcp.prompt()
    def port_sas_program(sas_code: str) -> str:
        """Adapt an existing SAS program to run on Jenner, flagging what changes."""
        return (
            "Adapt the following SAS program to run on the Jenner engine.\n\n"
            "Most SAS runs unchanged, so change as little as possible. Report "
            "every change you make and why. If the program relies on something "
            "Jenner does not implement, say so plainly rather than silently "
            "substituting.\n\n"
            "Pay particular attention to anything that assumes a dataset is a "
            ".sas7bdat on disk, since Jenner's default is Avro — if the program "
            "hands files to a SAS user or another SAS system, declare a "
            "sas7bdat LIBNAME so the outputs stay .sas7bdat.\n\n"
            f"```sas\n{sas_code}\n```\n\n"
            f"{JENNER_DIFFERENCES}\n\n"
            f"{_RUN_ADVICE}"
        )

    @mcp.prompt()
    def debug_jenner_log(log_text: str, severity: str | None = None) -> str:
        """Diagnose a Jenner run log: root cause and the smallest fix."""
        focus = (
            f"\nFocus on {severity}-level messages.\n" if severity else ""
        )
        return (
            "Diagnose this Jenner run log.\n"
            f"{focus}\n"
            "For each problem: quote the line, give the ROOT cause rather than "
            "restating the message, and give the smallest change that fixes it.\n\n"
            "Log conventions are SAS's: NOTE is informational, WARNING means the "
            "step ran with a caveat, ERROR means it did not do what was asked. "
            "A step can log a NOTE and still be wrong — check that row and column "
            "counts match what the program intended.\n\n"
            "Two Jenner-specific things worth checking:\n"
            "  * 'Dataset not found' where a libref is involved often means the "
            "    library's engine and the file on disk disagree — a library has "
            "    ONE engine and every member uses it.\n"
            "  * a numeric column read back as text usually means it round-tripped "
            "    through CSV, which does not preserve types. Avro, Parquet and "
            "    SAS7BDAT do.\n\n"
            f"```\n{log_text}\n```"
        )

    @mcp.prompt()
    def choose_storage_engine(scenario: str) -> str:
        """Pick the right Jenner storage engine for a scenario, with the tradeoffs."""
        return (
            f"Recommend a storage engine for this scenario:\n\n{scenario}\n\n"
            "Choose from Avro (the default), CSV, Parquet, SAS7BDAT and XPT, and "
            "justify the choice against these properties:\n\n"
            "| Engine   | Types preserved | Read by SAS | Typical use |\n"
            "|----------|-----------------|-------------|-------------|\n"
            "| Avro     | yes             | no          | default; intermediate work |\n"
            "| CSV      | NO              | yes         | exchange, eyeballing |\n"
            "| Parquet  | yes             | no          | handoff to Python/R, archival |\n"
            "| SAS7BDAT | yes             | yes         | SAS interop, end-to-end SAS work |\n"
            "| XPT      | partial         | yes         | FDA/EMA submission |\n\n"
            "Then show the LIBNAME (or quoted path) that selects it, and name the "
            "one thing most likely to go wrong with that choice.\n\n"
            "Watch for: CSV loses types, so a numeric column comes back as text; "
            "Parquet libraries return columns alphabetically rather than in the "
            "order written; SPSS (.sav) and Stata (.dta) are read-only."
        )

    @mcp.prompt()
    def explore_dataset(dataset: str, focus: str | None = None) -> str:
        """Profile a dataset: structure first, then distributions."""
        extra = f"\nConcentrate on: {focus}.\n" if focus else ""
        return (
            f"Profile the dataset `{dataset}` on the Jenner engine.\n"
            f"{extra}\n"
            "Work in two passes, and read the output of the first before writing "
            "the second — the structure determines which summaries make sense.\n\n"
            "1. Structure: PROC CONTENTS for the variable list, types, lengths "
            "and formats. Note that variables list alphabetically by default; add "
            "VARNUM for creation order.\n"
            "2. Distributions: PROC MEANS for the numerics, PROC FREQ for the "
            "categoricals, PROC UNIVARIATE where a fuller picture is warranted.\n\n"
            "You can also query the dictionary views directly, which is often "
            "quicker than a PROC for a structural question:\n"
            "```sas\n"
            "proc sql;\n"
            "    select libname, memname, nobs, nvar from dictionary.tables;\n"
            "    select name, type, length from dictionary.columns\n"
            "        where memname = 'YOURTABLE';\n"
            "quit;\n"
            "```\n\n"
            "Report what the data actually shows — missingness, unexpected "
            "cardinality, values outside a plausible range — not just the "
            f"statistics.\n\n{_RUN_ADVICE}"
        )

    @mcp.prompt()
    def federated_query(sources: str, question: str) -> str:
        """Query across files, databases and object stores — Jenner-only capability."""
        return (
            f"Answer this question:\n\n{question}\n\nfrom these sources:\n\n"
            f"{sources}\n\n"
            "This is something Jenner does and SAS does not, so do not reach for "
            "a SAS idiom here.\n\n"
            "Options, in rough order of preference:\n"
            "  * PROC SQL joining across LIBNAMEs of different engines. A join "
            "    whose sides are different formats is fine — declare a LIBNAME "
            "    per source and join them.\n"
            "  * PROC FSQL for federated SQL spanning files, databases and object "
            "    stores in a single query.\n"
            "  * PROC S3 for object-store operations.\n"
            "  * PROC GQL for graph-shaped questions.\n\n"
            "Jenner speaks 14 database engines through LIBNAME (PostgreSQL, "
            "MySQL, SQLite, SQL Server, Oracle, DB2, DuckDB, Snowflake, Redshift, "
            "BigQuery, Databricks, ClickHouse, ODBC, and an in-memory engine), "
            "plus live data APIs (FRED, World Bank, NOAA, OECD, EODData).\n\n"
            "Show the LIBNAME statements and the query, and say which engine each "
            f"source resolves to.\n\n{_RUN_ADVICE}"
        )

    @mcp.prompt()
    def review_jenner_program(sas_code: str, focus: str | None = None) -> str:
        """Review a Jenner program for correctness first, then performance."""
        lens = focus or "correctness first, then performance and clarity"
        return (
            f"Review the following Jenner program. Focus on: {lens}.\n\n"
            f"```sas\n{sas_code}\n```\n\n"
            "Lead with anything that makes it WRONG, before anything that makes "
            "it slow. A program that runs clean and produces the wrong number is "
            "the worse failure.\n\n"
            "Jenner-specific things worth checking:\n"
            "  * Round-tripping data through CSV between steps — types are lost, "
            "    and a downstream statistical proc may refuse a column that came "
            "    back as text. Avro (the default) keeps them.\n"
            "  * Naming an engine on a library whose members do not need it. "
            "    Leaving it off gets Avro, which is usually right.\n"
            "  * Relying on column ORDER from a Parquet library — it returns "
            "    columns alphabetically. Name them in KEEP= or SELECT.\n"
            "  * A DATA step writing several datasets at once (`data a b;`) where "
            "    one leg is SAS7BDAT — split it into separate steps.\n"
            "  * Integer vs float: Jenner keeps integers exact, so an ID above "
            "    2^53 survives here where it would round in SAS. Do not add "
            "    workarounds for SAS's rounding.\n\n"
            "For each finding give the line, why it matters, and the fix."
        )
