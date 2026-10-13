# Local Apps

A collection of small local web apps. Each lives in its own folder with its own `app.py` and `requirements.txt`.

## Apps

| App | Folder | Description |
|-----|--------|-------------|
| Power BI Metadata Extractor | `power-bi-metadata-extractor/` | Parse a Power BI `model.bim` and extract tables, columns, measures; export to Markdown. |

## Running an app

```bash
cd <app-folder>
pip install -r requirements.txt
streamlit run app.py
```
