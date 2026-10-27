"""Tests for data-diff-duckdb-sandbox/diff_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb  # noqa: E402
import pandas as pd  # noqa: E402

import diff_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


# --- loading ----------------------------------------------------------
df_csv = core.load_upload("a.csv", "x,y\n1,2\n3,\n".encode())
check("csv load", list(df_csv.columns) == ["x", "y"] and len(df_csv) == 2)

buf = io.BytesIO()
pd.DataFrame({"a": [1, 2]}).to_parquet(buf, index=False)
df_pq = core.load_upload("a.parquet", buf.getvalue())
check("parquet load", df_pq["a"].tolist() == [1, 2])

try:
    core.load_upload("a.txt", b"hello")
    check("unsupported type rejected", False)
except ValueError:
    check("unsupported type rejected", True)

check("table name sanitize",
      core.sanitize_table_name("My Report (2024).xlsx") == "my_report_2024")
check("table name digit prefix", core.sanitize_table_name("2024.csv") == "t_2024")

# --- profiling ---------------------------------------------------------
prof = core.profile_df(pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]}))
check("null pct", prof["columns"][0]["null_pct"] == round(1 / 3 * 100, 2))
check("memory counted", prof["memory_bytes"] > 0)
pf = core.profile_frame(prof)
check("profile frame cols", list(pf.columns)[:3] == ["column", "dtype", "null_count"])

# --- sql ----------------------------------------------------------------
con = duckdb.connect()
con.register("t", pd.DataFrame({"a": [1, 2, 3]}))
res = core.run_sql(con, "SELECT SUM(a) AS s FROM t")
check("sql runs", res["s"].iloc[0] == 6)
try:
    core.run_sql(con, "SELECT * FROM nope")
    check("bad sql raises", False)
except ValueError as e:
    check("bad sql raises", "SQL error" in str(e))

# --- diff ----------------------------------------------------------------
old = pd.DataFrame([
    {"id": 1, "name": "Amy", "amt": 10.0, "gone_col": "x"},
    {"id": 2, "name": "Bob", "amt": 20.0, "gone_col": "y"},
    {"id": 3, "name": "Cat", "amt": 30.0, "gone_col": "z"},
])
new = pd.DataFrame([
    {"id": 2, "name": "Bob", "amt": 25.0, "new_col": 1},   # amt changed
    {"id": 3, "name": "Cat", "amt": 30.0, "new_col": 2},   # unchanged
    {"id": 4, "name": "Dan", "amt": 40.0, "new_col": 3},   # added
])
d = core.diff_datasets(old, new, ["id"])
check("added rows", d["added"]["id"].tolist() == [4])
check("deleted rows", d["deleted"]["id"].tolist() == [1])
cc = d["changed_cells"]
check("changed cell detected",
      len(cc) == 1 and cc.iloc[0]["column"] == "amt"
      and cc.iloc[0]["old_value"] == 20.0 and cc.iloc[0]["new_value"] == 25.0
      and cc.iloc[0]["id"] == "2")
sch = d["schema"]
check("schema removed col", ((sch["column"] == "gone_col")
                             & (sch["status"] == "removed")).any())
check("schema added col", ((sch["column"] == "new_col")
                           & (sch["status"] == "added")).any())
check("summary counts", d["summary"]["added"] == 1
      and d["summary"]["deleted"] == 1 and d["summary"]["changed_cells"] == 1)

# dtype change flagged
old2 = pd.DataFrame({"id": [1], "v": [1]})
new2 = pd.DataFrame({"id": [1], "v": ["one"]})
d2 = core.diff_datasets(old2, new2, ["id"])
check("dtype change flagged",
      ((d2["schema"]["column"] == "v")
       & (d2["schema"]["status"] == "dtype changed")).any())

# int vs str keys still join
old3 = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
new3 = pd.DataFrame({"id": ["1", "2"], "v": ["a", "CHANGED"]})
d3 = core.diff_datasets(old3, new3, ["id"])
check("int/str key compat",
      d3["summary"]["added"] == 0 and d3["summary"]["changed_cells"] == 1)

# duplicate keys warn
d4 = core.diff_datasets(pd.DataFrame({"id": [1, 1], "v": ["a", "b"]}),
                        pd.DataFrame({"id": [1], "v": ["a"]}), ["id"])
check("dup key warning", any("duplicate" in w for w in d4["warnings"]))

# no keys -> error
try:
    core.diff_datasets(old, new, [])
    check("empty keys rejected", False)
except ValueError:
    check("empty keys rejected", True)

# NaN == NaN is not a change
o5 = pd.DataFrame({"id": [1], "v": [None]})
n5 = pd.DataFrame({"id": [1], "v": [None]})
check("nan==nan no change",
      core.diff_datasets(o5, n5, ["id"])["summary"]["changed_cells"] == 0)

# --- temp staging + duckdb-native reads --------------------------------
import os
import tempfile  # noqa: E402

raw_csv = b"x,y\n1,2\n3,4\n"
tpath = core.write_upload_to_temp("sales data.csv", raw_csv)
check("temp staging round-trip", open(tpath, "rb").read() == raw_csv
      and tpath.endswith(".csv") and "dd5_" in os.path.basename(tpath))
check("temp outside repo", not os.path.abspath(tpath).startswith(
    os.path.abspath(Path(__file__).resolve().parent.parent)))
os.unlink(tpath)

check("source clause parquet",
      core.duckdb_source_clause("/tmp/x.parquet", "x.parquet")
      == "read_parquet('/tmp/x.parquet')")
check("source clause csv",
      core.duckdb_source_clause("/tmp/x.csv", "X.CSV")
      == "read_csv_auto('/tmp/x.csv')")
try:
    core.duckdb_source_clause("/tmp/x.xlsx", "x.xlsx")
    check("source clause rejects xlsx", False)
except ValueError:
    check("source clause rejects xlsx", True)
check("source clause csv safe mode",
      core.duckdb_source_clause("/tmp/x.csv", "x.csv", all_varchar=True)
      == "read_csv_auto('/tmp/x.csv', all_varchar=true)")

# --- Safe Mode: dirty CSV (type violation past the sniffer's sample) ---
# The sniffer infers BIGINT from the first rows it samples; the string on
# the final line must raise a duckdb.Error naming the line in strict
# mode, and load verbatim with all_varchar=true (Safe Mode).
dirty_rows = ["id,label"] + [f"{i},item{i}" for i in range(1, 30001)]
dirty_rows.append("91021100/112,badrow")
dirty_path = core.write_upload_to_temp(
    "dirty.csv", ("\n".join(dirty_rows) + "\n").encode())
con_dirty = duckdb.connect()
con_dirty.execute('CREATE OR REPLACE VIEW v_strict AS SELECT * FROM '
                  + core.duckdb_source_clause(dirty_path, "dirty.csv"))
try:
    core.profile_duckdb(con_dirty, "v_strict")
    check("dirty csv strict mode raises", False)
except duckdb.Error as e:
    check("dirty csv strict mode raises", "Line: 30002" in str(e),
          str(e)[:120])
con_dirty.execute('CREATE OR REPLACE VIEW v_safe AS SELECT * FROM '
                  + core.duckdb_source_clause(dirty_path, "dirty.csv",
                                              all_varchar=True))
prof_safe = core.profile_duckdb(con_dirty, "v_safe")
check("dirty csv safe mode loads", prof_safe["rows"] == 30001)
check("dirty csv safe mode all varchar",
      all(c["dtype"] == "VARCHAR" for c in prof_safe["columns"]))
check("dirty csv bad value preserved",
      con_dirty.execute(
          "SELECT id FROM v_safe WHERE label = 'badrow'").fetchone()[0]
      == "91021100/112")
os.unlink(dirty_path)

# --- Lenient CSV: short rows (fewer columns than the header) ----------
# The bad row must sit PAST the sniffer's ~20,480-row sample: inside the
# sample, dialect detection itself fails and the file loads as a single
# VARCHAR column instead of erroring.
check("source clause csv lenient",
      core.duckdb_source_clause("/tmp/x.csv", "x.csv", null_padding=True)
      == "read_csv_auto('/tmp/x.csv', null_padding=true)")
check("source clause csv safe + lenient",
      core.duckdb_source_clause("/tmp/x.csv", "x.csv", all_varchar=True,
                                null_padding=True)
      == "read_csv_auto('/tmp/x.csv', all_varchar=true, null_padding=true)")
short_rows = (["a,b,c,d,e"]
              + [f"{i},2,3,4,5" for i in range(21000)]
              + ["6,7,8"]
              + [f"{i},2,3,4,5" for i in range(21001, 21100)])
short_path = core.write_upload_to_temp(
    "short.csv", ("\n".join(short_rows) + "\n").encode())
con_short = duckdb.connect()
con_short.execute('CREATE OR REPLACE VIEW s_strict AS SELECT * FROM '
                  + core.duckdb_source_clause(short_path, "short.csv"))
try:
    core.profile_duckdb(con_short, "s_strict")
    check("short row strict mode raises", False)
except duckdb.Error as e:
    check("short row strict mode raises",
          "Number of Columns" in str(e) and "Found: 3" in str(e),
          str(e).splitlines()[2][:80] if len(str(e).splitlines()) > 2 else "")
con_short.execute('CREATE OR REPLACE VIEW s_len AS SELECT * FROM '
                  + core.duckdb_source_clause(short_path, "short.csv",
                                              null_padding=True))
prof_short = core.profile_duckdb(con_short, "s_len")
check("short row lenient loads", prof_short["rows"] == 21100)
check("short row padded with null",
      con_short.execute(
          "SELECT c, d, e FROM s_len WHERE a = 6 AND b = 7").fetchone()
      == (8, None, None))
os.unlink(short_path)

# --- Diff-tab skiprows: report-style files with preamble lines --------
# Reproduces the Diff-tab screenshot error: single-field title lines make
# pandas infer 1 column, then the real header errors out.
preamble_csv = (b"Daily Refresh Report\nGenerated 2025-05-23\n"
                b"id,name,amt\n1,Amy,10\n2,Bob,20\n")
try:
    core.load_upload("rep.csv", preamble_csv)
    check("preamble csv without skiprows raises", False)
except ValueError as e:
    check("preamble csv without skiprows raises",
          "Expected 1 fields" in str(e), str(e)[:80])
df_skip = core.load_upload("rep.csv", preamble_csv, skiprows=2)
check("skiprows csv header",
      list(df_skip.columns) == ["id", "name", "amt"] and len(df_skip) == 2
      and df_skip.iloc[0]["name"] == "Amy")
# Excel with a title row on top (same shape, different parser).
xbuf = io.BytesIO()
with pd.ExcelWriter(xbuf, engine="openpyxl") as w:
    pd.DataFrame({"id": [1], "name": ["Amy"]}).to_excel(
        w, index=False, startrow=1)
df_x = core.load_upload("rep.xlsx", xbuf.getvalue(), skiprows=1)
check("skiprows excel header",
      list(df_x.columns) == ["id", "name"] and len(df_x) == 1)

# --- export encoding: utf-8-sig (BOM) for Excel -------------------------
plain = "備註,地區\n中文測試,香港\n".encode("utf-8")
bombed = core.with_utf8_bom(plain)
check("bom added", bombed.startswith(core.UTF8_BOM) and bombed[3:] == plain)
check("bom idempotent", core.with_utf8_bom(bombed) == bombed)
check("bom payload decodes",
      bombed.decode("utf-8-sig").splitlines()[1] == "中文測試,香港")
# End-to-end over the exact _full_export steps: DuckDB COPY writes plain
# UTF-8 (no BOM — Excel would garble it); the helper fixes the bytes.
fd, cpath = tempfile.mkstemp(suffix=".csv")
os.close(fd)
con_bom = duckdb.connect()
con_bom.execute("CREATE TABLE cn AS SELECT '中文測試' AS 備註")
con_bom.execute(f"COPY (SELECT * FROM cn) TO '{cpath}' (HEADER, DELIMITER ',')")
raw_copy = Path(cpath).read_bytes()
check("duckdb copy has no bom", not raw_copy.startswith(core.UTF8_BOM))
fixed_copy = core.with_utf8_bom(raw_copy)
check("copy export fixed for excel",
      fixed_copy.startswith(core.UTF8_BOM)
      and "中文測試" in fixed_copy.decode("utf-8-sig"))
os.unlink(cpath)

# end-to-end: staged csv scanned natively, no pandas involved
tpath2 = core.write_upload_to_temp("t.csv", b"a,b\n1,x\n2,\n3,y\n")
con2 = duckdb.connect()
tname2 = core.sanitize_table_name("t.csv")
con2.execute(f'CREATE OR REPLACE VIEW "{tname2}" AS SELECT * FROM '
             + core.duckdb_source_clause(tpath2, "t.csv"))
check("duckdb native scan",
      con2.execute(f'SELECT SUM(CAST(a AS INTEGER)) FROM "{tname2}"')
      .fetchone()[0] == 6)
prof2 = core.profile_duckdb(con2, tname2)
check("profile_duckdb rows/cols", prof2["rows"] == 3 and prof2["cols"] == 2)
check("profile_duckdb null pct",
      prof2["columns"][1]["null_pct"] == round(1 / 3 * 100, 2))
check("profile_duckdb n_unique", prof2["columns"][0]["n_unique"] == 3)
check("profile_duckdb frame renders",
      list(core.profile_frame(prof2).columns)[:3]
      == ["column", "dtype", "null_count"])
os.unlink(tpath2)

# profile_duckdb matches profile_df on identical data
pdf = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "z"]})
con3 = duckdb.connect()
con3.register("pdf", pdf)
p_n = core.profile_duckdb(con3, "pdf")
p_p = core.profile_df(pdf)
check("profile parity rows", p_n["rows"] == p_p["rows"] == 3)
check("profile parity nulls",
      p_n["columns"][0]["null_count"] == p_p["columns"][0]["null_count"] == 1)
check("profile parity unique",
      p_n["columns"][1]["n_unique"] == p_p["columns"][1]["n_unique"] == 3)

print(f"\nAll {passed} checks passed.")
