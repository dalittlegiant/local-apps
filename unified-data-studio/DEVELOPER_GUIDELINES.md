# Developer Guidelines — Dav Data Studio (unified-data-studio)

> Shared repo conventions (testing, encoding, git/PAT, security) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's structure, data contracts, and methodology.

## Purpose

One Streamlit multi-page app (`streamlit run launcher.py`) housing three
local productivity & governance tools behind `st.navigation`:

1. **📊 PBIP Metadata & DAX Editor** — parse TMDL tables from a PBIP folder,
   edit DAX formulas and descriptions in the browser, save back to the
   `.tmdl` files with lineageTag-safe line surgery.
2. **🛡️ Security Command Center** — platform-agnostic governance: rule-book
   access engine, joiner/leaver/mover delta tracking, audit register + gap
   analysis, effective-access query tool. Logic ported from the standalone
   `power-bi-security-command-center` v4 (same column contracts, so existing
   Rule_Book / Exceptions / master files keep working).
3. **🎨 Theme & UI Studio** — theme generator (controls → live dashboard
   mockup → `theme.json` export) plus a bulk `visual.json` editor that
   standardizes container formatting across a whole report.

## Layout (MPA exception to the single-file rule)

```
unified-data-studio/
├── launcher.py            # entrypoint: set_page_config + st.navigation only
├── pages/
│   ├── metadata_dax_editor.py
│   ├── security_command_center.py
│   └── theme_ui_studio.py
├── lib/                   # pure logic, ZERO st.* imports (unit-testable)
│   ├── tmdl_io.py         # TMDL parse + line-surgery edit/save
│   ├── csv_loader.py      # encoding-robust CSV/Excel loading, HR mapping
│   ├── rules_engine.py    # access engine, deltas, gap analysis
│   └── theme_builder.py   # theme.json builder, preview HTML, visual.json bulk edit
├── tests/
│   ├── run_tests.py       # 60+ checks, no Streamlit needed
│   └── fixtures/          # sample .tmdl files, visual.json
├── requirements.txt       # streamlit>=1.36 (st.navigation), pandas, openpyxl
└── README.md
```

Rules: `launcher.py` owns `set_page_config` (suite `pages/` must not call
it; standalone `app.py` files use the guarded try/except pattern from the
root guide); session-state keys are prefixed per page (`tmdl_`, `sec_`,
`thu_`) because state is global across MPA pages; `lib/` stays
Streamlit-free.

**Sidebar theme** (in `launcher.py`, injected CSS): emojis on the 5 pillar
headers only, no icons on `st.Page` items; sub-items get a `::before`
colored dot and an accent underline on hover/active, with per-pillar
accents (`--acc`/`--acc-soft`) assigned via
`ul[data-testid="stSidebarNavItems"] > div:nth-of-type(n)` — keep the
`nth-of-type` order in sync with the section dict. Global suite CSS
(`.block-container` top padding) lives in the same style block.

## App 1 — TMDL line-surgery methodology (`lib/tmdl_io.py`)

**Never rewrite a file wholesale.** The parser records the exact line
numbers and raw indentation of every editable property; `build_edit_ops`
diffs working vs parsed objects into `LineOp`s (`replace`, `replace_range`,
`delete_range`, `insert_before`); `apply_line_ops` applies them bottom-up so
line numbers stay valid. Everything else — `lineageTag`, comments, blank
lines, BOM, `\r\n` vs `\n`, trailing newline — is preserved byte-for-byte
(tests assert lineageTag lines are identical after edits).

- **Measure shapes handled:** inline (`measure 'X' = DAX…` + deeper
  continuation lines), `expression:` single-line property, `expression: |`
  block scalar. Single-line → multi-line DAX converts to block form.
- **Description shapes:** `///` block (preferred when both exist),
  `description:` property, absent → a new `///` block is inserted above the
  declaration. Editing an empty description deletes the `///` block/property.
- **Measure renames:** `build_edit_ops(..., new_name=...)` swaps only the
  name token on the declaration line (`_swap_decl_name_token` splits at the
  LAST `=`, preserving the exact separator spacing; quoting style is kept —
  quoted stays quoted, bare stays bare unless the new name needs quotes).
  The token is verified against the parsed name first — if it cannot be
  located safely the rename is skipped rather than risking a corrupt line.
  When DAX changes too on an inline measure, the single declaration-line op
  carries both edits so they never overlap. DAX references are NOT
  cascaded — the UI's Global Find & Replace (`plan_dax_replace`, plain
  substring over every measure expression) patches dependents before save,
  and a warning banner says so. Rename validation (page): non-empty, no
  `]`, no duplicate name in the same table.
- **DAX display normalization:** continuation lines are per-line stripped
  when parsed (v2 behavior); the file keeps the exact text written on save.
- **Quoting:** property rewrites preserve the original quoting style
  (single-quote doubling for TMDL escapes); values needing quotes get them.
- **Safety in the UI:** diff preview per file before save; save requires a
  confirmation checkbox; in-place save only in folder mode; zip mode edits a
  temp copy and downloads the result. `validate_dax` warns (never blocks) on
  unbalanced brackets/quotes. "Discard" restores from the deep-copied parse.
- **Scope:** TMDL only. Legacy `model.bim` stays in the standalone v2
  extractor app.

## App 2 — data contracts & functions

Column contracts are identical to the standalone v4 app (see its
`DEVELOPER_GUIDELINES.md` for the full table): `Work Email`, `Department`,
`Position`, `Store_Access` (`:`-separated, exploded with `.split(':')` +
`.explode()`), `Report_Access` (`;`-separated), `Store_Name` via the master.
Framing is platform-agnostic ("assets", not "stores"); the engine itself is
unchanged: exact `(Department, Position)` match → `*` wildcard → per-email
exceptions win → explode → master join → `NO RULE` rows stay visible.
`compute_deltas` (leavers/joiners/movers, anti-joins with `indicator=True`
on `Work Email`), `gap_analysis` (expected vs audit pairs, both directions).
`warn_unmapped` from v4 was de-streamlit-ified: the lib returns the lists,
the page renders the red warning.

