# Developer Guidelines — Data Quality Watchdog

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Validate raw CSV/Excel/Parquet files before they feed Power BI or ETL
pipelines — a pre-refresh gatekeeper, 100% local.

## Layout

```
data-quality-watchdog/
├── app.py                  # Streamlit UI only
├── dq_core.py              # pure logic — no st.*
├── tests/run_tests.py      # 23 checks, no Streamlit needed
└── requirements.txt
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`dq12_` prefix; no `st.set_page_config` (suite launcher owns it).

## Functions & methodology (`dq_core.py`, all pure)

- `load_file(name, raw)` — parquet/csv/xlsx; encoding-tolerant CSV;
  `ValueError` (never crash) on bad input.
- `run_checks(df, opts)` → `{name: {status, summary, exceptions}}`,
  status ∈ pass/warning/fail:
  - **Duplicate PKs** (fail) — `duplicated(keep=False)` on key cols.
  - **Required columns** (fail) — missing list.
  - **Null spikes** (warning) — columns over configurable % threshold.
  - **Whitespace** (warning) — `is_string_dtype` cols with un-stripped values
    (pandas-3-safe).
  - **Outliers** (warning) — IQR or Z-score on numeric cols with ≥4
    non-null values; exception rows tagged.
- `summarize(df, metric_cols, cat_cols)` — row count, metric sums,
  distinct category counts.
- `baseline_compare(cur, base, pct_threshold)` — flags row-count, sum, and
  distinct-count drift ≥ threshold (fail at ≥2× threshold; `None` delta
  when baseline is 0).
- `overall_status` — fail > warning > pass; `exceptions_frame` unions all
  exception rows (deduped) for the CSV download.

## App-specific conventions

- Checks run on demand (button), results persist in session for the
  expanders/downloads.
- Baseline is optional; drift table only renders when a baseline is loaded.

## Testing

`python3 tests/run_tests.py` covers: dup-PK fail/pass, missing-column
fail, null-spike threshold behavior, whitespace detection, IQR outlier
values, Z-score threshold, overall fail/pass, summarize math, baseline
drift flags (rows/sums), flag schema, no-drift silence, exception
union/dedupe, parquet/csv loading, bad-type rejection. `AppTest` boot
verified for `app.py`.

## Future work

- Saved check profiles per data source.
- Trend of report cards over time (local history).
- Schema-drift detection (column add/remove vs baseline).
