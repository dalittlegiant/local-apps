# Local Apps — Developer Guide

Shared conventions for every app in this repo. App-specific details
(schema, parsing logic, methodology) live in each app's own
`DEVELOPER_GUIDELINES.md` — this file covers what they all share.

## Layout

```
local-apps/
├── DEVELOPER_GUIDE.md        # this file — shared conventions
├── README.md                 # app catalog (keep the table current)
├── <app-slug>/
│   ├── app.py                # the entire app, single file
│   ├── requirements.txt      # minimal deps
│   └── DEVELOPER_GUIDELINES.md  # app-specific: purpose, data contracts,
│                                # functions, methodology, tests
└── <mpa-slug>/               # multi-page apps (the exception below)
    ├── launcher.py           # entrypoint: set_page_config + st.navigation
    ├── pages/                # one self-contained script per app
    ├── lib/                 # pure logic, zero st.* imports (unit-testable)
    ├── tests/                # run_tests.py + fixtures (no Streamlit needed)
    ├── requirements.txt
    └── DEVELOPER_GUIDELINES.md
```

## Multi-page apps (MPA)

A unified launcher is the exception to the single-file rule, used when
several tools belong together (`unified-data-studio`). Conventions:

1. `launcher.py` owns `set_page_config` and `st.navigation` — pages never
   call `set_page_config`.
2. Pure logic lives in `lib/` with **no `st.*` imports at all** (unlike
   single-file apps, no UI-marker slicing is needed — import and test
   directly).
3. Session-state keys are prefixed per page — state is global across MPA
   pages, so `tmdl_`, `sec_`, `thu_` style prefixes prevent collisions.
4. `tests/run_tests.py` must pass before commit; verify page scripts with
   Streamlit's `AppTest` headless runner when the UI changes.
5. Registering a new tool: build it as its own top-level directory
   (`app.py` with a guarded `set_page_config` (see "UI polish conventions"
   below), a `sys.path` bootstrap so local imports work standalone and via
   the launcher, session keys prefixed per app, unique `url_path`), then
   add one `st.Page("../<dir>/app.py", …)` line in the launcher's section
   dict. Existing app folders are read-only — never refactor them to fit
   the launcher.
6. Local persistence (SQLite/JSON): keep it in `<app>/storage/` (or
   `<app>/data/`); both are gitignored along with `*.db`, `*.sqlite*`,
   `*.csv`, `*.xlsx`, `*.parquet`, `*.bim`, `*.tmdl`, `*.pbix`, `.env`.
   Never commit user data. Large transient uploads go to the OS temp dir
   (`tempfile`), never the repo — and temp dirs must be cleaned up
   (delete-on-replace + stale sweep via `lib.safe_extractall` helpers or
   equivalent; see unified-data-studio).
7. Streamlit privacy lockdown: every `.streamlit/config.toml` must set
   `[browser] gatherUsageStats = false` (telemetry off) and
   `[server] address = "127.0.0.1"` (loopback-only bind — never expose the
   local server to the LAN). `tests/test_repo_hardening.py` guards both.
   Config resolution note: Streamlit loads server settings from the
   launch folder (CWD) and the main script's folder only — an MPA page's
   own `.streamlit/` is never inherited. Any entrypoint that needs a
   server setting (e.g. `[server] maxUploadSize` for uploads) must carry
   its own config beside its entry script: repo root (launch-from-root),
   `unified-data-studio/` (the launcher), and each heavy-upload
   standalone app (e.g. `data-diff-duckdb-sandbox/`, 1000 MB). Config
   changes need a full server restart to take effect.
7. Sidebar theme (launcher-owned CSS, injected once via `st.markdown(...,
   unsafe_allow_html=True)`): emojis on the 5 pillar headers only —
   `st.Page` items use no icon. Sub-item styling targets
   `a[data-testid="stSidebarNavLink"]` with a `::before` colored dot;
   per-pillar accents via CSS vars on
   `ul[data-testid="stSidebarNavItems"] > div:nth-of-type(n)` (order must
   match the section dict); hover/active get the accent underline
   (`border-bottom`). Global suite CSS lives here too
   (e.g. `.block-container { padding-top: 1.8rem }`).

## UI polish conventions

- **Cards**: group upload/input areas, KPI metric rows, and result tables
  in `with st.container(border=True):` — 2–5 cards per view, never one
  giant card around the whole page.
- **Empty states**: every view that waits for user input shows a bordered
  onboarding card (subheader + numbered steps), never blank space or a
  raw traceback.
- **Standalone page config**: standalone `app.py` files (which also run
  via the launcher) set page config defensively:
  `try: st.set_page_config(page_title=…, page_icon=…, layout="wide")`
  `except Exception: pass  # launcher owns page config`.
  Suite `pages/` scripts never call it.

## New-app checklist

1. Create `<app-slug>/` with `app.py`, `requirements.txt`, `DEVELOPER_GUIDELINES.md`.
2. Write the per-app guidelines (see "What goes where" below).
3. Add the app to the `README.md` table.
4. Test the pure logic (see "Testing"), `py_compile`, commit, push.
5. **After any change or new build, update the affected guideline file(s)** —
   per-app file for app logic, this file for shared conventions.

## Running any app

```bash
cd <app-folder>
pip install -r requirements.txt
streamlit run app.py            # single-file apps
streamlit run launcher.py       # multi-page apps (unified-data-studio)
```

## App structure

Every `app.py` follows the same layering, top to bottom:

