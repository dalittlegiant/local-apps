"""Tests for data-quality-watchdog/dq_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

import dq_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


df = pd.DataFrame({
    "id": [1, 2, 2, 4],                       # dup pk
    "store": [" A ", "B", "C", "D"],           # whitespace
    "amt": [10.0, 12.0, 11.0, 500.0],          # outlier
    "note": [None, None, "x", "y"],            # 50% null
})

# --- duplicate PK -------------------------------------------------------------
c = core.run_checks(df, {"pk_cols": ["id"]})
check("dup pk fail", c["Duplicate primary keys"]["status"] == "fail")
check("dup pk rows", len(c["Duplicate primary keys"]["exceptions"]) == 2)

c = core.run_checks(df, {"pk_cols": ["store"]})
check("unique pk pass", c["Duplicate primary keys"]["status"] == "pass")

# --- required columns ------------------------------------------------------------
c = core.run_checks(df, {"required_cols": ["id", "nope"]})
check("missing col fail", c["Required columns"]["status"] == "fail"
      and "nope" in c["Required columns"]["summary"])
c = core.run_checks(df, {"required_cols": ["id"]})
check("required present pass", c["Required columns"]["status"] == "pass")

# --- null spikes ------------------------------------------------------------------
c = core.run_checks(df, {"null_threshold": 10.0})
check("null spike warning", c["Null spikes"]["status"] == "warning"
      and "note" in c["Null spikes"]["summary"])
c = core.run_checks(df, {"null_threshold": 90.0})
check("null under threshold pass", c["Null spikes"]["status"] == "pass")

# --- whitespace ----------------------------------------------------------------------
c = core.run_checks(df, {})
check("whitespace warning", c["Whitespace issues"]["status"] == "warning"
      and "store" in c["Whitespace issues"]["summary"])

# --- outliers ---------------------------------------------------------------------------
c = core.run_checks(df, {"outlier_method": "IQR"})
check("iqr outlier", c["Numeric outliers"]["status"] == "warning"
      and "amt" in c["Numeric outliers"]["summary"])
check("outlier rows", (c["Numeric outliers"]["exceptions"]["amt"] == 500.0).all())
c = core.run_checks(df, {"outlier_method": "Z-score", "z_threshold": 5.0})
check("zscore high threshold pass",
      c["Numeric outliers"]["status"] == "pass")

# --- overall --------------------------------------------------------------------------------
check("overall fail", core.overall_status(
    core.run_checks(df, {"pk_cols": ["id"]}), []) == "fail")
check("overall pass", core.overall_status(
    core.run_checks(pd.DataFrame({"id": [1, 2], "v": ["a", "b"]}),
                    {"pk_cols": ["id"], "required_cols": ["id", "v"]}),
    []) == "pass")

# --- baseline -----------------------------------------------------------------------------------
base = pd.DataFrame({"id": [1, 2, 3], "amt": [10.0, 10.0, 10.0],
                     "store": ["A", "B", "C"]})
cur = pd.DataFrame({"id": [1, 2], "amt": [10.0, 50.0],
                    "store": ["A", "B"]})
cur_s = core.summarize(cur, ["amt"], ["store"])
base_s = core.summarize(base, ["amt"], ["store"])
check("summarize", cur_s["rows"] == 2 and cur_s["metric_sums"]["amt"] == 60.0
      and base_s["distinct_counts"]["store"] == 3)
flags = core.baseline_compare(cur_s, base_s, 10.0)
names = {f["metric"] for f in flags}
check("row drop flagged", "row_count" in names)
check("sum spike flagged", "sum(amt)" in names)
check("flag fields", all("delta_pct" in f and "status" in f for f in flags))
flags0 = core.baseline_compare(cur_s, cur_s, 10.0)
check("no drift no flags", flags0 == [])

# --- exceptions frame ------------------------------------------------------------------------------
checks = core.run_checks(df, {"pk_cols": ["id"], "outlier_method": "IQR"})
exc = core.exceptions_frame(checks)
check("exceptions combined", len(exc) == 3 and "_check" in exc.columns)
check("exceptions deduped", len(exc) == len(exc.drop_duplicates()))

# --- loading ---------------------------------------------------------------------------------------------
buf = io.BytesIO()
pd.DataFrame({"a": [1]}).to_parquet(buf, index=False)
check("parquet loads", len(core.load_file("f.parquet", buf.getvalue())) == 1)
check("csv loads", len(core.load_file("f.csv", b"a\n1\n")) == 1)
try:
    core.load_file("f.txt", b"x")
    check("bad type rejected", False)
except ValueError:
    check("bad type rejected", True)

print(f"\nAll {passed} checks passed.")
