"""Prompt templates for the Jenner MCP server.

Registered via ``register_prompts(mcp)`` on the server instance.

WHAT BELONGS HERE
-----------------
A prompt earns its place only if it tells the model something it does not
already know, or is bad at. The model already knows how to write SAS, profile a
dataset and read a log — templates for those are padding, and were removed.

Four things the model genuinely cannot know, which is what these carry:

1. Where to learn more about how Jenner differs. It has no idea
   docs.jenneranalytics.com exists.
2. How to get started with what Jenner has and SAS does not — PROC FSQL, GQL,
   S3, AI, native database LIBNAMEs. No training data covers these.
3. That its SAS knowledge transfers directly. Told only "this is a different
   engine", a model turns cautious, hedges, and invents non-existent
   Jenner-specific syntax. Most SAS runs unchanged; say so FIRST.
4. The affordances of the system it is talking to — that a run returns datasets
   with preview URLs and files, that logs are clipped with a way to fetch the
   rest, that there is a cheap parse-only check, that determinism is a flag,
   that WORK does not survive between calls.

ACCURACY
--------
Every Jenner-specific claim was run against the live public API before being
written down, and every URL was checked to resolve. Two constructs are
deliberately NOT taught because the deployed engine still rejects them, even
though both have landed on dev:

* ``libname x avro "dir";`` — naming the Avro engine explicitly. Avro is the
  default, so the templates get it by NOT naming an engine, which works today.
* a quoted ``"file.sas7bdat"`` in a ``PROC SQL`` FROM clause — the templates
  teach the ``LIBNAME`` form, which works today.

``test_no_unreleased_features_taught`` enforces that. If you add a claim, run
it through ``run_sas`` first and check any URL you cite still resolves.
"""

from __future__ import annotations

from ._compat import Server

__all__ = [
    "register_prompts",
    "SERVER_INSTRUCTIONS",
    "JENNER_ORIENTATION",
    "JENNER_AFFORDANCES",
    "DOCS",
]


DOCS = "https://docs.jenneranalytics.com"


# Ordering is deliberate: point 3 (your SAS works), then 1 (where to look),
# then the deltas. A model that meets a list of differences before it is told
# its existing knowledge applies becomes hesitant and over-adapts.
# All URLs verified live 2026-08-04.
JENNER_ORIENTATION = f"""\
YOUR SAS KNOWLEDGE APPLIES. Jenner runs standard SAS — DATA steps, PROCs,
macros, SQL — without a SAS licence. Write the SAS you would normally write.
Most programs run unchanged, so do not hedge, do not ask whether an ordinary
SAS construct is supported, and do not invent Jenner-specific syntax. Write the
SAS, run it, read the log.

WHERE TO LOOK THINGS UP
  {DOCS}                                  full documentation
  {DOCS}/getting-started/                  start here
  {DOCS}/getting-started/sas-differences/  every divergence from SAS
  {DOCS}/language/                         language and PROC reference
  {DOCS}/language/file-formats/            storage engines in depth
  {DOCS}/data-access/                      files, databases, object stores

THE DIFFERENCES THAT CHANGE WHAT YOU WRITE

  Storage engines — the one most likely to bite.
    SAS has exactly one dataset format: every permanent dataset is a
    .sas7bdat. Jenner has several, and its DEFAULT is Avro, not SAS7BDAT.
    SAS7BDAT is fully supported for both reading and writing; it is one engine
    among several rather than the only one.

        libname mylib "data";               /* no engine named => Avro */
        libname saslib sas7bdat "sasdata";  /* real .sas7bdat members  */
        data "out.sas7bdat"; set work.x; run;

    Leave it alone (Avro) for intermediate work — faster, and it preserves
    column types across steps where CSV does not. Name sas7bdat when a SAS user
    or SAS system is on the other end; parquet to hand off to Python/R; xport
    for FDA/EMA submission. One engine per library.
    Detail: {DOCS}/getting-started/sas-differences/#storage-engines

  Numeric types.
    SAS stores every numeric as an 8-byte double. Jenner distinguishes integers
    from floats, so 5+3 is the integer 8 while 10/3 is a float. IDs above 2^53
    stay exact here where SAS silently rounds — do not add workarounds for
    rounding that will not happen.

  Variable name case in output.
    Names are case-insensitive. How a name APPEARS is driven by labels: most
    procs show the case you wrote; PROC PRINT shows uppercase unless you add
    the LABEL option.

  Not implemented: SAS/SCL and SAS/AF."""


