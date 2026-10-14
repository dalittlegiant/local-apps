# Developer Guidelines — Power BI Security & Governance Command Center

## Purpose

A local-only Streamlit governance tool for Kong's Power BI duties. Three modules:

1. **RLS Engine** — merges monthly HR Staff List (Excel) + Rule_Book.csv +
   Overrides.csv into a clean `Final_RLS.csv`, with rule matching on
   **both** `Base_Store` and `Position`.
2. **Delta Tracking** — compares previous vs new HR lists to find **Leavers**
   (revoke access), **Joiners** (suggest access from rules), and **Movers**
   (position/store changed).
3. **Access Audit & Gap Analysis** — a local data-entry form maintains
   `Access_Audit.csv` (Date, Email, Asset_Name, Permission_Level); Gap Analysis
   cross-checks expected access (HR + rules) vs actual grants and flags
   **Missing Required Access** and **Excess / Unknown Access**.

No Power BI API is used or needed — everything is local CSV/Excel + Pandas.

## Project layout

```
power-bi-security-command-center/
├── app.py                  # The entire app (single file, Streamlit)
├── requirements.txt        # streamlit, pandas, openpyxl
└── DEVELOPER_GUIDELINES.md # This file
```

Run locally with:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Architecture

`app.py` is organized in layers, top to bottom:

1. **Helpers & parsers** (pure functions, no Streamlit calls)
   - `_norm_email()` — lowercase + strip; **every** join key goes through this.
     Email matching is the #1 source of silent misses, so this is load-bearing.
   - `read_hr_excel()` — reads the HR Excel, validates `Email/Base_Store/Position`,
     dedupes on normalized email (keeps last).
   - `read_csv_upload()` — tolerant CSV reader (all columns as strings).
   - `sample_rule_book()` / `sample_overrides()` — downloadable templates.
2. **Core logic** (pure functions, unit-testable)
   - `simulate_rls(hr, rules, overrides)` — the RLS engine:
     - Exact `(Base_Store, Position)` match first, then wildcard `Base_Store="*"`
       fallback (e.g. Regional Manager sees ALL stores).
     - Per-email overrides win over rules; `Source` column records which applied.
     - Returns `(final_df, warnings)` — staff with no matching rule produce a
       warning, never a silent empty row.
   - `compute_deltas(old, new, rules)` — personnel movement:
     - **Leavers**: anti-join old ⨯ new (`indicator=True`, `left_only`).
     - **Joiners**: anti-join new ⨯ old, then run through `simulate_rls` to
       suggest RLS codes + report access.
     - **Movers**: inner join + boolean mask on changed `Base_Store`/`Position`.
   - `gap_analysis(expected, audit)` — expands expected report lists into
     `(email, asset)` rows, then anti-joins both directions:
     - missing = expected − actual → `st.error`
     - excess = actual − expected → `st.warning`
3. **Session state** — `hr_current` (reused across tabs), `audit_log` (the
   register), `final_rls`, `delta_res`, `gap_res`. The audit log lives only in
   memory; download the CSV to persist it.
4. **UI** — three tabs. Delta and Gap results use `st.error`/`st.warning` so
   leavers and missing access visually pop, per the brief.

## Data contracts

**HR Staff List (.xlsx)** — columns: `Email`, `Base_Store`, `Position`
(extra columns pass through untouched).

**Rule_Book.csv** — columns: `Base_Store`, `Position`, `RLS_Stock_Room_Codes`,
`Report_Access`. Multi-value fields use `;` as separator.
Use `Base_Store = *` for position-wide wildcard rules.

**Overrides.csv** — columns: `Email`, `RLS_Stock_Room_Codes`, `Report_Access`,
`Reason`. Empty cells mean "keep the rule value".

**Access_Audit.csv** — columns: `Date`, `Email`, `Asset_Name`, `Permission_Level`.

## Conventions

- **Parsers and logic stay pure.** No `st.*` calls above the `# UI` section —
  this keeps them testable without Streamlit (see testing below).
- **Joins are always on `_email_key`** (normalized), never on raw `Email`.
- **Anti-joins use `indicator=True`.** This is the standard pattern for
  leavers/joiners/missing/excess — do not reimplement with `isin()` loops.
- **Never crash on bad input.** Validators raise `ValueError` with a human
  message; the UI catches and shows it. Unknown files are skipped, not fatal.
- **`;` is the multi-value separator** in `RLS_Stock_Room_Codes` and
  `Report_Access`. Keep it consistent everywhere (templates, parsing, export).

## Testing

Streamlit is not required. Extract the pure section and `exec` it:

```python
src = open('app.py').read()
pure = src[:src.index("# ====" + "=" * 60 + " state ===")]
pure = pure.replace("import streamlit as st\n", "")
ns = {}
exec(pure, ns)
# ns['simulate_rls'], ns['compute_deltas'], ns['gap_analysis'], ...
```

Cover at minimum: exact + wildcard + override rule resolution, unmatched-staff
warning, leaver/joiner/mover detection, joiner access suggestion, gap analysis
both directions, empty audit log, email normalization (case/whitespace).

## Security notes

- Runs entirely locally; no network calls, no API keys.
- The audit log is in-memory session state — **download the CSV** before
  closing the browser or entries are lost. (A future upgrade could persist to
  a local SQLite file.)
- Treat exported `Final_RLS.csv` as sensitive (contains staff emails) — do not
  commit it to the repo.

## Future work

- Persist the audit log to local SQLite instead of session state.
- Parse `RLS_Stock_Room_Codes` against actual Power BI RLS role definitions.
- Scheduled monthly reminder to run the delta check.
- Diff view for movers showing old → new values side by side.
