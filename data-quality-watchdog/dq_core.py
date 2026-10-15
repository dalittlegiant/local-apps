"""Core logic for the Data Quality Watchdog. Pure — no ``st.*`` calls.

Pre-refresh gatekeeper: duplicate PKs, missing columns, null spikes,
whitespace issues, numeric outliers (IQR / Z-score), optional baseline
comparison, and a Pass/Warning/Fail report card with exception rows.
"""

import io

import pandas as pd
from pandas.api.types import is_numeric_dtype, is_string_dtype


def load_file(name: str, raw: bytes) -> pd.DataFrame:
    lname = name.lower()
    try:
        if lname.endswith(".parquet"):
            return pd.read_parquet(io.BytesIO(raw))
        if lname.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(raw), dtype=object)
        if lname.endswith(".csv"):
            for enc in ("utf-8-sig", "utf-8", "cp1252"):
                try:
                    return pd.read_csv(io.BytesIO(raw), encoding=enc)
                except (UnicodeDecodeError, UnicodeError):
                    continue
            return pd.read_csv(io.BytesIO(raw), encoding="latin-1")
    except Exception as exc:
        raise ValueError(f"Could not read {name}: {exc}") from exc
    raise ValueError(f"Unsupported file type: {name}")


def _exc(df: pd.DataFrame, idx, check: str) -> pd.DataFrame:
    e = df.loc[idx].copy()
    e["_check"] = check
    return e


def run_checks(df: pd.DataFrame, opts: dict) -> dict:
    """Run all health checks. Returns {name: {status, summary, exceptions}}.

    status ∈ {"pass", "warning", "fail"}.
    """
    checks: dict[str, dict] = {}
    n = len(df)

    # 1. duplicate primary keys
    pk = [c for c in opts.get("pk_cols", []) if c in df.columns]
    if pk:
        dup = df.duplicated(subset=pk, keep=False)
        checks["Duplicate primary keys"] = {
            "status": "fail" if dup.any() else "pass",
            "summary": f"{int(dup.sum())} duplicate row(s) on {pk}"
                       if dup.any() else f"Keys {pk} are unique.",
            "exceptions": _exc(df, dup, "dup_pk") if dup.any() else None,
        }

    # 2. missing required columns
    required = [c.strip() for c in opts.get("required_cols", []) if c.strip()]
    missing = [c for c in required if c not in df.columns]
    checks["Required columns"] = {
        "status": "fail" if missing else "pass",
        "summary": f"Missing: {', '.join(missing)}" if missing
                   else f"All {len(required)} required column(s) present.",
        "exceptions": None,
    }

    # 3. null spikes
    thr = float(opts.get("null_threshold", 10.0))
    null_pct = (df.isna().sum() / n * 100) if n else pd.Series(dtype=float)
    spiked = null_pct[null_pct > thr]
    checks["Null spikes"] = {
        "status": "warning" if len(spiked) else "pass",
        "summary": ("Columns over "
                    f"{thr}% null: "
                    + ", ".join(f"{c} ({v:.1f}%)"
                                for c, v in spiked.items())) if len(spiked)
                   else f"No column exceeds {thr}% nulls.",
        "exceptions": None,
    }

    # 4. whitespace issues
    ws_cols = []
    for c in df.columns:
        if is_string_dtype(df[c]):
            s = df[c].dropna()
            if len(s) and ((s != s.str.strip()).any()):
                ws_cols.append(c)
    checks["Whitespace issues"] = {
        "status": "warning" if ws_cols else "pass",
        "summary": f"Leading/trailing whitespace in: {', '.join(ws_cols)}"
                   if ws_cols else "No whitespace issues in text columns.",
        "exceptions": None,
    }

    # 5. numeric outliers
    method = opts.get("outlier_method", "IQR")
    num_cols = [c for c in df.columns
                if is_numeric_dtype(df[c]) and df[c].notna().sum() >= 4]
    out_idx = pd.Series(False, index=df.index)
    out_detail = []
    for c in num_cols:
        s = pd.to_numeric(df[c], errors="coerce").dropna()
        if method == "Z-score":
            z = (s - s.mean()) / (s.std() or 1)
            bad = z.abs() > float(opts.get("z_threshold", 3.0))
        else:  # IQR
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            bad = (s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)
        if bad.any():
            out_idx = out_idx | df.index.isin(s[bad].index)
            out_detail.append(f"{c}: {int(bad.sum())}")
    checks["Numeric outliers"] = {
        "status": "warning" if out_detail else "pass",
        "summary": f"Outliers ({method}) in " + "; ".join(out_detail)
                   if out_detail else f"No outliers detected ({method}).",
        "exceptions": _exc(df, out_idx, "outlier") if out_detail else None,
    }

    return checks


def summarize(df: pd.DataFrame, metric_cols: list[str],
              cat_cols: list[str]) -> dict:
    metrics = {c: float(pd.to_numeric(df[c], errors="coerce").sum())
               for c in metric_cols if c in df.columns}
    cats = {c: int(df[c].nunique(dropna=True))
            for c in cat_cols if c in df.columns}
    return {"rows": len(df), "metric_sums": metrics,
            "distinct_counts": cats}


def baseline_compare(cur: dict, base: dict,
                     pct_threshold: float = 10.0) -> list[dict]:
    """Flag sudden drops/spikes vs baseline. Returns flag dicts."""
    flags: list[dict] = []

    def _flag(name: str, b: float, c: float):
        if b == 0:
            if c != 0:
                flags.append({"metric": name, "baseline": b, "current": c,
                              "delta_pct": None,
                              "status": "warning",
                              "note": "baseline was 0, now non-zero"})
            return
        d = (c - b) / abs(b) * 100
        if abs(d) >= pct_threshold:
            flags.append({"metric": name, "baseline": b, "current": c,
                          "delta_pct": round(d, 1),
                          "status": "fail" if abs(d) >= pct_threshold * 2
                          else "warning",
                          "note": f"{d:+.1f}% vs baseline"})

    _flag("row_count", base["rows"], cur["rows"])
    for m in set(cur["metric_sums"]) & set(base["metric_sums"]):
        _flag(f"sum({m})", base["metric_sums"][m], cur["metric_sums"][m])
    for m in set(cur["distinct_counts"]) & set(base["distinct_counts"]):
        _flag(f"distinct({m})", base["distinct_counts"][m],
              cur["distinct_counts"][m])
    return flags


def overall_status(checks: dict, baseline_flags: list[dict]) -> str:
    if any(c["status"] == "fail" for c in checks.values()) or \
       any(f["status"] == "fail" for f in baseline_flags):
        return "fail"
    if any(c["status"] == "warning" for c in checks.values()) or baseline_flags:
        return "warning"
    return "pass"


def exceptions_frame(checks: dict) -> pd.DataFrame:
    frames = [c["exceptions"] for c in checks.values()
              if c["exceptions"] is not None and not c["exceptions"].empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates()
