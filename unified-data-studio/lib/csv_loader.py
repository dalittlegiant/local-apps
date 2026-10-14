"""Robust tabular file loading. Pure logic — no ``st.*`` calls.

Ported from the Power BI Security & Governance Command Center v4; the
encoding fallback chain is a standing repo convention (see the root
DEVELOPER_GUIDE.md): ``utf-8-sig -> utf-8 -> cp1252 -> latin-1``.
"""

import io

import pandas as pd

# Canonical column names used across the Security Command Center.
EMAIL = "Work Email"
DEPT = "Department"
POS = "Position"
STORE_ACCESS = "Store_Access"   # holds asset codes (exploded to one row each)
STORE_NAME = "Store_Name"       # friendly name resolved via the asset master
REPORT_ACCESS = "Report_Access"

STORE_SEP = ":"   # multi-asset delimiter inside Store_Access, e.g. "A:C"
REPORT_SEP = ";"  # multi-report delimiter inside Report_Access


def split_list(s: str, sep: str) -> list[str]:
    return [p.strip() for p in str(s).split(sep) if p.strip()]


def _require_cols(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def _clean_str_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def read_csv_bytes(raw: bytes) -> tuple[pd.DataFrame, str]:
    """Robust CSV reader: utf-8-sig -> utf-8 -> cp1252 -> latin-1."""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, encoding=enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1"), "latin-1"


def read_table_upload(uploaded) -> pd.DataFrame:
    """Read a CSV or Excel upload into a cleaned string dataframe.

    ``uploaded`` is any file-like with a ``.name`` (Streamlit UploadedFile
    works). The detected encoding is stored on ``df.attrs['source_encoding']``.
    """
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded, dtype=str)
        enc = "excel"
    else:
        df, enc = read_csv_bytes(uploaded.getvalue())
    df = _clean_str_df(df)
    df.attrs["source_encoding"] = enc
    return df


def read_hr_excel(uploaded, mapping: dict[str, str]) -> pd.DataFrame:
    """Read the HR Staff List and rename raw columns to the canonical schema.

    mapping: {"Work Email": <raw col>, "Department": <raw col>,
              "Position": <raw col>}
    """
    df = _clean_str_df(pd.read_excel(uploaded, dtype=str))
    rename = {raw: canon for canon, raw in mapping.items()
              if raw and raw in df.columns}
    df = df.rename(columns=rename)
    _require_cols(df, [EMAIL, DEPT, POS], "HR Staff List (after schema mapping)")
    df = df[df[EMAIL] != ""].drop_duplicates(subset=[EMAIL], keep="last")
    return df
