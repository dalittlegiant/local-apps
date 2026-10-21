"""Core logic for the Data Diff & DuckDB Sandbox. Pure — no ``st.*`` calls.

Covers: upload loading (parquet/csv/xlsx), temp-file staging for large
uploads, DuckDB-native profiling, DuckDB SQL execution, and the dataset
version diff engine (added/deleted rows, schema discrepancies, cell-level
changes on primary keys).
"""

import io
import os
import re
import tempfile
from pathlib import Path

import pandas as pd

MAX_CHANGED_CELLS = 10_000


# ------------------------------------------------------------ loading
def load_upload(name: str, raw: bytes, sheet: str | int = 0) -> pd.DataFrame:
    """Read an uploaded file into a DataFrame. Raises ValueError on failure."""
    lname = name.lower()
    try:
        if lname.endswith(".parquet"):
            return pd.read_parquet(io.BytesIO(raw))
        if lname.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(raw), sheet_name=sheet, dtype=object)
        if lname.endswith(".csv"):
            for enc in ("utf-8-sig", "utf-8", "cp1252"):
                try:
                    return pd.read_csv(io.BytesIO(raw), dtype=str, encoding=enc)
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Could not read {name}: {exc}") from exc
    raise ValueError(f"Unsupported file type: {name} "
                     "(use .parquet, .csv, or .xlsx)")


def excel_sheets(raw: bytes) -> list[str]:
    """Sheet names of an uploaded workbook."""
    try:
        return pd.ExcelFile(io.BytesIO(raw)).sheet_names
    except Exception as exc:
        raise ValueError(f"Could not list sheets: {exc}") from exc


def sanitize_table_name(name: str) -> str:
    base = re.sub(r"\.[^.]+$", "", name)          # drop extension
    base = re.sub(r"[^0-9a-zA-Z]+", "_", base).strip("_").lower()
    if not base:
        base = "table"
    if base[0].isdigit():
        base = "t_" + base
    return base


# --------------------------------------- temp staging for large uploads
def write_upload_to_temp(name: str, raw: bytes) -> str:
    """Stage uploaded bytes in the OS temp dir (outside the repo).

    Returns the temp path. The caller owns cleanup (delete when the table
    is dropped). Temp files are never inside the repo, so they can never
    be committed.
    """
    suffix = Path(name).suffix.lower() or ".bin"
    fd, path = tempfile.mkstemp(prefix="dd5_", suffix=suffix)
    os.close(fd)
    with open(path, "wb") as fh:
        fh.write(raw)
    return path


def duckdb_source_clause(path: str, name: str, all_varchar: bool = False) -> str:
    """A FROM-clause fragment letting DuckDB scan the staged file directly.

    No pandas round-trip: DuckDB reads parquet/csv natively, so a 300MB
    file never becomes a 300MB DataFrame in Python memory.

    ``all_varchar=True`` (CSV only) adds ``all_varchar=true`` to
    ``read_csv_auto`` — Safe Mode: every column is read as VARCHAR, so
    type inference is bypassed and a file whose deep rows violate the
    sniffed types (e.g. a string in a BIGINT column) still loads. The
    trade-off is that all values arrive as text.
    """
    q = path.replace("'", "''")
    lname = name.lower()
    if lname.endswith(".parquet"):
        return f"read_parquet('{q}')"
    if lname.endswith(".csv"):
        if all_varchar:
            return f"read_csv_auto('{q}', all_varchar=true)"
        return f"read_csv_auto('{q}')"
    raise ValueError(f"DuckDB cannot scan {name} directly (use .parquet/.csv).")


def profile_duckdb(con, tname: str) -> dict:
    """Instant profiler that runs entirely inside DuckDB.

    Single-pass aggregation — the file is never materialized as a
    DataFrame. Returns the same shape as profile_df() so profile_frame()
    renders it unchanged.
    """
    desc = con.execute(f'DESCRIBE SELECT * FROM "{tname}"').fetchall()
    names = [str(r[0]) for r in desc]
    dtypes = [str(r[1]) for r in desc]
    bits = ["COUNT(*) AS _n"]
    for i, c in enumerate(names):
        q = c.replace('"', '""')
        bits.append(f'COUNT(*) - COUNT("{q}") AS _nl{i}')
        bits.append(f'COUNT(DISTINCT "{q}") AS _uq{i}')
    row = con.execute(f'SELECT {", ".join(bits)} FROM "{tname}"').fetchone()
    n = int(row[0])
    columns = []
    for i, (c, typ) in enumerate(zip(names, dtypes)):
        nulls = int(row[1 + 2 * i])
        columns.append({
            "column": c,
            "dtype": typ,
            "null_count": nulls,
            "null_pct": round(nulls / n * 100, 2) if n else 0.0,
            "n_unique": int(row[2 + 2 * i]),
        })
    return {"rows": n, "cols": len(names), "memory_bytes": 0,
            "columns": columns}


# ---------------------------------------------------------- profiling
def profile_df(df: pd.DataFrame) -> dict:
    """Instant profiler: shape, memory, per-column dtype/nulls/uniques."""
    n = len(df)
    cols = []
    for c in df.columns:
        s = df[c]
        nulls = int(s.isna().sum())
        cols.append({
            "column": str(c),
            "dtype": str(s.dtype),
            "null_count": nulls,
            "null_pct": round(nulls / n * 100, 2) if n else 0.0,
            "n_unique": int(s.nunique(dropna=True)),
        })
    return {
        "rows": n,
        "cols": len(df.columns),
        "memory_bytes": int(df.memory_usage(deep=True).sum()),
        "columns": cols,
    }


