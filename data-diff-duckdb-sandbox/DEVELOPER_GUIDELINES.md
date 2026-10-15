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
├── tests/run_tests.py      # 34 checks, no Streamlit needed
├── .streamlit/config.toml  # maxUploadSize=500 (also at repo root)
└── requirements.txt        # + duckdb, pyarrow
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`dd5_` prefix; guarded `st.set_page_config` (try/except — no-op inside the
suite launcher, which owns page config).

## Functions & methodology (`diff_core.py`, all pure)

- `load_upload(name, raw, sheet)` — parquet via pyarrow, CSV with
  `utf-8-sig → utf-8 → cp1252 → latin-1`, Excel via openpyxl as `object`
  dtype. Raises `ValueError` (never crashes) on bad input. Used for xlsx
  ingestion and the diff tab only — parquet/csv never touch pandas.
- `write_upload_to_temp(name, raw)` — stages bytes in the OS temp dir
  (outside the repo; never committable). Returns the path; caller deletes
  it on table drop.
- `duckdb_source_clause(path, name)` — `read_parquet(...)` /
  `read_csv_auto(...)` FROM-fragment so DuckDB scans the staged file
  natively.
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
- **Connection** (`_con()`): single persistent in-memory DuckDB connection
  via `@st.cache_resource` — views and file metadata stay hot between
  queries. Single-user local app: no cross-thread sharing.
- **Query path** (`_run_query`): SELECTs run `COUNT(*)` for the total plus
  `… LIMIT 1000`, both via zero-copy Arrow (`to_arrow_table()` — never
  `fetchdf()`); `st.dataframe` renders the Arrow table natively. An
  `st.info` banner shows the true total when it exceeds 1,000 rows.
  Preview downloads (≤1,000 rows) convert Arrow→pandas, which is trivial
  at that size. Full export is DuckDB `COPY` straight to a temp file —
  no pandas, no StringIO.
- **Profiler cache** (`st.session_state["dd5_prof_cache"]`): the
  single-pass `COUNT(DISTINCT)` aggregation scans the full dataset, so
  each table is profiled **once** — expander bodies execute on every
  Streamlit rerun, and re-profiling every table on every Run click was
  the dominant latency source. Cleared by "Clear all tables".
- The DuckDB connection lives in session state (in-memory, per browser
  session).
- **Query isolation**: the SQL editor + Run button live in an `st.form`, so
  typing never triggers execution; results (preview, total, ms) are stored
  in session state. UI preview is capped at 1,000 rows with total-row
  count and execution ms shown; full results export via DuckDB
  `COPY (sql) TO ...` (CSV/Parquet) on explicit click — no pandas.
- Diff previews show the first 500–1000 rows; full results go through the
  CSV/Excel/Parquet download buttons. Diff-tab DataFrames are cached in
  session state keyed by `(tag, filename, size)`.

## Testing

`python3 tests/run_tests.py` covers: csv/parquet loading, unsupported-type
rejection, table-name sanitizing, null-%/memory profiling, SQL success +
error paths, temp-file staging (round-trip, outside-repo, suffix),
`duckdb_source_clause` fragments + xlsx rejection, end-to-end native scan
of a staged CSV, `profile_duckdb` rows/nulls/uniques + frame rendering,
`profile_duckdb`/`profile_df` parity, added/deleted detection, cell-level
old→new values, schema add/remove/dtype-change, int-vs-str key
compatibility, duplicate-key warnings, empty-key rejection, NaN==NaN
suppression. `AppTest` boot verified for `app.py`.

## Future work

- Saved query library per table.
- Side-by-side cell diff with before/after highlighting.
- Direct `.xlsx` multi-sheet registration without a selector round-trip.