1. **Pure logic** — parsers, merges, transformations. **No `st.*` calls.**
   This is what makes the logic unit-testable without Streamlit.
2. **Session state** — initialized defaults for cross-tab/page data.
3. **Sidebar** — global controls (navigation, schema mapping).
4. **UI** — pages/tabs, file uploaders, buttons, results, downloads.
   A `# UI` (or equivalent) marker comment separates this from the pure section;
   the test harness slices the file at that marker.

## Shared conventions

- **Pure stays pure.** Nothing above the UI marker may call `st.*`.
- **Robust file reading.** CSVs go through an encoding fallback chain
  `utf-8-sig → utf-8 → cp1252 → latin-1` (a real production file with `é`,
  byte `0xe9`, once crashed a plain `pd.read_csv`). Accept `.xlsx`/`.xls`
  uploads wherever possible — Excel sidesteps encoding entirely. Write
  downloads as `utf-8-sig` so Excel opens them cleanly.
- **Never crash on bad input.** Validators raise `ValueError` with a
  human-readable message; the UI catches it and shows `st.error`/`st.warning`.
  Unknown or unreadable files are skipped with a warning, never fatal.
- **Joins on real columns.** Never let a temporary join key leak between
  functions (a past `_email_key` bug crashed Gap Analysis). Build explicit
  pair dataframes and anti-join on the actual columns.
- **Anti-joins use `indicator=True`.** The standard pattern for "in A but not
  B" (leavers, joiners, missing/excess) — don't reimplement with `isin()` loops.
- **Unmatched rows stay visible.** A row that matches no rule gets a warning
  and a visible placeholder (e.g. `NO RULE`), never silently dropped.
- **In-memory state must be downloadable.** Anything the user creates in-app
  (audit logs, results) lives in session state and vanishes when the browser
  closes — always offer a CSV download.
- **Sidebar is for global controls** (navigation, schema/column mapping).
  Per-tab inputs live in the tab.
- **Document multi-value separators per app** (`:` vs `;`) in the per-app guide.

## Testing

Streamlit is not required. Slice off the pure section at the UI marker and
`exec` it, then exercise the functions directly:

```python
src = open('app.py').read()
pure = src[:src.index("<UI marker comment>")]  # see the per-app guide for the exact marker
pure = pure.replace("import streamlit as st\n", "")
ns = {}
exec(pure, ns)
# now call ns['your_function'](...) with crafted inputs
```

Cover at minimum: happy path, empty input, malformed input, encoding edge
cases, and every warning branch. Then `python3 -m py_compile app.py`.

**Test-environment pitfalls (shared):**
- pandas 3.x infers text columns as `str` dtype, not `object` — detect text
  with `pandas.api.types.is_string_dtype`, never `dtype == 'object'`.
- Some openpyxl builds have a broken `ws.merged_cell_ranges` property —
  always read merged ranges via `ws.merged_cells.ranges`.

## Git workflow

- Commit per app: `<slug> vN: <what changed>` (e.g. `Command Center v3: ...`).
- Pushes use a **transient PAT** supplied by Kong per push: embed it in the
  remote URL for that one command only, then remove the remote
  (`git remote remove origin`). Never print, store, commit, or hardcode it.
- After Kong pastes a PAT, remind him **once** to rotate/revoke it.

## Security

- Apps are local-only: no network calls, no API keys, no secrets in the repo.
- Never commit data exports (they contain staff emails etc.). `.gitignore`
  covers `__pycache__/`, `*.pyc`, `.venv/`, `*.db`, `*.sqlite*`, `*.csv`,
  `*.xlsx`, `*.xls`, `*.parquet`, `data/`, `storage/`, `*.bim`, `*.tmdl`,
  `*.pbix`, `.env` — add data filenames if an app writes them to disk.
  `SECURITY_AUDIT_REPORT.md` is gitignored (local-only audit artifact).
- Never `zipfile.extractall()` on user uploads — use the ZipSlip-guarded
  `lib.safe_extractall()` (unified-data-studio) or equivalent.
- JS-embedding rule: any Python string interpolated into a `<script>` block
  must neutralize `</script` (e.g. `<\/script`) and JSON-encode dynamic
  values (`json.dumps`), never f-string them raw.

## Central workspace database (shared convention)

- `workspace_db.py` is copied identically into every storage-backed app dir
  (`unified-data-studio/`, `knowledge-snippet-vault/` [canonical — edit here
  first], `bi-requirement-meeting-hub/`, `ai-prompt-privacy-hub/`).
  **Keep the copies identical** — any schema/behavior change must be synced
  to all of them.
- One `workspace_master.db` holds every module's records. Resolution order:
  `link.json` override → `<repo>/workspace/` → `./workspace_master.db`
  fallback. `link.json` lives next to the default location; never commit
  user folder paths.
- `workspace/` is gitignored (`*.db` covers the database file itself).
- The Workspace Data Manager page (`unified-data-studio/pages/
  workspace_manager.py`, `wsm_` session-state prefix) is the control plane:
  live record counts, linked-folder set/clear, timestamped backup download,
  validated restore (auto-backs-up the current DB first).

## What goes where

| This file (shared) | Per-app `DEVELOPER_GUIDELINES.md` |
|---|---|
| Layout, run instructions, new-app checklist | Purpose: what the app does and why |
| Pure/UI layering, testing harness | Data contracts: exact columns per file |
| Encoding, validation, join, anti-join conventions | Functions & methodology (the app's logic) |
| Git/PAT workflow, security | App-specific tests & edge cases, future work |
