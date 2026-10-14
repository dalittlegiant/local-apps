# Developer Guidelines — Power BI Metadata Extractor

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Extract Tables, Columns, and Measures (with DAX + descriptions) from a Power BI
semantic model so Kong can write Dashboard Playbooks and spot redundant DAX.
Supports legacy `model.bim` (JSON) and modern TMDL (`definition/tables/*.tmdl`).

## Functions (all pure — no `st.*`)

- `parse_bim(bytes) -> dict` — decodes and JSON-parses a `.bim` file.
- `extract_model_bim(dict) -> [tables]` — walks the TOM JSON tree.
- `parse_tmdl_table(str) -> table | None` — line-based parser for one `.tmdl`
  file. Handles quoted names (`'Total Sales'`), escaped quotes (`'Bob''s'`),
  `///` description blocks, multi-line DAX, and skips non-extracted objects
  (`partition`, `hierarchy`, `ref`, …).
- `detect_pbip_format(Path) -> ("tmdl", [files]) | ("bim", path)` —
  auto-detects under a PBIP root: `*.SemanticModel/definition/tables/*.tmdl`
  first, then `*.SemanticModel/model.bim`. Raises a friendly `ValueError`
  otherwise.
- `extract_from_tmdl_files([Path]) -> (tables, warnings)` — parses each file,
  collecting per-file warnings instead of crashing.
- `to_markdown(tables, source_name, fmt) -> str` — renders the Data Dictionary:
  one `## Table` section each, Columns as a compact table, Measures as `####`
  subsections with `> description` quote + ` ```dax ` fence. Designed for
  direct copy-paste into Playbooks.

Canonical table shape passed between layers:

```python
{
    "name": "Sales",
    "columns": [{"Name": "OrderID", "Data Type": "int64"}, ...],
    "measures": [{"Name": "Total Sales", "Expression": "SUM(...)",
                  "Description": "..."}, ...],
}
```

## UI

- Sidebar radio: "Upload model.bim" vs "PBIP project folder".
- Tabs per table; `st.dataframe` for columns and measures (DAX in a wide text
  column for redundancy review).
- Download button for `documentation.md` + collapsible Markdown preview.

## App-specific conventions

- **TMDL is indentation-based.** The parser is line-oriented, not a full
  grammar. If Microsoft extends TMDL syntax, add the new object type to
  `_TMDL_SKIP_RE` (to ignore) or add a `_TMDL_<TYPE>_RE` + extraction branch
  (to support).
- **Descriptions:** `///` triple-slash blocks take priority over the
  `description:` property when both exist.
- **DAX fidelity:** multi-line DAX is joined with `\n` and preserved verbatim —
  do not reformat it; Kong reviews the raw code for redundancy.

## Testing

UI marker for the harness: `# ====... UI ===`. Cover at minimum: basic table,
multi-line DAX, `///` descriptions, quoted/escaped names, `partition`/`ref`
skipping, empty table, missing table declaration, folder auto-detection
(tmdl + bim), unknown-format folder.

## Future work

- **Relationships:** `definition/relationships.tmdl` is currently ignored —
  parsing `fromColumn`/`toColumn` would enable a model diagram view.
- **Calculated columns / hierarchies:** skipped by `_TMDL_SKIP_RE`; add if needed.
- **DAX redundancy analysis:** automated similarity detection across measure
  expressions — currently manual review only.
