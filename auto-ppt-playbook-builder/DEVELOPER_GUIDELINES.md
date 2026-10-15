# Developer Guidelines — Auto PPT Playbook Builder

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Standardize and speed up User Playbooks, Training Decks, and Data
Dictionary slides — 100% local via `python-pptx` + `Pillow`. Three tools
(one tab each):

1. **Annotated Screenshot Builder** — numbered callout badges on a
   screenshot (X/Y % sliders) → `.pptx` slide (image left, steps table
   right); slides accumulate into a session deck; optional corporate
   `.pptx` template applies deck-wide.
2. **Data Dictionary to Slides** — CSV upload or pasted Markdown table →
   paginated table slides (configurable 4–10 rows/slide, default 7).
3. **Slide Cloner (Mail-Merge)** — template `.pptx` with `{{tags}}` +
   CSV/Excel dataset → one populated slide per row.

## Layout

```
auto-ppt-playbook-builder/
├── app.py                  # Streamlit UI only (tabs, widgets, downloads)
├── ppt_core.py             # pure logic — no st.*
├── tests/run_tests.py      # 23 checks, no Streamlit needed
└── requirements.txt
```

`app.py` inserts its own directory into `sys.path` so `import ppt_core`
works both standalone (`streamlit run app.py`) and via the suite launcher
(`st.Page("../auto-ppt-playbook-builder/app.py")`). Session keys use the
`ppt4_` prefix. No `st.set_page_config` — the suite launcher owns it.

## Functions & methodology (`ppt_core.py`, all pure)

- `annotate_screenshot(img, callouts)` — Pillow badges: white halo +
  corporate-red circle + bold white number, radius ∝ image size;
  coordinates are % of width/height. Input image never mutated.
- `new_presentation()` — blank 16:9 deck; `load_template(bytes)` — user's
  corporate template; `blank_layout(prs)` — emptiest layout available.
- `add_annotated_slide(prs, img, steps, title)` — image left (~55%, aspect
  kept), steps table right (# + Step, navy header, zebra rows).
- `add_dictionary_slides(prs, columns, rows, rows_per_slide, title_prefix)`
  — chunks rows, one table slide per chunk titled `Prefix (i/n)`.
- `find_tags(prs, slide_idx)` — `{{tag}}` names in first-seen order from
  text frames and tables.
- `clone_slide(prs, src)` — deep-copies shape XML **and re-targets image
  relationships** (`relate_to(..., RT.IMAGE)`), so template pictures survive
  the merge. Placeholders from the blank layout are stripped first.
- `mail_merge(template_bytes, slide_idx, dataset)` — one cloned slide per
  row; run-aware tag replacement (rewrites the first run, clears the rest —
  paragraph formatting survives, intra-paragraph styling does not);
  template slides are removed afterwards, keeping merged output only.
- `parse_markdown_table(text)` — GitHub-style `| cell |` tables; separator
  rows skipped; ragged rows padded/truncated to header width.
- `read_csv_smart(bytes)` — `utf-8-sig → utf-8 → cp1252 → latin-1`.

## App-specific conventions

- Mail-merge tags also match with inner spaces (`{{ Store }}`).
- Missing dataset columns leave their `{{tag}}` untouched (warned in UI).
- Table slides use even column widths and 10–12pt fonts; beyond ~6 columns
  the user should trim the column selection.
- The deck lives in session state — download the `.pptx` before closing.

## Testing

`python3 tests/run_tests.py` covers: badge rendering + input immutability,
annotated-slide shape/table content, pagination counts and last-row content,
tag detection order, merge slide count, tag replacement in text + tables,
missing-tag passthrough, image preservation through clone, markdown parsing
+ rejection, cp1252 CSV fallback. `AppTest` boot verified for `app.py`.

## Future work

- Click-to-place callouts (needs a custom component for image click coords).
- Per-shape animation/transition carry-over in cloned slides.
- Direct `.pptx` → PDF export (needs LibreOffice — out of scope offline).