## App 3 — theme schema notes (`lib/theme_builder.py`)

- Theme JSON follows the documented format: top-level `name`,
  `dataColors`, `background`, `foreground`, `tableAccent`, `textClasses`
  (label/callout/title/header), and
  `visualStyles.*.*.{background,border,dropShadow,padding,title}` with
  `{ "solid": { "color": "#…" } }` color wrappers.
- **Radius caveat:** `radius` inside `border` is used by real themes and
  Microsoft's own reference, but one third-party source reports some
  Desktop builds silently ignoring themes that carry it. The builder
  includes it (rounded corners are a requirement); if a build ignores it,
  delete the `radius` key from the exported JSON. The UI says this too.
- **Bulk editor:** scans `visualContainerObjects` in each `visual.json`
  (`background`, `border`, `padding`, `dropShadow`, `title`,
  `visualHeader`), shows current values, applies a preset/custom standard
  only to the chosen properties (deep copy; everything else preserved),
  and zips the results. Presets live in `standard_presets()`.
- Live preview is an HTML/CSS mockup (`render_preview_html`); every widget
  change re-renders it. User-controlled text is HTML-escaped.

## Testing

```bash
cd unified-data-studio
python3 tests/run_tests.py        # 79 lib checks, no Streamlit needed
python3 -m py_compile launcher.py pages/*.py lib/*.py
```

Covered: TMDL parse shapes (tabs/spaces, `///` vs property, inline vs
`expression:` vs block), every edit op type, lineageTag byte-preservation,
BOM/CRLF round-trip, DAX validator, cp1252/utf-8-sig CSV fallback,
`:` explosion, wildcard/exception/`NO RULE`/master-fallback, deltas, gap
analysis both directions, theme build/validate, visual.json scan/apply
idempotency. UI flows were additionally verified with Streamlit's `AppTest`
headless runner (page boot, PBIP folder load, widget→stage→save→file on
disk, theme control wiring) — re-run against a venv with streamlit
installed if the pages change.

## Gotchas for future edits

- The DAX `text_area` / measure-name keys include the selected measure's
  index plus a `dax_nonce` (`tmdl_dax_area_{i}_{n}`) — without this,
  switching measures (or staging a rename / find & replace) shows stale
  widget state. The nonce bumps on every rename/find-replace staging.
- `st.data_editor` writes descriptions back into the working objects on
  every rerun by row position; keep the editor DataFrame in parse order.
- `build_edit_ops` takes the **original** object (it owns the line
  locations) plus the new values — never the mutated working copy.
- `use_container_width=True` is kept (not the newer `width="stretch"`) so
  the app stays compatible with the `streamlit>=1.36` floor.

## Suite apps 4–7 (standalone dirs, wired into `launcher.py`)

Each lives in its own top-level directory with `app.py` (UI) + `*_core.py`
(pure logic) + `tests/run_tests.py` + `requirements.txt` +
`DEVELOPER_GUIDELINES.md`. They are registered in the launcher's sectioned
`st.navigation` via `st.Page("../<dir>/app.py", …, url_path="<unique>")`
— `url_path` is required because every app entrypoint is named `app.py`.
Session prefixes: `ppt4_`, `dd5_`, `san6_`, `pdf7_`.

| # | App | Dir | Core module |
|---|-----|-----|-------------|
| 4 | PPT Playbook Builder | `../auto-ppt-playbook-builder/` | `ppt_core.py` — Pillow annotation, 16:9 slide building, dictionary pagination, image-preserving slide clone + `{{tag}}` mail-merge |
| 5 | SQL Sandbox & Diff Engine | `../data-diff-duckdb-sandbox/` | `diff_core.py` — parquet/csv/xlsx loading, profiler, DuckDB runner, key-based diff (added/deleted/schema/cell-level) |
| 6 | Messy Excel Sanitizer | `../messy-excel-sanitizer/` | `sanitize_core.py` — merged-cell handling, sanitization pipeline, schema validation, concatenation |
| 7 | Comms & PDF Toolkit | `../office-comms-pdf-toolkit/` | `toolkit_core.py` — 5 comms templates, pypdf/reportlab ops (pure-Python, Stlite-safe), Pillow beautifier |
| 8 | Flowchart Studio | `../interactive-flowchart-studio/` | `flow_core.py` — validation, layered layout, standalone interactive HTML viewer, Mermaid/SVG export |
| 9 | Meeting Hub | `../bi-requirement-meeting-hub/` | `meeting_core.py` — SQLite CRUD, triage filters, grouped minutes generator |
| 10 | Prompt & Privacy Hub | `../ai-prompt-privacy-hub/` | `prompt_core.py` — framework prompts, custom templates, reversible masker, repo packer |
| 11 | Snippet Vault | `../knowledge-snippet-vault/` | `vault_core.py` — SQLite snippets/notes, full-text + tag search, cheat-sheet export |
| 12 | Data Quality Watchdog | `../data-quality-watchdog/` | `dq_core.py` — health checks, baseline drift compare, report card |
| 13 | Stlite Sandbox Builder | `../mobile-stlite-sandbox-builder/` | `stlite_core.py` — repo app scanner, multi-file bundler, pinned @stlite/mountable HTML template |

## Future work

- Relationships/hierarchies in the TMDL parser (currently skipped).
- Audit log persistence (SQLite) instead of session state.
- Bulk editor: per-visual-type `objects` (dataLabels, legend, …) standards.
