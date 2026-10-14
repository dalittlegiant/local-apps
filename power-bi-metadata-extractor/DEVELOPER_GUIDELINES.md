# Developer Guidelines — Power BI Metadata Extractor

## Purpose

This app extracts Tables, Columns, and Measures (with DAX + descriptions) from a
Power BI semantic model so Kong can write Dashboard Playbooks and spot redundant
DAX. It supports both the legacy `model.bim` (JSON) format and the modern TMDL
(`definition/tables/*.tmdl`) format.

## Project layout

```
power-bi-metadata-extractor/
├── app.py                  # The entire app (single file, Streamlit)
├── requirements.txt        # streamlit, pandas
└── DEVELOPER_GUIDELINES.md # This file
```

Run locally with:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Architecture

`app.py` is organized in layers, top to bottom:

1. **Parsers** (pure functions, no Streamlit calls)
   - `parse_bim(bytes) -> dict` — decodes and JSON-parses a `.bim` file.
   - `extract_model_bim(dict) -> [tables]` — walks the TOM JSON tree.
   - `parse_tmdl_table(str) -> table | None` — line-based TMDL parser for one
     `.tmdl` file. Handles quoted names (`'Total Sales'`), escaped quotes
     (`'Bob''s'`), `///` description blocks, multi-line DAX, and skips
     non-extracted objects (`partition`, `hierarchy`, `ref`, …).
   - `detect_pbip_format(Path) -> ("tmdl", [files]) | ("bim", path)` —
     auto-detects the format under a PBIP root. Looks for
     `*.SemanticModel/definition/tables/*.tmdl` first, then
     `*.SemanticModel/model.bim`. Raises a friendly `ValueError` otherwise.
   - `extract_from_tmdl_files([Path]) -> (tables, warnings)` — parses each
     file, collecting per-file warnings instead of crashing.
2. **Markdown export**
   - `to_markdown(tables, source_name, fmt) -> str` — renders a Data Dictionary:
     one `## Table` section each, Columns as a compact table, Measures as
     `####` subsections with `> description` quote + ```` ```dax ```` code fence.
     Designed for direct copy-paste into Playbooks.
3. **UI** (Streamlit, at the bottom of the file)
   - Sidebar radio: "Upload model.bim" vs "PBIP project folder".
   - Tabs per table; `st.dataframe` for columns and measures (DAX in a wide
     text column for redundancy review).
   - Download button for `documentation.md` + collapsible Markdown preview.

The canonical table shape passed between layers is:

```python
{
    "name": "Sales",
    "columns": [{"Name": "OrderID", "Data Type": "int64"}, ...],
    "measures": [{"Name": "Total Sales", "Expression": "SUM(...)",
                  "Description": "..."}, ...],
}
```

## Conventions

- **Parsers stay pure.** No `st.*` calls above the `# UI` section — this keeps
  them unit-testable without Streamlit installed (see testing below).
- **Never crash on bad input.** Every parser raises `ValueError` with a human
  message; the UI catches it and shows `st.error` / `st.warning`. Unknown files
  (`.abf`, `.pbism`, stray `.txt`) are skipped with a warning, never fatal.
- **TMDL is indentation-based.** The parser is line-oriented, not a full grammar.
  If Microsoft extends TMDL syntax, add the new object type to `_TMDL_SKIP_RE`
  (to ignore) or add a new `_TMDL_<TYPE>_RE` + extraction branch (to support).
- **Descriptions:** `///` triple-slash blocks take priority over the
  `description:` property when both exist.
- **DAX fidelity:** multi-line DAX is joined with `\n` and preserved verbatim —
  do not reformat it; Kong reviews the raw code for redundancy.

## Testing

Streamlit is not required to test the parsers. Extract the pure section and
`exec` it, e.g.:

```python
src = open('app.py').read()
pure = src[:src.index("# ====" + "=" * 60 + " UI ===")]
pure = pure.replace("import pandas as pd\nimport streamlit as st\n", "")
pure = re.sub(r'st\.set_page_config\(.*?\)\n', '', pure, flags=re.S)
ns = {}
exec(pure, ns)
# now use ns['parse_tmdl_table'], ns['detect_pbip_format'], etc.
```

Cover at minimum: basic table, multi-line DAX, `///` descriptions, quoted /
escaped names, `partition`/`ref` skipping, empty table, missing table
declaration, folder auto-detection (tmdl + bim), unknown-format folder.

## Future work

- **Relationships:** `definition/relationships.tmdl` is currently ignored. Parsing
  `fromColumn` / `toColumn` would enable a model diagram view.
- **Calculated columns / hierarchies:** skipped by `_TMDL_SKIP_RE`; add if Kong
  needs them in the dictionary.
- **DAX redundancy analysis:** automated similarity detection across measure
  expressions (e.g., normalized token comparison) — currently manual review only.
- **model.tmdl:** culture / default settings live here; not needed for the
  dictionary today.