# Point 4. The model cannot introspect a tool result it has not received yet,
# so the shape of a run is worth stating before it runs anything.
JENNER_AFFORDANCES = """\
WHAT THIS SYSTEM GIVES YOU

  run_sas(script, deterministic=True, timeout=None, max_obs=None)
      Executes the program in a sandbox and returns, in one response:
        log          the SAS log — NOTEs, WARNINGs, ERRORs. Read this first.
        exit_code    SAS severity: 0 clean, >=2 error
        listing      printed output (PROC PRINT, PROC MEANS, ...)
        datasets     every WORK dataset with row count, column names and a
                     preview_url — you do not need a PROC PRINT to see what
                     the program produced
        files        artifacts written: PNG, SVG, CSV, with URLs
        diagnostics  parse errors kept separate from runtime errors
        run_id + access_token   for fetching more later
      `deterministic` (on by default) seeds the RNG and freezes today() and
      datetime(), so repeated runs match. Turn it off for genuine simulation.

  validate_sas(script)
      Parse-check without executing. Fast, no side effects. Worth running on
      generated code before something expensive or destructive.

  get_run(run_id, access_token)
      The full, unclipped log and listing. run_sas clips large ones to protect
      the context window; come here when you need all of it.

  dataset_preview(run_id, name, access_token)
      Rows of a WORK dataset a run produced.

  Consequences worth holding on to:
    * The log is the primary diagnostic surface, exactly as in SAS.
    * A step can log a NOTE and still be wrong. Check row and column counts
      against what the program intended.
    * Each run is a fresh sandbox. WORK does NOT persist between run_sas
      calls — everything a program needs must be in that one program.
    * Anonymous callers get shorter timeouts and lower observation caps than
      authenticated ones. A truncated or timed-out run may be tier policy
      rather than a defect in the program."""


# Server instructions are the only channel the model is guaranteed to see:
# the spec hands them over at initialize, unprompted. Most clients surface
# @mcp.prompt templates as user-invoked slash commands, so a model working
# autonomously never reads one. This therefore carries the irreducible core of
# all four points, and names the prompts for the long forms.
#
# It is deliberately short. Instructions are paid for on every session, so
# anything that can wait until the model actually needs it waits in a prompt.
SERVER_INSTRUCTIONS = f"""\
Jenner runs standard SAS — DATA steps, PROCs, macros, SQL — without a SAS
licence. Write the SAS you already know; most programs run unchanged. Do not
hedge about ordinary SAS support, and do not invent Jenner-specific syntax.

Four things worth knowing before you write:

1. Storage engines. SAS has one dataset format; Jenner has several and its
   DEFAULT is Avro, not SAS7BDAT. SAS7BDAT is fully supported for read and
   write, but you must ask for it — `libname saslib sas7bdat "dir";` — or
   outputs land as .avro, which SAS cannot open. Also: CSV does not preserve
   column types. Use the `choose_storage_engine` prompt when it matters.

2. Numerics are typed. Integers stay integers, so IDs beyond 2^53 are exact
   where SAS rounds. SAS/SCL and SAS/AF are not implemented.

3. Jenner has procs SAS does not: PROC FSQL (federated SQL across files,
   databases and object stores), PROC GQL (graph), PROC S3, PROC AI, and
   native LIBNAME engines for 14 databases. Do not guess their syntax — see
   the `jenner_beyond_sas` prompt or {DOCS}/data-access/.

4. Each run_sas call is a FRESH sandbox: WORK does not persist between calls,
   so a program must be self-contained. run_sas returns the log, listing, and
   every WORK dataset with row/column counts — you rarely need a PROC PRINT to
   see what a program produced. validate_sas parse-checks without executing.

Docs: {DOCS} — divergences at {DOCS}/getting-started/sas-differences/."""


