# Local Apps

A collection of small local web apps. Each lives in its own folder with its own `app.py` and `requirements.txt`.

Shared developer conventions live in [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md); each app's own `DEVELOPER_GUIDELINES.md` covers its schema and logic.

## Apps

| App | Folder | Description |
|-----|--------|-------------|
| Power BI Metadata Extractor | `power-bi-metadata-extractor/` | Parse a Power BI `model.bim` and extract tables, columns, measures; export to Markdown. |
| Power BI Security & Governance Command Center | `power-bi-security-command-center/` | Local RLS engine (store + position rules), delta tracking (joiners/leavers/movers), access audit register with gap analysis. |
| Dav Data Studio (unified MPA) | `unified-data-studio/` | One launcher, seven apps: PBIP Metadata & DAX Editor, platform-agnostic Security Command Center, Power BI Theme & UI Studio — plus the four below, wired into the same sidebar. Run with `streamlit run launcher.py` (from `unified-data-studio/`). |
| PPT Playbook Builder | `auto-ppt-playbook-builder/` | Annotated screenshot slides, data-dictionary pagination, `{{tag}}` mail-merge for PowerPoint. |
| SQL Sandbox & Diff Engine | `data-diff-duckdb-sandbox/` | DuckDB SQL over local parquet/CSV/Excel + dataset version diff (added/deleted/schema/cell-level). |
| Messy Excel Sanitizer | `messy-excel-sanitizer/` | Batch Excel/CSV intake, sanitization pipeline, schema validation, master dataset export. |
| Comms & PDF Toolkit | `office-comms-pdf-toolkit/` | Corporate comms drafts + checklists, offline PDF merge/split/watermark/table-extract, screenshot beautifier. |

## Running an app

```bash
cd <app-folder>
pip install -r requirements.txt
streamlit run app.py
```
