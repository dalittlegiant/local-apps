# Developer Guidelines — Data Diff & DuckDB Sandbox

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Inspect large local datasets and diff file versions without Excel
freezing — 100% local. Two tools (one tab each):

1. **Profiler & SQL Runner** — drop `.parquet`/`.csv`/`.xlsx` files; instant
   schema, null %, memory footprint; DuckDB SQL editor; export subsets to
   CSV/Excel/Parquet.
2. **Version Diff Engine** — old vs new snapshots on primary key(s):
   added rows, deleted rows, schema/column discrepancies, and cell-level
   old → new changes.

## Layout

```
data-diff-duckdb-sandbox/
├── app.py                  # Streamlit UI only
├── diff_core.py            # pure logic — no st.*
├── tests/run_tests.py      # 57 checks, no Streamlit needed
├── .streamlit/config.toml  # maxUploadSize=1000 (also at repo root + launcher dir)
└── requirements.txt        # + duckdb, pyarrow
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`dd5_` prefix; guarded `st.set_page_config` (try/except — no-op inside the
suite launcher, which owns page config).

## Functions & methodology (`diff_core.py`, all pure)

- `load_upload(name, raw, sheet, skiprows=0)` — parquet via pyarrow, CSV with
  `utf-8-sig → utf-8 → cp1252 → latin-1`, Excel via openpyxl as `object`
  dtype. Raises `ValueError` (never crashes) on bad input. Used for xlsx
  ingestion and the diff tab only — parquet/csv never touch pandas.
  `skiprows` skips that many physical lines before the header (report
  exports with title/preamble lines); ignored for parquet.
- `write_upload_to_temp(name, raw)` — stages bytes in the OS temp dir
  (outside the repo; never committable). Returns the path; caller deletes
  it on table drop.
- `duckdb_source_clause(path, name, all_varchar=False, null_padding=False, skip_rows=None)` — `read_parquet(...)` /
  `read_csv_auto(...)` FROM-fragment so DuckDB scans the staged file
  natively. `all_varchar=True` (CSV only) appends `all_varchar=true` —
  Safe Mode, see below. `null_padding=True` (CSV only) appends
  `null_padding=true` — Lenient CSV, see below. `skip_rows=N` (CSV
  only) appends `skip=N`, overriding the sniffer's auto-detected
  preamble skip; `None` leaves auto-detection on.
- `excel_sheets(raw)` — workbook sheet names for the per-file selector.
- `sanitize_table_name(name)` — safe DuckDB identifiers (`t_` prefix for
  leading digits).
- `profile_df(df)` — rows/cols, `memory_usage(deep=True)`, per-column
  dtype, null count/%, `n_unique` (pandas path: xlsx, diff tab).
- `profile_duckdb(con, tname)` — same output shape, computed inside DuckDB
  as a single-pass aggregation (no DataFrame materialized).
- `profile_frame(profile)` — renders either profiler's dict.
- `run_sql(con, sql)` — DuckDB execute → DataFrame; DB errors surface as
  `ValueError("SQL error: …")`.
- `with_utf8_bom(data)` — prefixes the UTF-8 BOM (utf-8-sig) if absent.
  Excel sniffs CSV encoding from the BOM; without it UTF-8 Chinese text
  garbles. DuckDB `COPY` writes no BOM, so full-result CSV bytes pass
  through this in `_full_export` (preview CSVs encode `utf-8-sig`
  directly at the download button).
- `diff_datasets(old, new, keys)` — keys **string-cast on both sides** so
  int/str drift still joins; duplicate keys produce warnings (not errors).
  Schema diff covers added/removed columns and dtype changes. Added/deleted
  are anti-joins with `indicator=True` on the real key columns. Changed
  cells: inner join on keys → per-column compare where `NaN == NaN` is not
  a change → long format `(keys…, column, old_value, new_value)`, capped at
  10,000 rows with a warning.

## App-specific conventions

- **Ingest-once registry** (`st.session_state["dd5_registry"]`): uploads
  are keyed by `("upload", filename, size[, sheet])`, local paths by
  `("path", abspath[, sheet])`. parquet/csv uploads are staged to the OS
  temp dir and exposed as DuckDB VIEWs over `read_parquet`/`read_csv_auto`;
  **local paths are queried in place** — DuckDB reads the file directly,
  bypassing Python memory entirely. xlsx (either source) is parsed once
  and materialized as a DuckDB TABLE. Nothing is re-parsed on reruns.
  Name collisions get `_2`, `_3` suffixes. "Clear all tables" drops the
  views/tables and deletes the temp files (path-mode files are never
  touched).
- **Safe Mode** (`st.toggle` "Enable Safe Mode (Read all as String)",
  SQL tab, default OFF): CSV views are created over
  `read_csv_auto(..., all_varchar=true)`, bypassing type inference so a
  file whose deep rows violate the sniffed types (e.g. a string in a
  BIGINT column) still loads — every column as VARCHAR. Registry entries
  carry a `"safe"` flag; flipping the toggle re-creates the view under
  the **same table name** (reusing the staged temp file, never staging a
  second copy) and evicts that table's cached profile. In strict mode
  the conversion error surfaces at the profiler's full scan: the app
  catches `duckdb.Error`, shows an `st.error` pointing at the toggle,
  and puts the raw traceback (which names the exact file line) in a
  "View Error Details & Line Number" expander — it never crashes.
  CSV-only by design: parquet keeps native types, xlsx and the whole
  Diff tab already load through pandas as text.
- **Lenient CSV** (`st.toggle` "Enable Lenient CSV (Pad short rows with
  NULL)", SQL tab, default OFF): CSV views are created over
  `read_csv_auto(..., null_padding=true)`, so rows with FEWER columns
  than the header are padded with NULL instead of raising
  "Expected Number of Columns ... Found: ...". This is a DIFFERENT
  failure class from Safe Mode: Safe Mode bypasses type inference only
  and cannot fix a short row. Rows with MORE columns than the header
  still error; `ignore_errors` (which would drop bad rows) is
  deliberately not offered. Registry entries carry both `"safe"` and
  `"lenient"` flags; flipping either re-creates the view under the same
  table name. The profiler's error card branches on the traceback:
  column-count errors point at Lenient CSV, conversion errors at Safe
  Mode. Sniffer nuance: a bad row INSIDE the ~20,480-row sniff sample
  breaks dialect detection itself (file loads as a single VARCHAR
  column) instead of erroring — only bad rows past the sample produce
  the clean column-count error.
- **SQL-tab header skip** (`st.toggle` "Auto-detect skipped rows
  (DuckDB)", default ON, + "Rows to skip before the header (CSV)"
  number input): the toggle OFF passes an explicit `skip=N` to
  `read_csv_auto`, overriding auto-detection for report formats whose
  preamble DuckDB misreads (e.g. a title row that looks like a header).
  `skip=0` genuinely means "skip nothing" — it is not auto-detect, so
  the toggle exists to tell the two apart. Registry entries carry
  `"skip_rows"` alongside `"safe"`/`"lenient"`; flipping any of the
  three re-creates the view under the same table name. Naming trap:
  DuckDB's SQL parameter is `skip`, pandas' is `skiprows` — the Diff
  tab's input uses the pandas spelling, the SQL tab's the DuckDB one,
  and the two tabs keep separate widget keys/state on purpose.
- **Connection** (`_con()`): single persistent in-memory DuckDB connection
  via `@st.cache_resource` — views and file metadata stay hot between
  queries. Single-user local app: no cross-thread sharing.
- **Query path** (`_run_query`): SELECTs run `COUNT(*)` for the total plus
  `… LIMIT 1000`, both via zero-copy Arrow (`to_arrow_table()` — never
  `fetchdf()`); `st.dataframe` renders the Arrow table natively. An
  `st.info` banner shows the true total when it exceeds 1,000 rows.
  Preview downloads (≤1,000 rows) convert Arrow→pandas, which is trivial
  at that size. Full export is DuckDB `COPY` straight to a temp file —
  no pandas, no StringIO. CSV exports are always **utf-8-sig** (BOM) so
  Excel renders Chinese correctly: previews via
  `.encode("utf-8-sig")`, full results via `with_utf8_bom()` on the
  COPY output (DuckDB itself writes no BOM).
- **Profiler cache** (`st.session_state["dd5_prof_cache"]`): the
  single-pass `COUNT(DISTINCT)` aggregation scans the full dataset, so
  each table is profiled **once** — expander bodies execute on every
  Streamlit rerun, and re-profiling every table on every Run click was
  the dominant latency source. Cleared by "Clear all tables".
  **Failures are cached too** (`{"error": traceback}`): a broken file
  must not be re-scanned to its failure line on every interaction.
  The entry is evicted when the view is re-created (Safe / Lenient
  toggle flip) or tables are cleared — same staleness contract as
  successful profiles (a file edited on disk needs "Clear all tables"
  to re-read).
- The DuckDB connection lives in session state (in-memory, per browser
  session).
- **Query isolation**: the SQL editor + Run button live in an `st.form`, so
  typing never triggers execution; results (preview, total, ms) are stored
  in session state. UI preview is capped at 1,000 rows with total-row
  count and execution ms shown; full results export via DuckDB
  `COPY (sql) TO ...` (CSV/Parquet) on explicit click — no pandas.
- Diff previews show the first 500–1000 rows; full results go through the
  CSV/Excel/Parquet download buttons. Diff-tab DataFrames are cached in
  session state keyed by `(tag, skiprows, filename, size)` — changing the
  skip count re-parses. The Diff tab's "Rows to skip before the header"
  number input (default 0, shared by old + new) handles report-style
  files whose preamble title lines would otherwise make pandas infer 1
  column and fail with "Expected 1 fields in line …, saw N". The SQL
  tab needs no such input: DuckDB's `read_csv_auto` auto-detects
  `skip_rows` itself.

## Testing

`python3 tests/run_tests.py` covers: csv/parquet loading, unsupported-type
rejection, table-name sanitizing, null-%/memory profiling, SQL success +
error paths, temp-file staging (round-trip, outside-repo, suffix),
`duckdb_source_clause` fragments + xlsx rejection + Safe Mode fragment,
dirty-CSV end-to-end (30k numeric rows + a string in the BIGINT column:
strict-mode `profile_duckdb` raises `duckdb.Error` naming line 30002,
`all_varchar` loads all rows as VARCHAR with the bad value preserved),
short-row CSV end-to-end (bad row past the 20,480-row sniff sample:
strict-mode `profile_duckdb` raises "Expected Number of Columns ...
Found: 3", `null_padding` loads all rows with trailing columns NULL),
skiprows (preamble CSV raises "Expected 1 fields" without it, loads
with the true header at skiprows=2; Excel title row at skiprows=1),
SQL-tab skip (auto-detection picks a title row as header; explicit
skip=1 recovers the real header; skip=0 means skip nothing),
export encoding (BOM added, idempotent, Chinese payload round-trips;
DuckDB COPY output verified BOM-less then fixed), end-to-end native scan
of a staged CSV, `profile_duckdb` rows/nulls/uniques + frame rendering,
`profile_duckdb`/`profile_df` parity, added/deleted detection, cell-level
old→new values, schema add/remove/dtype-change, int-vs-str key
compatibility, duplicate-key warnings, empty-key rejection, NaN==NaN
suppression. `AppTest` boot verified for `app.py`.

## Future work

- Saved query library per table.
- Side-by-side cell diff with before/after highlighting.
- Direct `.xlsx` multi-sheet registration without a selector round-trip.

### Security notes (2026-10-15)

The SQL box executes arbitrary DuckDB SQL with full local file access — a caption
under the editor says so (by design for a single-user local sandbox). Staged
upload temp files (`dd5_*`) are deleted on "Clear all tables"; a startup sweep
(`_sweep_stale_staged_files`) removes ones leaked by closed sessions.