def register_prompts(mcp: Server) -> None:
    """Register every prompt template on *mcp*."""

    @mcp.prompt()
    def jenner_orientation() -> str:
        """Start here: what carries over from SAS, where the docs are, what the tools return."""
        return (
            f"{JENNER_ORIENTATION}\n\n{JENNER_AFFORDANCES}\n\n"
            "Take this as read and continue with the user's task. Do not "
            "recite it back unless they asked what Jenner is."
        )

    @mcp.prompt()
    def jenner_beyond_sas(goal: str | None = None) -> str:
        """Get started with what Jenner has and SAS does not — FSQL, GQL, S3, AI, databases."""
        aim = (
            f"\nThe user wants to: {goal}\nPick whichever fits and show working "
            "code for it.\n"
            if goal
            else "\nShow a short working example of each so the user can see "
            "what is on offer.\n"
        )
        return (
            "These exist in Jenner and have no SAS equivalent, so you will not "
            "have met them in SAS material. Do not guess the syntax — a "
            "reference is linked for each.\n"
            f"{aim}\n"
            "  PROC SQL across engines\n"
            "      A join whose sides are different formats is fine. Declare a\n"
            "      LIBNAME per source and join them:\n\n"
            '          libname saslib sas7bdat "sasdata";\n'
            '          libname pqlib  parquet  "archive";\n'
            "          proc sql;\n"
            "              create table work.j as\n"
            "              select a.id, b.site from saslib.adlb a\n"
            "              left join pqlib.sites b on a.id = b.id;\n"
            "          quit;\n\n"
            f"      {DOCS}/language/proc-sql/\n\n"
            "  PROC FSQL — federated SQL spanning files, databases and object\n"
            "      stores in ONE query.\n"
            f"      {DOCS}/language/proc-fsql/\n\n"
            "  PROC GQL — graph queries over connected data.\n"
            f"      {DOCS}/language/proc-gql/\n\n"
            "  PROC S3 — object-store operations against S3 and compatibles.\n"
            f"      {DOCS}/language/proc-s3/\n\n"
            "  PROC AI — LLM-powered data processing inside the DATA step.\n\n"
            "  Database LIBNAMEs — 14 engines, read and write, addressed like\n"
            "      any other library: PostgreSQL, MySQL, SQLite, SQL Server,\n"
            "      Oracle, DB2, DuckDB, Snowflake, Redshift, BigQuery,\n"
            "      Databricks, ClickHouse, ODBC, and an in-memory engine. Plus\n"
            "      live data APIs: FRED, World Bank, NOAA, OECD, EODData.\n"
            f"      {DOCS}/data-access/\n\n"
            "  Native CSV / Parquet / Avro / SAS7BDAT / XPT I/O is built in.\n"
            "      No PROC IMPORT dance: the file extension, or the LIBNAME\n"
            "      engine, selects the format.\n"
            f"      {DOCS}/language/file-formats/\n\n"
            f"{JENNER_AFFORDANCES}"
        )

    @mcp.prompt()
    def port_sas_program(sas_code: str) -> str:
        """Adapt an existing SAS program to Jenner, changing as little as possible."""
        return (
            "Adapt this SAS program to run on Jenner.\n\n"
            "Start from the assumption that it already works. Most SAS runs "
            "unchanged, so change as little as possible and report every change "
            "with a reason. If something genuinely is not implemented, say so "
            "plainly rather than silently substituting.\n\n"
            "The change most often needed is storage. If this program hands "
            "files to a SAS user or another SAS system, declare a sas7bdat "
            "LIBNAME so its outputs stay .sas7bdat — Jenner defaults to Avro, "
            "so leaving it implicit produces .avro files SAS cannot read.\n\n"
            f"```sas\n{sas_code}\n```\n\n"
            f"{JENNER_ORIENTATION}\n\n"
            "Then run it with run_sas and confirm from the log that it did what "
            "the original did."
        )

    @mcp.prompt()
    def choose_storage_engine(scenario: str) -> str:
        """Pick a storage engine — the divergence most likely to yield an unusable artifact."""
        return (
            f"Recommend a storage engine for this scenario:\n\n{scenario}\n\n"
            "This question does not arise in SAS, which has one format. Jenner "
            "has several and defaults to Avro rather than SAS7BDAT, so choosing "
            "wrong produces a program that runs clean and hands over an "
            "artifact the recipient cannot open.\n\n"
            "| Engine   | Types kept | SAS can read it | Use when |\n"
            "|----------|-----------|-----------------|----------|\n"
            "| Avro     | yes       | no              | default; intermediate work |\n"
            "| CSV      | NO        | yes             | exchange, eyeballing |\n"
            "| Parquet  | yes       | no              | handoff to Python/R, archival |\n"
            "| SAS7BDAT | yes       | yes             | SAS interop, end-to-end SAS work |\n"
            "| XPT      | partial   | yes             | FDA/EMA submission |\n\n"
            "Give the LIBNAME (or quoted path) that selects it, and name the one "
            "thing most likely to go wrong with that choice.\n\n"
            "Known traps: CSV loses types, so a numeric column returns as text "
            "and a statistical proc may refuse it. Parquet libraries return "
            "columns alphabetically rather than in written order — name them in "
            "KEEP= or SELECT when order matters. SPSS (.sav) and Stata (.dta) "
            "are read-only. A DATA step writing several datasets at once "
            "(`data a b;`) is not supported when one leg is SAS7BDAT. In PROC "
            "SQL, use a LIBNAME for a SAS7BDAT source rather than a quoted "
            "path.\n\n"
            f"Detail: {DOCS}/language/file-formats/"
        )

    @mcp.prompt()
    def debug_jenner_log(log_text: str, severity: str | None = None) -> str:
        """Diagnose a run log, including the causes a SAS reading would not suggest."""
        focus = f"\nFocus on {severity}-level messages.\n" if severity else ""
        return (
            "Diagnose this Jenner run log. Read it as a SAS log — the "
            "conventions are identical — and give the root cause plus the "
            f"smallest fix, not a restatement of the message.{focus}\n"
            "Four causes are Jenner-specific and will not occur to you from SAS "
            "experience alone:\n\n"
            "  * 'Dataset not found' involving a libref usually means the "
            "library's engine and the file on disk disagree. A library has ONE "
            "engine and every member uses it.\n"
            "  * A numeric column behaving as text usually means it "
            "round-tripped through CSV, which does not preserve types. Avro "
            "(the default), Parquet and SAS7BDAT do.\n"
            "  * A truncated result or a timeout may be tier policy rather than "
            "a program defect — anonymous callers get lower caps.\n"
            "  * WORK does not persist between run_sas calls. A 'does not "
            "exist' error for something an earlier call created means it needs "
            "to be in the same program.\n\n"
            f"```\n{log_text}\n```\n\n"
            f"Reference: {DOCS}/getting-started/sas-differences/"
        )
