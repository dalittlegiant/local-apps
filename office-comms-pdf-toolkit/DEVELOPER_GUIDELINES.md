# Developer Guidelines — Office Comms & PDF Toolkit

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Speed up routine analyst/officer communications and handle sensitive
PDFs/screenshots 100% locally. Three tools (one tab each):

1. **Comms Studio** — 5 built-in templates (New Dashboard Launch, Training
   Invitation, Venue/Schedule Change, Data Refresh Delay Notice,
   Governance/Audit Reminder): fill variables → email + Teams drafts +
   interactive pre-launch checklist with progress.
2. **PDF Toolkit** — merge, split/extract page ranges, diagonal text
   watermark, multi-strategy table extraction → Excel (pdfplumber
   grid/text → PyMuPDF → pypdf layout fallback, with an Auto /
   Grid-Bordered / Borderless mode toggle and per-table strategy labels).
3. **Screenshot Beautifier** — batch trim/padding/rounded-corners/drop-shadow
   (Pillow), per-image + zip download.

## Layout

```
office-comms-pdf-toolkit/
├── app.py                  # Streamlit UI only
├── toolkit_core.py         # pure logic — no st.*
├── tests/run_tests.py      # 46 checks, no Streamlit needed
└── requirements.txt        # + pypdf, reportlab, Pillow, pdfplumber,
                             # pymupdf (desktop). pdfplumber/pymupdf are
                             # dropped in Stlite/WASM exports — see below.
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`pdf7_` prefix; no `st.set_page_config` (suite launcher owns it).

## Functions & methodology (`toolkit_core.py`, all pure)

- `TEMPLATES` — each scenario: `variables` (name/label/default),
  `subject`, `email_body`, `teams_message`, `checklist`. Rendered with
  `str.format`; templates contain no literal braces.
- `render_comms(key, values)` → `{subject, email, teams, checklist}`.
- `merge_pdfs([bytes])` — order-preserving; invalid files raise
  `ValueError` naming the file number.
- `parse_page_range("1-3,5", n)` — 1-based spec → 0-based sorted unique
  pages; rejects `0`, reversed/over-range/non-numeric specs with messages.
- `split_pdf(data, pages)`, `add_watermark(data, text, opacity, font_size)`
  — watermark is a per-page reportlab overlay (30° diagonal, centered),
  sized to each page's mediabox, merged via pypdf.
- `extract_tables(data, mode="auto")` → `[(page, table_idx, df, strategy)]`;
  first row becomes the header (deduped). Per-page cascade, first valid
  strategy wins — a detection counts when ≥2 non-empty rows and ≥2 columns
  survive (all-empty spacer rows are dropped):
  - `auto`: pdfplumber `lines`/`lines` ("grid") → pdfplumber `text`/`text`
    with tightened tolerances ("text") → PyMuPDF `find_tables()` ("pymupdf")
    → PyMuPDF text/text ("pymupdf-text") → legacy pypdf `layout` heuristic
    ("legacy": runs of 2+ spaces delimit columns, blank lines delimit
    tables, single-column blocks skipped as prose).
  - `grid`: bordered strategies only (pdfplumber lines, PyMuPDF grid).
  - `borderless`: text-aligned strategies only (pdfplumber text, PyMuPDF
    text). Forced modes do NOT fall back to legacy.
  `STRATEGY_LABELS` maps the strategy key to the UI display name.
  pdfplumber/PyMuPDF are imported lazily — if either is missing, its
  strategies are skipped and the pipeline degrades gracefully.
- `tables_to_excel` writes one sheet per table (`p{page}_t{idx}`, ≤31 chars).
- Stlite/WASM note: `mobile-stlite-sandbox-builder` drops `pdfplumber`,
  `pypdfium2`, and `pymupdf` from the generated HTML requirements (no
  Pyodide wheels), so browser exports transparently use the legacy
  pure-Python heuristic.
- `beautify(img, opts)` — auto-trim via `ImageChops.difference` against the
  corner color, manual % margin crop, padding canvas, rounded-corner alpha
  mask, drop shadow (blurred black rounded rect, offset). Returns RGBA.

## App-specific conventions

- Checklist state persists per template via widget keys — generate once,
  tick through at your own pace.
- Drafts render into `st.code` blocks for one-tap copying.
- Beautifier outputs PNG (RGBA needed for corners/shadow).

## Testing

`python3 tests/run_tests.py` covers: all 5 templates render with zero
unfilled `{vars}`, custom values propagate, merge counts + rejections,
range parsing + 5 rejection cases, split/watermark page preservation,
table header/rows extraction + per-table strategy labels, synthetic
bordered PDF → `grid` strategy, synthetic borderless (shaded, no lines)
PDF → auto falls back past grid with correct content, forced
`grid`/`borderless` mode semantics, bad-mode rejection, beautifier
trim/pad/corner/shadow/crop geometry. `AppTest` boot verified for
`app.py` (incl. the Extraction-mode radio).

## Future work

- Custom user-defined comms templates (stored locally as JSON).
- PDF redaction (burn rectangles over text regions).
- Beautifier presets ("deck-ready", "Teams post").
