# Developer Guidelines — Messy Excel Sanitizer

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Clean and merge messy human-created Excel/CSV files from different stores
or departments into one master dataset — 100% local. Four steps:

1. **Batch upload** — multiple `.xlsx`/`.csv`; per-workbook sheet picker.
2. **Sanitization pipeline** — skip top N title rows, unmerge cells +
   forward-fill, strip whitespace, standardize headers, unify dates, drop
   empties/duplicates.
3. **Schema validation** — flag sources missing expected columns.
4. **Concatenate & export** — one master `.xlsx`/`.csv`/`.parquet` download.

## Layout

```
messy-excel-sanitizer/
├── app.py                  # Streamlit UI only
├── sanitize_core.py        # pure logic — no st.*
├── tests/run_tests.py      # 16 checks, no Streamlit needed
└── requirements.txt        # + openpyxl, pyarrow
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`san6_` prefix; no `st.set_page_config` (suite launcher owns it).

## Functions & methodology (`sanitize_core.py`, all pure)

- `read_source(raw, filename, sheet, skip_rows, unmerge)` — xlsx: with
  `unmerge=True`, merged ranges are unmerged via openpyxl
  (`ws.merged_cells.ranges` — the `merged_cell_ranges` property is broken
  on some openpyxl builds) by saving the unmerged workbook to a buffer and
  re-reading; horizontally merged **headers** are forward-filled across the
  header row. Then `skip_rows` title rows are dropped and the next row
  becomes the header (blank → `col_{i}`, duplicates → `_2` suffixes).
  CSVs go through the `utf-8-sig → cp1252` fallback. Raises `ValueError`
  (never crashes) on bad input.
- `sanitize_df(df, opts)` — `ffill` (down only — safe for data rows),
  whitespace strip on text columns, header modes (`strip` / `snake_case`),
  date unification (only columns where ≥50% of values look date-like via
  `DATE_LIKE`, then ≥50% parse with `dayfirst`; result is `datetime64`),
  drop fully-empty rows/cols, drop duplicates. Returns `(df, notes)` so the
  UI can report exactly what was done.
- `_is_text(s)` — `is_string_dtype`, covering pandas 2 (`object`) and
  pandas 3 (`str`) — text detection must not assume `object` dtype.
- `validate_schema(df, expected)` — case/space-insensitive
  `(missing, extra)` column lists.
- `concat_sources([(file, sheet, df), …])` — union of columns
  (`sort=False`) plus `_source_file` / `_source_sheet` tracking columns.

## App-specific conventions

- Only sources passing validation (no missing columns, no read errors)
  enter the master dataset; failures stay visible in the validation report.
- Uploaded raw bytes are kept in session state so pipeline options can be
  re-run without re-uploading — keep uploads reasonably sized.
- Dates are kept as `datetime64` in the master frame; Excel export renders
  them natively.

## Testing

`python3 tests/run_tests.py` covers: title-row skip, header parsing,
unmerge→gap→ffill, merged-header across-fill, snake_case headers, date
unification values, whitespace stripping, empty/dupe dropping, header
dedupe, schema missing/extra, concat union + source tracking, CSV path,
empty-after-skip rejection. `AppTest` boot verified for `app.py`.

## Future work

- Column-type coercion profiles (currency → float with symbol stripping).
- Fuzzy header matching against the expected schema ("Stor Name" → "store_name").
- Per-source column mapping UI before concatenation.
