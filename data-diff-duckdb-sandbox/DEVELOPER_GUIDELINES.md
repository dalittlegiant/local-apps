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
├── tests/run_tests.py      # 21 checks, no Streamlit needed
└── requirements.txt        # + duckdb, pyarrow
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`dd5_` prefix; no `st.set_page_config` (suite launcher owns it).

## Functions & methodology (`diff_core.py`, all pure)

- `load_upload(name, raw, sheet)` — parquet via pyarrow, CSV with
  `utf-8-sig → utf-8 → cp1252 → latin-1`, Excel via openpyxl as `object`
  dtype. Raises `ValueError` (never crashes) on bad input.
- `excel_sheets(raw)` — workbook sheet names for the per-file selector.
- `sanitize_table_name(name)` — safe DuckDB identifiers (`t_` prefix for
  leading digits).
- `profile_df(df)` — rows/cols, `memory_usage(deep=True)`, per-column
  dtype, null count/%, `n_unique`.
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

- Uploaded files are registered once as DuckDB views named after the
  (sanitized) file; name collisions get `_2`, `_3` suffixes.
- The DuckDB connection lives in session state (in-memory, per browser
  session).
- Diff previews show the first 500–1000 rows; full results go through the
  CSV/Excel/Parquet download buttons.

## Testing

`python3 tests/run_tests.py` covers: csv/parquet loading, unsupported-type
rejection, table-name sanitizing, null-%/memory profiling, SQL success +
error paths, added/deleted detection, cell-level old→new values, schema
add/remove/dtype-change, int-vs-str key compatibility, duplicate-key
warnings, empty-key rejection, NaN==NaN suppression. `AppTest` boot
verified for `app.py`.

## Future work

- Saved query library per table.
- Side-by-side cell diff with before/after highlighting.
- Direct `.xlsx` multi-sheet registration without a selector round-trip.
