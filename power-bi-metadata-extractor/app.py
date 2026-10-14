"""Power BI Report Metadata Extractor.

Parse a Power BI semantic model — either the legacy model.bim (JSON) or the
modern TMDL format (definition/tables/*.tmdl) — and extract tables, columns,
and measures for documentation (Dashboard Playbooks) and DAX redundancy
review.

Input modes:
  1. Upload a single .bim / .json file.
  2. Enter the root path of a PBIP project folder (auto-detects .bim or .tmdl).

Run with: streamlit run app.py
"""

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Power BI Report Metadata Extractor",
    page_icon="📊",
    layout="wide",
)


# ============================================================ .bim (JSON) ===
def parse_bim(file_bytes: bytes) -> dict:
    """Parse raw bytes of a .bim / .json file into a Python dict."""
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


def extract_model_bim(data: dict) -> list[dict]:
    """Extract tables/columns/measures from a model.bim dict."""
    model = data.get("model", data)
    tables = model.get("tables", []) or []
    result = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        columns = [
            {"Name": c.get("name", "<unnamed>"), "Data Type": c.get("dataType", "—")}
            for c in (table.get("columns", []) or [])
            if isinstance(c, dict)
        ]
        measures = [
            {
                "Name": m.get("name", "<unnamed>"),
                "Expression": m.get("expression", "—"),
                "Description": m.get("description", "") or "",
            }
            for m in (table.get("measures", []) or [])
            if isinstance(m, dict)
        ]
        result.append(
            {"name": table.get("name", "<unnamed>"), "columns": columns, "measures": measures}
        )
    return result


# ================================================================ TMDL ===
# TMDL is indentation-based. We parse line-by-line:
#   table Name                 <- indent 0
#       column Name            <- indent N
#           dataType: int64    <- indent > N (property)
#       measure 'Name' = DAX   <- indent N (DAX may continue on deeper lines)
#   /// Description lines      <- triple-slash above an object

_TMDL_TABLE_RE = re.compile(r"^table\s+(.+?)\s*$")
_TMDL_COLUMN_RE = re.compile(r"^column\s+(.+?)\s*$")
_TMDL_MEASURE_RE = re.compile(r"^measure\s+(.+?)\s*=\s*(.*)$")
_TMDL_MEASURE_NODAX_RE = re.compile(r"^measure\s+(.+?)\s*=\s*$")
_TMDL_PROP_RE = re.compile(r"^([A-Za-z][\w]*)\s*:\s*(.*)$")
_TMDL_DESC_RE = re.compile(r"^///\s?(.*)$")
# Object types we parse; everything else (partition, hierarchy, etc.) is skipped.
_TMDL_SKIP_RE = re.compile(
    r"^(partition|hierarchy|level|annotation|ref\s|variation|calculationGroup|"
    r"calculationItem|perspective|role|tablePermission|expression|relationship|"
    r"culture|model|database|dataSource|providerDataSource)\b"
)


def _unquote_tmdl_name(raw: str) -> str:
    """Remove surrounding single quotes and unescape doubled quotes."""
    raw = raw.strip()
    if len(raw) >= 2 and raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    return raw


