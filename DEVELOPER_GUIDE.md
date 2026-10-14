# Local Apps — Developer Guide

Shared conventions for every app in this repo. App-specific details
(schema, parsing logic, methodology) live in each app's own
`DEVELOPER_GUIDELINES.md` — this file covers what they all share.

## Layout

```
local-apps/
├── DEVELOPER_GUIDE.md        # this file — shared conventions
├── README.md                 # app catalog (keep the table current)
└── <app-slug>/
    ├── app.py                # the entire app, single file
    ├── requirements.txt      # minimal deps
    └── DEVELOPER_GUIDELINES.md  # app-specific: purpose, data contracts,
                                 # functions, methodology, tests
```

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
streamlit run app.py
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

## Git workflow

- Commit per app: `<slug> vN: <what changed>` (e.g. `Command Center v3: ...`).
- Pushes use a **transient PAT** supplied by Kong per push: embed it in the
  remote URL for that one command only, then remove the remote
  (`git remote remove origin`). Never print, store, commit, or hardcode it.
- After Kong pastes a PAT, remind him **once** to rotate/revoke it.

## Security

- Apps are local-only: no network calls, no API keys, no secrets in the repo.
- Never commit data exports (they contain staff emails etc.). `.gitignore`
  covers `__pycache__/`, `*.pyc`, `.venv/` — add data filenames if an app
  writes them to disk.

## What goes where

| This file (shared) | Per-app `DEVELOPER_GUIDELINES.md` |
|---|---|
| Layout, run instructions, new-app checklist | Purpose: what the app does and why |
| Pure/UI layering, testing harness | Data contracts: exact columns per file |
| Encoding, validation, join, anti-join conventions | Functions & methodology (the app's logic) |
| Git/PAT workflow, security | App-specific tests & edge cases, future work |
