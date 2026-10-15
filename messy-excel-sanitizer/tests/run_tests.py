"""Tests for messy-excel-sanitizer/sanitize_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402
import pandas as pd  # noqa: E402

import sanitize_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


def messy_xlsx() -> bytes:
    """Title row + merged vertical store col + merged horizontal header."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws["A1"] = "Monthly Sales Report - DO NOT USE ROW 1"
    ws["A2"] = "Store"
    ws["B2"] = "  Sales Amount  "
    ws["C2"] = "Date"
    ws["A3"] = "Store A"
    ws["A4"] = "Store A"  # will be merged A3:A4 below
    ws.merge_cells("A3:A4")
    ws["B3"] = 100
    ws["B4"] = 200
    ws["C3"] = "01/02/2026"
    ws["C4"] = "02/02/2026"
    ws["A5"] = "Store B"
    ws["B5"] = 300
    ws["C5"] = "03/02/2026"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


raw = messy_xlsx()

# --- read with title-row skip + unmerge --------------------------------
df = core.read_source(raw, "sales.xlsx", sheet="Sales", skip_rows=1,
                      unmerge=True)
check("header parsed", list(df.columns) == ["Store", "Sales Amount", "Date"])
check("unmerge leaves gap before ffill", df["Store"].isna().sum() == 1)
df_f, _ = core.sanitize_df(df, {"ffill": True})
check("unmerge+ffill fills store",
      df_f["Store"].tolist() == ["Store A", "Store A", "Store B"])

df_nounmerge = core.read_source(raw, "sales.xlsx", sheet="Sales", skip_rows=1,
                                unmerge=False)
check("no unmerge leaves NaN", df_nounmerge["Store"].isna().sum() == 1)

# --- sanitize -----------------------------------------------------------
opts = {"ffill": False, "strip_ws": True, "header_mode": "snake",
        "date_unify": True, "dayfirst": True,
        "drop_empty_rows": True, "drop_empty_cols": True, "drop_dupes": False}
clean, notes = core.sanitize_df(df, opts)
check("snake headers", list(clean.columns) == ["store", "sales_amount", "date"],
      str(list(clean.columns)))
check("dates unified", str(clean["date"].dtype).startswith("datetime64"),
      str(clean["date"].dtype))
check("date values right", clean["date"].iloc[0].strftime("%Y-%m-%d") == "2026-02-01")

# whitespace strip
df_ws = pd.DataFrame({"a": ["  x ", "y  ", None]})
c2, _ = core.sanitize_df(df_ws, {"strip_ws": True, "header_mode": "strip",
                                 "drop_empty_rows": False,
                                 "drop_empty_cols": False})
check("whitespace stripped",
      c2["a"].iloc[0] == "x" and c2["a"].iloc[1] == "y"
      and pd.isna(c2["a"].iloc[2]))

# dupes + empties
df_de = pd.DataFrame({"a": [1, 1, None], "b": [2, 2, None], "e": [None, None, None]})
c3, n3 = core.sanitize_df(df_de, {"drop_empty_rows": True,
                                  "drop_empty_cols": True, "drop_dupes": True})
check("empties+dupes dropped", len(c3) == 1 and "e" not in c3.columns)

# header dedupe
df_hd = pd.DataFrame([[1, 2]], columns=["A", "A"])
c4, _ = core.sanitize_df(df_hd, {"header_mode": "snake"})
check("dupe headers suffixed", list(c4.columns) == ["a", "a_2"])

# --- validation ----------------------------------------------------------
missing, extra = core.validate_schema(clean, ["store", "sales_amount", "nope"])
check("missing flagged", missing == ["nope"])
check("extra flagged", extra == ["date"])

# --- concat ---------------------------------------------------------------
d1 = pd.DataFrame({"store": ["A"], "amt": [1]})
d2 = pd.DataFrame({"store": ["B"], "other": ["x"]})
master = core.concat_sources([("f1.xlsx", "S1", d1), ("f2.xlsx", "S2", d2)])
check("concat union cols",
      set(master.columns) >= {"store", "amt", "other", "_source_file",
                              "_source_sheet"} and len(master) == 2)
check("concat source tracking",
      master["_source_file"].tolist() == ["f1.xlsx", "f2.xlsx"])

# --- csv path --------------------------------------------------------------
csv_raw = "h1,h2\n a ,1\n".encode()
dfc = core.read_source(csv_raw, "a.csv")
check("csv read", list(dfc.columns) == ["h1", "h2"])

try:
    core.read_source(b"", "empty.xlsx", skip_rows=5)
    check("empty after skip rejected", False)
except ValueError:
    check("empty after skip rejected", True)

print(f"\nAll {passed} checks passed.")