def parse_tmdl_table(text: str) -> dict | None:
    """Parse one .tmdl table file into {name, columns, measures}.

    Returns None if no table declaration is found.
    """
    lines = text.splitlines()
    table_name: str | None = None
    columns: list[dict] = []
    measures: list[dict] = []

    # Pending triple-slash description block (applies to the next object).
    pending_desc: list[str] = []

    # Current object being filled: dict with keys kind/table/column/measure.
    current: dict | None = None
    current_indent: int = -1
    # For measures: are we still collecting multi-line DAX?
    dax_indent: int = -1

    def flush_current():
        nonlocal current, dax_indent
        if current and current["kind"] == "measure":
            expr = "\n".join(current["dax_lines"]).strip()
            measures.append(
                {
                    "Name": current["name"],
                    "Expression": expr if expr else "—",
                    "Description": current["description"],
                }
            )
        elif current and current["kind"] == "column":
            columns.append(
                {"Name": current["name"], "Data Type": current.get("dataType", "—")}
            )
        current = None
        dax_indent = -1

    for raw_line in lines:
        if not raw_line.strip():
            continue  # blank lines never end a DAX block in practice; keep them out
        indent = len(raw_line) - len(raw_line.lstrip(" \t"))
        stripped = raw_line.strip()

        # Skip full-line comments that are not descriptions.
        if stripped.startswith("//") and not stripped.startswith("///"):
            continue

        # Triple-slash description block.
        m = _TMDL_DESC_RE.match(stripped)
        if m:
            pending_desc.append(m.group(1))
            continue

        # Table declaration at indent 0.
        if indent == 0:
            m = _TMDL_TABLE_RE.match(stripped)
            if m:
                flush_current()
                table_name = _unquote_tmdl_name(m.group(1))
                pending_desc = []  # table-level desc not needed for our output
                continue
            # Anything else at indent 0 ends the table scope.
            flush_current()
            pending_desc = []
            continue

        # Skip whole object types we don't extract (partition, hierarchy, ...).
        if _TMDL_SKIP_RE.match(stripped):
            flush_current()
            # Skip its entire indented subtree.
            skip_indent = indent
            # Mark so following deeper lines are ignored until dedent.
            current = {"kind": "skip", "indent": skip_indent}
            current_indent = indent
            pending_desc = []
            continue
        if current and current.get("kind") == "skip":
            if indent > current["indent"]:
                continue
            else:
                current = None  # dedented out of the skipped block

        # New column / measure declaration (same or shallower indent than current).
        m_col = _TMDL_COLUMN_RE.match(stripped)
        m_meas = _TMDL_MEASURE_RE.match(stripped)
        if m_col or m_meas:
            # A new declaration at <= current indent closes the previous object.
            if current and indent <= current_indent:
                flush_current()
            desc = "\n".join(pending_desc).strip()
            pending_desc = []
            if m_col:
                current = {
                    "kind": "column",
                    "name": _unquote_tmdl_name(m_col.group(1)),
                    "description": desc,
                }
            else:
                dax_first = m_meas.group(2).strip()
                current = {
                    "kind": "measure",
                    "name": _unquote_tmdl_name(m_meas.group(1)),
                    "description": desc,
                    "dax_lines": [dax_first] if dax_first else [],
                }
                dax_indent = indent
            current_indent = indent
            continue

        # Inside a current object: property or DAX continuation.
        if current and indent > current_indent:
            m_prop = _TMDL_PROP_RE.match(stripped)
            # A line is a property only if it looks like `word:` AND we are not
            # in the middle of a multi-line DAX expression. Heuristic: if the
            # current measure already has DAX lines, a `word:` line at deeper
            # indent is ambiguous — TMDL puts properties after the full DAX, so
            # treat `word:` as a property only when it matches known property
            # names; otherwise keep it as DAX.
            known_props = {
                "dataType", "datatype", "description", "formatString",
                "displayFolder", "isHidden", "summarizeBy", "sourceColumn",
                "isKey", "isNullable", "lineageTag",
            }
            if m_prop and m_prop.group(1) in known_props:
                key = m_prop.group(1)
                val = m_prop.group(2).strip()
                if current["kind"] == "column" and key.lower() == "datatype":
                    current["dataType"] = val
                elif key.lower() == "description" and not current["description"]:
                    current["description"] = val
                # Other properties are ignored for documentation purposes.
                continue
            # Otherwise: DAX continuation line (measure only).
            if current["kind"] == "measure":
                current["dax_lines"].append(stripped)
                continue
            # Unknown deeper line inside a column: ignore.
            continue

        # Dedented to an unexpected level: close current object.
        flush_current()
        pending_desc = []

    flush_current()

    if table_name is None:
        return None
    return {"name": table_name, "columns": columns, "measures": measures}