def profile_frame(profile: dict) -> pd.DataFrame:
    return pd.DataFrame(profile["columns"],
                        columns=["column", "dtype", "null_count", "null_pct",
                                 "n_unique"])


def run_sql(con, sql: str) -> pd.DataFrame:
    """Execute SQL on a DuckDB connection. Raises ValueError with the DB error."""
    if not sql.strip():
        raise ValueError("SQL is empty.")
    try:
        return con.execute(sql).fetchdf()
    except Exception as exc:
        raise ValueError(f"SQL error: {exc}") from exc


# -------------------------------------------------------- diff engine
def _key_str(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """String-cast key columns so int/str key mismatches still join."""
    df = df.copy()
    for k in keys:
        df[k] = df[k].astype(str)
    return df


def diff_datasets(old: pd.DataFrame, new: pd.DataFrame,
                  keys: list[str]) -> dict:
    """Version diff on primary key(s).

    Returns {"added", "deleted", "changed_cells", "schema", "summary",
             "warnings"}. Keys are compared as strings to survive dtype drift.
    """
    warnings: list[str] = []
    if not keys:
        raise ValueError("Pick at least one key column.")
    for k in keys:
        if k not in old.columns or k not in new.columns:
            raise ValueError(f"Key column '{k}' must exist in both datasets.")

    old_k, new_k = _key_str(old, keys), _key_str(new, keys)
    if old_k.duplicated(subset=keys).any():
        warnings.append("Old dataset has duplicate key values — "
                        "diffs on duplicates are unreliable.")
    if new_k.duplicated(subset=keys).any():
        warnings.append("New dataset has duplicate key values — "
                        "diffs on duplicates are unreliable.")

    # --- schema discrepancies
    old_cols, new_cols = list(old.columns), list(new.columns)
    schema_rows = []
    for c in old_cols:
        if c not in new_cols:
            schema_rows.append({"column": c, "old_dtype": str(old[c].dtype),
                                "new_dtype": "—", "status": "removed"})
    for c in new_cols:
        if c not in old_cols:
            schema_rows.append({"column": c, "old_dtype": "—",
                                "new_dtype": str(new[c].dtype),
                                "status": "added"})
    for c in old_cols:
        if c in new_cols and str(old[c].dtype) != str(new[c].dtype):
            schema_rows.append({"column": c, "old_dtype": str(old[c].dtype),
                                "new_dtype": str(new[c].dtype),
                                "status": "dtype changed"})
    schema = pd.DataFrame(schema_rows,
                          columns=["column", "old_dtype", "new_dtype", "status"])

    # --- added / deleted (anti-joins on real key columns)
    added = new_k.merge(old_k[keys].drop_duplicates(), on=keys, how="left",
                        indicator=True)
    added = new.loc[added[added["_merge"] == "left_only"].index].reset_index(drop=True)
    deleted = old_k.merge(new_k[keys].drop_duplicates(), on=keys, how="left",
                          indicator=True)
    deleted = old.loc[deleted[deleted["_merge"] == "left_only"].index] \
        .reset_index(drop=True)

    # --- cell-level changes on the inner join
    common = [c for c in old_cols if c in new_cols and c not in keys]
    changed_rows: list[dict] = []
    truncated = False
    if common:
        both = old_k.merge(new_k, on=keys, how="inner", suffixes=("_old", "_new"))

        def _lookup(dfk: pd.DataFrame) -> dict:
            m: dict = {}
            for i, kt in enumerate(
                    dfk[keys].itertuples(index=False, name=None)):
                m.setdefault(kt, i)  # first wins; dups already warned
            return m

        old_map, new_map = _lookup(old_k), _lookup(new_k)
        for _, brow in both.iterrows():
            kt = tuple(brow[k] for k in keys)
            oi, ni = old_map.get(kt), new_map.get(kt)
            if oi is None or ni is None:  # pragma: no cover - defensive
                continue
            for c in common:
                ov, nv = old.at[oi, c], new.at[ni, c]
                if pd.isna(ov) and pd.isna(nv):
                    continue
                if ov == nv and type(ov) is type(nv):
                    continue
                if len(changed_rows) >= MAX_CHANGED_CELLS:
                    truncated = True
                    break
                changed_rows.append({**{k: brow[k] for k in keys},
                                     "column": c,
                                     "old_value": None if pd.isna(ov) else ov,
                                     "new_value": None if pd.isna(nv) else nv})
            if truncated:
                break
    if truncated:
        warnings.append(f"Changed-cells list capped at {MAX_CHANGED_CELLS:,} rows.")
    changed_cells = pd.DataFrame(changed_rows,
                                 columns=[*keys, "column", "old_value", "new_value"])

    summary = {
        "old_rows": len(old), "new_rows": len(new),
        "added": len(added), "deleted": len(deleted),
        "changed_cells": len(changed_cells),
        "schema_issues": len(schema),
    }
    return {"added": added, "deleted": deleted, "changed_cells": changed_cells,
            "schema": schema, "summary": summary, "warnings": warnings}
