"""Power BI Report Metadata Extractor.

Parse a Power BI model.bim file (from a PBIP project directory) and extract
the data model metadata: tables, columns, and measures. Displays the results
in the UI and allows export to Markdown.

Run with: streamlit run app.py
"""

import io
import json

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Power BI Report Metadata Extractor",
    page_icon="📊",
    layout="wide",
)


def parse_bim(file_bytes: bytes) -> dict:
    """Parse raw bytes of a .bim / .json file into a Python dict.

    Raises:
        ValueError: if the content is not valid JSON or not a dict.
    """
    try:
        text = file_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Could not decode file as UTF-8: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object.")
    return data


def extract_model(data: dict) -> list[dict]:
    """Extract tables, columns and measures from a model.bim dict.

    Returns a list of dicts: {name, columns: [...], measures: [...]} where each
    column is {name, data_type} and each measure is {name, expression, description}.
    """
    model = data.get("model", data)  # tolerate both wrapped and bare shapes
    tables = model.get("tables", []) or []

    result = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        t_name = table.get("name", "<unnamed>")

        columns = []
        for col in table.get("columns", []) or []:
            if not isinstance(col, dict):
                continue
            columns.append(
                {
                    "Name": col.get("name", "<unnamed>"),
                    "Data Type": col.get("dataType", "—"),
                }
            )

        measures = []
        for meas in table.get("measures", []) or []:
            if not isinstance(meas, dict):
                continue
            measures.append(
                {
                    "Name": meas.get("name", "<unnamed>"),
                    "Expression": meas.get("expression", "—"),
                    "Description": meas.get("description", "") or "",
                }
            )

        result.append({"name": t_name, "columns": columns, "measures": measures})
    return result


def to_markdown(tables: list[dict], source_name: str) -> str:
    """Render extracted metadata as a Markdown document."""
    lines = [
        f"# Power BI Model Metadata — {source_name}",
        "",
        f"_Tables: {len(tables)}_",
        "",
    ]
    for table in tables:
        lines.append(f"## Table: {table['name']}")
        lines.append("")
        lines.append("### Columns")
        lines.append("")
        if table["columns"]:
            lines.append("| Name | Data Type |")
            lines.append("| --- | --- |")
            for col in table["columns"]:
                lines.append(f"| {col['Name']} | {col['Data Type']} |")
        else:
            lines.append("_No columns found._")
        lines.append("")
        lines.append("### Measures")
        lines.append("")
        if table["measures"]:
            lines.append("| Name | Expression | Description |")
            lines.append("| --- | --- | --- |")
            for meas in table["measures"]:
                expr = str(meas["Expression"]).replace("\n", "<br>")
                desc = str(meas["Description"]).replace("\n", "<br>")
                lines.append(f"| {meas['Name']} | `{expr}` | {desc} |")
        else:
            lines.append("_No measures found._")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------- sidebar ---
with st.sidebar:
    st.header("📁 Upload model.bim")
    uploaded = st.file_uploader(
        "Choose a .bim or .json file",
        type=["bim", "json"],
        help="From a PBIP project: <report>.SemanticModel/model.bim",
    )
    st.caption("The file is parsed locally in your browser session — nothing is sent anywhere.")


# ------------------------------------------------------------------ main ----
st.title("📊 Power BI Report Metadata Extractor")
st.caption("Upload a `model.bim` to inspect tables, columns and measures, then export as Markdown.")

if uploaded is None:
    st.info("👈 Upload a `.bim` or `.json` file from the sidebar to get started.")
    st.stop()

try:
    raw = uploaded.getvalue()
    data = parse_bim(raw)
    tables = extract_model(data)
except ValueError as exc:
    st.error(f"⚠️ {exc}")
    st.stop()
except Exception as exc:  # defensive: never crash the app on odd input
    st.error(f"⚠️ Unexpected error while parsing: {exc}")
    st.stop()

if not tables:
    st.warning("No tables found in this file. Is it a valid Power BI `model.bim`?")
    st.stop()

st.success(f"Parsed **{len(tables)}** table(s) from `{uploaded.name}`.")

tabs = st.tabs([t["name"] for t in tables])
for tab, table in zip(tabs, tables):
    with tab:
        st.subheader(f"Table: {table['name']}")

        st.markdown("**Columns**")
        if table["columns"]:
            st.dataframe(pd.DataFrame(table["columns"]), use_container_width=True)
        else:
            st.info("No columns in this table.")

        st.markdown("**Measures**")
        if table["measures"]:
            st.dataframe(pd.DataFrame(table["measures"]), use_container_width=True)
        else:
            st.info("No measures in this table.")

st.divider()
md_text = to_markdown(tables, uploaded.name)
st.download_button(
    label="⬇️ Download documentation.md",
    data=md_text.encode("utf-8"),
    file_name="documentation.md",
    mime="text/markdown",
)
with st.expander("Preview Markdown"):
    st.code(md_text[:4000] + ("…" if len(md_text) > 4000 else ""), language="markdown")