def detect_pbip_format(root: Path) -> tuple[str, Path | list[Path]]:
    """Auto-detect the semantic-model format under a PBIP project root.

    Returns ("tmdl", [tmdl files]) or ("bim", bim_path).
    Raises ValueError if nothing recognizable is found.
    """
    if not root.exists():
        raise ValueError(f"Path does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    # Newer TMDL layout: <root>/*.SemanticModel/definition/tables/*.tmdl
    # (also tolerate <root>/definition/tables directly)
    tmdl_dirs: list[Path] = []
    for sem in root.glob("*.SemanticModel"):
        d = sem / "definition" / "tables"
        if d.is_dir():
            tmdl_dirs.append(d)
    direct = root / "definition" / "tables"
    if direct.is_dir():
        tmdl_dirs.append(direct)

    tmdl_files: list[Path] = []
    for d in tmdl_dirs:
        tmdl_files.extend(sorted(d.glob("*.tmdl")))
    # Skip non-table TMDL files that may sit in tables/ (defensive).
    tmdl_files = [f for f in tmdl_files if f.is_file()]
    if tmdl_files:
        return "tmdl", tmdl_files

    # Legacy layout: <root>/*.SemanticModel/model.bim (or directly under root)
    bim_candidates: list[Path] = []
    for sem in root.glob("*.SemanticModel"):
        b = sem / "model.bim"
        if b.is_file():
            bim_candidates.append(b)
    direct_bim = root / "model.bim"
    if direct_bim.is_file():
        bim_candidates.append(direct_bim)
    if bim_candidates:
        return "bim", bim_candidates[0]

    raise ValueError(
        "No model.bim and no definition/tables/*.tmdl found under this folder. "
        "Expected a PBIP project root (containing *.SemanticModel/). "
        "Unknown formats such as .abf / .pbism are not parseable and were skipped."
    )


def extract_from_tmdl_files(files: list[Path]) -> tuple[list[dict], list[str]]:
    """Parse every .tmdl table file. Returns (tables, warnings)."""
    tables: list[dict] = []
    warnings: list[str] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"Skipped {f.name}: cannot read ({exc})")
            continue
        parsed = parse_tmdl_table(text)
        if parsed is None:
            warnings.append(f"Skipped {f.name}: no table declaration found")
            continue
        tables.append(parsed)
    return tables, warnings


# ============================================================ Markdown ===
def to_markdown(tables: list[dict], source_name: str, fmt: str) -> str:
    """Render extracted metadata as a Data-Dictionary Markdown document."""
    total_cols = sum(len(t["columns"]) for t in tables)
    total_meas = sum(len(t["measures"]) for t in tables)
    lines = [
        f"# Data Dictionary — {source_name}",
        "",
        f"_Source format: {fmt} · Tables: {len(tables)} · "
        f"Columns: {total_cols} · Measures: {total_meas}_",
        "",
        "---",
        "",
    ]
    for table in tables:
        lines.append(f"## Table: `{table['name']}`")
        lines.append("")
        lines.append("### Columns")
        lines.append("")
        if table["columns"]:
            lines.append("| Column | Data Type |")
            lines.append("| --- | --- |")
            for col in table["columns"]:
                lines.append(f"| `{col['Name']}` | {col['Data Type']} |")
        else:
            lines.append("_No columns found._")
        lines.append("")
        lines.append("### Measures")
        lines.append("")
        if table["measures"]:
            for meas in table["measures"]:
                lines.append(f"#### `{meas['Name']}`")
                lines.append("")
                if meas["Description"]:
                    lines.append(f"> {meas['Description']}")
                    lines.append("")
                lines.append("```dax")
                lines.append(str(meas["Expression"]))
                lines.append("```")
                lines.append("")
        else:
            lines.append("_No measures found._")
            lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)


