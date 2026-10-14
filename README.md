# Local Apps

A collection of small local web apps. Each lives in its own folder with its own `app.py` and `requirements.txt`.

Shared developer conventions live in [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md); each app's own `DEVELOPER_GUIDELINES.md` covers its schema and logic.

## Apps

| App | Folder | Description |
|-----|--------|-------------|
| Power BI Metadata Extractor | `power-bi-metadata-extractor/` | Parse a Power BI `model.bim` and extract tables, columns, measures; export to Markdown. |
| Power BI Security & Governance Command Center | `power-bi-security-command-center/` | Local RLS engine (store + position rules), delta tracking (joiners/leavers/movers), access audit register with gap analysis. |

## Running an app

```bash
cd <app-folder>
pip install -r requirements.txt
streamlit run app.py
```
