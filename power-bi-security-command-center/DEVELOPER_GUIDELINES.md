# Developer Guidelines — Power BI Security & Governance Command Center

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

A local-only Streamlit governance tool for Kong's Power BI duties. Four modules
(under the 🛠️ Workspace view; 📖 How to Use is the user-facing docs page):

1. **RLS Engine** — merges monthly HR Staff List + Rule_Book + Exceptions into
   `Final_RLS.csv`, one row per user per store.
2. **Delta Tracking** — compares previous vs new HR lists: **Leavers** (revoke),
   **Joiners** (provision, with suggested access), **Movers** (review).
3. **Access Audit & Gap Analysis** — register of manually granted cloud access,
   cross-checked against rule-expected access.
4. **Access Query Tool** — by-user and by-asset effective-access resolver.

No Power BI API is used or needed — everything is local CSV/Excel + Pandas.

## Data contracts

Canonical columns: `Work Email`, `Department`, `Position`, `Store_Access`,
`Store_Name`, `Report_Access`, plus `Source` (`Rule_Book` / `Exception` / `NO RULE`).

**HR Staff List** (`.xlsx`) — raw columns mapped via the sidebar ⚙️ Schema
Mapping to `Work Email` / `Department` / `Position`. `Department` holds
**store codes**. Extra columns pass through; dupes on email keep last.

**Rule_Book** (`.csv`/`.xlsx`) — `Department`, `Position`, `Store_Access`,
`Report_Access`. `Department` is a store code or `*` (position-wide wildcard).
`Store_Access`: codes separated by **`:`** (e.g. `A:C`). `Report_Access`:
names separated by **`;`**.

**Exceptions** (`.csv`/`.xlsx`, optional) — `Work Email`, `Store_Access`,
`Report_Access`, `Reason`. Wins per email; empty cells keep the rule value.

**Store_Master** (`.csv`/`.xlsx`, optional) — `Store_Code`, `Store_Name`.
Joined after explosion for friendly display; unknown codes fall back to the code.

**Access_Audit** (`.csv`/`.xlsx`) — `Date`, `Work Email`, `Asset_Name`,
`Permission_Level`, `Remark`.

## Functions & methodology (all pure — no `st.*`)

- `simulate_rls(hr, rules, exceptions, store_master)` — exact
  `(Department, Position)` match first, then `*` wildcard; exceptions override
  per email; `Store_Access` split on `:` and exploded to one row per store;
  store codes joined to the master for `Store_Name`; unmatched staff kept as a
  visible `NO RULE` row. Returns `(final_df, warnings)`.
- `compute_deltas(old, new, rules, store_master)` — **Leavers**: anti-join
  old ⨯ new; **Joiners**: anti-join new ⨯ old, then through `simulate_rls` for
  suggested access; **Movers**: inner join + mask on changed
  `Department`/`Position`. All joins strictly on `Work Email`.
- `gap_analysis(expected, audit)` — expands expected `Report_Access` into
  `(Work Email, Asset)` pairs, anti-joins both directions vs the audit log:
  missing → `st.error`, excess → `st.warning`. No hidden temp keys
  (a past `_email_key` leak crashed this — joins use real columns only).
- `check_unmapped_master_data(hr, rules)` — diffs HR's unique
  Positions/Departments against the Rule_Book; new values get the red
  *"New Position/Department detected … update the Rule Book"* warning.
  Called in the RLS, Delta, and Gap flows.
- Query Tool reads `final_rls` from session state (prompts to run RLS first);
  by-user shows RLS stores + audit reports, by-asset shows store→emails and
  report→(expected vs actual) grants.

## UI

- Sidebar: **Navigate** radio (🛠️ Workspace / 📖 How to Use) + ⚙️ Schema Mapping.
- `render_docs()` is pure `st.markdown`; the Workspace branch is skipped via
  `st.stop()` when docs are shown.
- Session state: `hr_current`, `store_master_current`, `audit_log`,
  `final_rls`, `delta_res`, `gap_res`. The audit log is in-memory —
  **download the CSV** before closing the browser.

## Testing

UI marker for the harness: `# ===... state ===`. Cover at minimum: exact +
wildcard + exception resolution, `:` explosion, store-master join and fallback,
unmatched-staff visibility, leaver/joiner/mover detection, joiner suggestion,
gap analysis both directions + empty audit, unmapped-data detection, query
by-user/by-asset, cp1252 (é) encoding fallback.

## Security notes

- The audit log is in-memory — **download the CSV** before closing the browser.
- Treat `Final_RLS.csv` as sensitive (staff emails) — never commit it.
- The linked folder is **read-only** — the app never writes into it. Only the
  link path itself is persisted (`storage/link.json`, gitignored).

## Linked data folder (2026-10-16)

`link_core.py` (Streamlit-free, unit-tested) implements the 📁 Linked data folder:
`save_link`/`load_link`/`clear_link` persist the folder path to
`storage/link.json`; `resolve_slot` maps each uploader key to a conventional
filename (case-insensitive stem match, `.xlsx` preferred over `.csv`); `LinkedFile`
is a `BytesIO` duck-typing a Streamlit `UploadedFile` so all existing
`read_table_upload` / `pd.read_excel` call sites work unchanged;
`pick_source(slot, uploaded, folder)` gives manual uploads precedence over the
linked file. Slot → filename mapping:

| Slot(s) | Conventional filename |
|---|---|
| `rls_hr`, `gap_hr` | `HR Staff List.xlsx` |
| `rls_rules`, `delta_rules`, `gap_rules` | `Rule_Book.xlsx` / `.csv` |
| `rls_ex` | `Exceptions.xlsx` / `.csv` |
| `rls_sm` | `Store_Master.xlsx` / `.csv` |
| `delta_old` / `delta_new` | `Previous HR List.xlsx` / `New HR List.xlsx` |
| `audit_load` | `Access_Audit.xlsx` / `.csv` |

Tests live in `tests/run_tests.py` (22 checks, no Streamlit needed).

## Future work

- Persist the audit log to local SQLite instead of session state.
- Scheduled monthly reminder to run the delta check.
- Diff view for movers showing old → new values side by side.