# ================================================================= UI ===
with st.sidebar:
    st.header("📁 Input")
    mode = st.radio(
        "Source type",
        ("Upload model.bim", "PBIP project folder"),
        help="Upload a single .bim file, or point at a PBIP project root for auto-detection.",
    )
    uploaded = None
    folder_path = ""
    if mode == "Upload model.bim":
        uploaded = st.file_uploader(
            "Choose a .bim or .json file",
            type=["bim", "json"],
            help="From a PBIP project: <report>.SemanticModel/model.bim",
        )
    else:
        folder_path = st.text_input(
            "PBIP project root path",
            placeholder=r"C:\Projects\MyReport  or  /home/user/MyReport",
            help="Folder containing *.SemanticModel/. Auto-detects model.bim or definition/tables/*.tmdl.",
        )
    st.caption("Parsing happens locally — nothing is sent anywhere.")


st.title("📊 Power BI Report Metadata Extractor")
st.caption(
    "Extract tables, columns and measures from `model.bim` (JSON) or TMDL "
    "(`definition/tables/*.tmdl`) into a documentation-ready Data Dictionary."
)

tables: list[dict] = []
warnings: list[str] = []
source_name = ""
fmt = ""

try:
    if mode == "Upload model.bim":
        if uploaded is None:
            st.info("👈 Upload a `.bim` or `.json` file from the sidebar to get started.")
            st.stop()
        data = parse_bim(uploaded.getvalue())
        tables = extract_model_bim(data)
        source_name = uploaded.name
        fmt = "model.bim (JSON)"
    else:
        if not folder_path.strip():
            st.info("👈 Enter the PBIP project root path in the sidebar to get started.")
            st.stop()
        root = Path(folder_path.strip()).expanduser()
        detected, payload = detect_pbip_format(root)
        if detected == "bim":
            data = parse_bim(Path(payload).read_bytes())
            tables = extract_model_bim(data)
            source_name = Path(payload).name
            fmt = "model.bim (JSON)"
        else:
            tables, warnings = extract_from_tmdl_files(payload)  # type: ignore[arg-type]
            source_name = root.name
            fmt = f"TMDL ({len(payload)} files)"  # type: ignore[arg-type]
except ValueError as exc:
    st.error(f"⚠️ {exc}")
    st.stop()
except Exception as exc:  # defensive: never crash the app on odd input
    st.error(f"⚠️ Unexpected error: {exc}")
    st.stop()

for w in warnings:
    st.warning(w)

if not tables:
    st.warning("No tables found. Is this a valid Power BI semantic model?")
    st.stop()

st.success(f"Parsed **{len(tables)}** table(s) from `{source_name}` ({fmt}).")

# ---- per-table display -------------------------------------------------
tabs = st.tabs([t["name"] for t in tables])
for tab, table in zip(tabs, tables):
    with tab:
        st.subheader(f"Table: {table['name']}")

        st.markdown("**Columns**")
        if table["columns"]:
            st.dataframe(pd.DataFrame(table["columns"]), use_container_width=True)
        else:
            st.info("No columns in this table.")

        st.markdown("**Measures** — full DAX shown for redundancy review")
        if table["measures"]:
            st.dataframe(
                pd.DataFrame(table["measures"]),
                use_container_width=True,
                column_config={
                    "Expression": st.column_config.TextColumn("Expression (DAX)", width="large"),
                    "Description": st.column_config.TextColumn("Description", width="medium"),
                },
            )
        else:
            st.info("No measures in this table.")

# ---- export -------------------------------------------------------------
st.divider()
md_text = to_markdown(tables, source_name, fmt)
st.download_button(
    label="⬇️ Download Data Dictionary (Markdown)",
    data=md_text.encode("utf-8"),
    file_name="documentation.md",
    mime="text/markdown",
)
with st.expander("Preview Markdown"):
    st.code(md_text[:6000] + ("…" if len(md_text) > 6000 else ""), language="markdown")
