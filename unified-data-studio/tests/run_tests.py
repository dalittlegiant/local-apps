"""Test harness for the Unified Data Studio's pure logic (lib/).

Run from the app root:  python3 tests/run_tests.py
No Streamlit required. Exits non-zero on the first failure.
"""

import copy
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures"

from lib import csv_loader as cl          # noqa: E402
from lib import rules_engine as re        # noqa: E402
from lib import theme_builder as tb       # noqa: E402
from lib import tmdl_io as tio            # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


def obj_by(objects, table, kind, name):
    for o in objects:
        if o.table == table and o.kind == kind and o.name == name:
            return o
    raise AssertionError(f"object not found: {table}/{kind}/{name}")


def lineage_lines(lines):
    return sorted(l for l in lines if "lineageTag:" in l)


# ================================================================ tmdl
t1 = tio.parse_tmdl_text((FIX / "DimCustomer.tmdl").read_text(), "DimCustomer.tmdl")
t2 = tio.parse_tmdl_text((FIX / "FactSales.tmdl").read_text(), "FactSales.tmdl")

m = obj_by(t1.objects, "DimCustomer", "measure", "Total Sales")
check("parse /// description", m.description == "Total sales across all channels.")
check("parse inline DAX", m.expression == "SUM ( FactSales[Amount] )")
check("parse lineageTag flag", m.has_lineage_tag is True)
check("parse inline form", m.expr_loc.form == "inline")

ytd = obj_by(t1.objects, "DimCustomer", "measure", "Sales YTD")
check("parse multiline inline DAX",
      ytd.expression == "TOTALYTD (\n[Total Sales],\nDimDate[Date]\n)")
check("parse description: property", ytd.description == "Year to date sales")
check("partition skipped", not any("Partition" in o.name for o in t1.objects))

col = obj_by(t1.objects, "DimCustomer", "column", "CustomerKey")
check("/// above column attaches to column",
      col.description == "Customer dimension, one row per customer."
      and col.has_lineage_tag)

avg = obj_by(t2.objects, "FactSales", "measure", "Avg Sale")
check("parse expression: property",
      avg.expression == "AVERAGE ( FactSales[Amount] )"
      and avg.expr_loc.form == "property")

run = obj_by(t2.objects, "FactSales", "measure", "Running Total")
check("parse expression: | block",
      run.expr_loc.form == "block"
      and "CALCULATE (" in run.expression and "ALL ( DimDate )" in run.expression)

nodesc = obj_by(t2.objects, "FactSales", "measure", "No Desc Measure")
check("parse missing description", nodesc.description == "" and nodesc.desc_loc is None)

# --- edit inline multi-line DAX; lineageTag lines must be byte-identical
lines1 = (FIX / "DimCustomer.tmdl").read_text().splitlines()
before_tags = lineage_lines(lines1)
new_dax = "TOTALYTD (\n    [Total Sales],\n    DimDate[Date],\n    \"6-30\"\n)"
ops = tio.build_edit_ops(ytd, new_dax, None)
check("inline DAX edit produces ops", len(ops) == 3)  # replace + delete + insert
out1 = tio.apply_line_ops(lines1, ops)
check("lineageTag untouched by DAX edit", lineage_lines(out1) == before_tags)
t1b = tio.parse_tmdl_text("\n".join(out1), "x")
# Note: the parser strips leading whitespace per DAX line for display
# (v2 behavior); the file itself keeps the exact text that was written.
norm = lambda e: "\n".join(l.strip() for l in e.strip().splitlines())
check("edited DAX re-parses",
      norm(obj_by(t1b.objects, "DimCustomer", "measure", "Sales YTD").expression)
      == norm(new_dax))
diff_changed = sum(1 for a, b in zip(lines1, out1) if a != b) + abs(len(lines1) - len(out1))
check("only intended lines changed", diff_changed <= 8, f"changed={diff_changed}")

# --- edit /// description
ops = tio.build_edit_ops(m, None, "New description here")
check("/// desc edit is one op", len(ops) == 1 and ops[0].kind == "replace_range")
out = tio.apply_line_ops(lines1, ops)
t1c = tio.parse_tmdl_text("\n".join(out), "x")
check("/// desc re-parses",
      obj_by(t1c.objects, "DimCustomer", "measure", "Total Sales").description
      == "New description here")
check("lineageTag untouched by desc edit", lineage_lines(out) == before_tags)

# --- edit description: property
ops = tio.build_edit_ops(ytd, None, "Updated: YTD sales")
out = tio.apply_line_ops(lines1, ops)
t1d = tio.parse_tmdl_text("\n".join(out), "x")
check("description: property edit re-parses",
      obj_by(t1d.objects, "DimCustomer", "measure", "Sales YTD").description
      == "Updated: YTD sales")

# --- add description where none exists
lines2 = (FIX / "FactSales.tmdl").read_text().splitlines()
ops = tio.build_edit_ops(nodesc, None, "Simple count")
check("add-desc is insert op", len(ops) == 1 and ops[0].kind == "insert_before")
out2 = tio.apply_line_ops(lines2, ops)
t2b = tio.parse_tmdl_text("\n".join(out2), "x")
check("inserted /// desc re-parses",
      obj_by(t2b.objects, "FactSales", "measure", "No Desc Measure").description
      == "Simple count")

# --- edit block scalar expression
ops = tio.build_edit_ops(run, "CALCULATE ( [Total Sales] )", None)
check("block edit is one range op",
      len(ops) == 1 and ops[0].kind == "replace_range")
out2b = tio.apply_line_ops(lines2, ops)
t2c = tio.parse_tmdl_text("\n".join(out2b), "x")
check("block edit re-parses",
      obj_by(t2c.objects, "FactSales", "measure", "Running Total").expression
      == "CALCULATE ( [Total Sales] )")

# --- single-line property -> multi-line becomes block scalar
ops = tio.build_edit_ops(avg, "AVERAGE (\n    FactSales[Amount]\n)", None)
out2c = tio.apply_line_ops(lines2, ops)
t2d = tio.parse_tmdl_text("\n".join(out2c), "x")
o2d = obj_by(t2d.objects, "FactSales", "measure", "Avg Sale")
check("property->block conversion re-parses",
      o2d.expression == "AVERAGE (\nFactSales[Amount]\n)"
      and o2d.expr_loc.form == "block")

# --- BOM + CRLF round-trip preservation
raw = b"\xef\xbb\xbf" + "table T\r\n\tlineageTag: x\r\n".encode()
p = FIX / "_tmp_bom.tmdl"
p.write_bytes(raw)
tf, meta = tio.read_tmdl_file(p)
check("BOM detected", meta["bom"] is True and meta["newline"] == "\r\n")
back = tio.render_tmdl_text(["table T", "\tlineageTag: x"], meta)
check("BOM+CRLF preserved", back == raw)
p.unlink()

# --- inline decl with '=' but DAX on continuation lines -> single space kept
ops = tio.build_edit_ops(ytd, "SUM ( FactSales[Amount] )", None)
out1e = tio.apply_line_ops(lines1, ops)
decl = [l for l in out1e if "measure 'Sales YTD'" in l][0]
check("inline rewrite keeps '= ' spacing", decl == "\tmeasure 'Sales YTD' = SUM ( FactSales[Amount] )",
      f"got: {decl!r}")
t1e = tio.parse_tmdl_text("\n".join(out1e), "x")
check("single-line rewrite re-parses",
      obj_by(t1e.objects, "DimCustomer", "measure", "Sales YTD").expression
      == "SUM ( FactSales[Amount] )")

# --- DAX validator
check("validator flags unbalanced", len(tio.validate_dax("SUM ( Sales[Amount] ")) == 1)
check("validator passes balanced", tio.validate_dax("SUM ( Sales[Amount] )") == [])
check("validator flags empty", len(tio.validate_dax("   ")) == 1)

# --- summary + markdown smoke
summ = tio.tables_summary(t1)
md = tio.to_markdown(summ, "DimCustomer", "TMDL (1 file)")
check("markdown export", "## Table: `DimCustomer`" in md and "```dax" in md)

# --- deep-copy isolation (page mutates working copies)
work = copy.deepcopy(t1.objects)
work[0].description = "mutated"
check("deepcopy isolates orig", t1.objects[0].description != "mutated")

# =========================================================== csv_loader
cp1252_csv = "Work Email,Department\njosé@example.com,A\n".encode("cp1252")
df, enc = cl.read_csv_bytes(cp1252_csv)
check("cp1252 fallback reads é", df.iloc[0, 0] == "josé@example.com", f"enc={enc}")
check("cp1252 detected", enc == "cp1252")

bom_csv = "Work Email\nx@y.z\n".encode("utf-8-sig")
df2, enc2 = cl.read_csv_bytes(bom_csv)
check("utf-8-sig BOM handled", df2.columns[0] == "Work Email", f"enc={enc2}")

# ========================================================== rules_engine
hr = pd.DataFrame([
    {cl.EMAIL: "a@x.com", cl.DEPT: "A", cl.POS: "Sales"},
    {cl.EMAIL: "b@x.com", cl.DEPT: "B", cl.POS: "Manager"},
    {cl.EMAIL: "c@x.com", cl.DEPT: "C", cl.POS: "Regional Manager"},
    {cl.EMAIL: "d@x.com", cl.DEPT: "Z", cl.POS: "Ghost"},
])
rules = re.sample_rule_book()
final, warns = re.simulate_rls(hr, rules, None, re.sample_store_master())
c_rows = final[final[cl.EMAIL] == "c@x.com"]
check("':' explosion via .explode()", len(c_rows) == 2
      and set(c_rows[cl.STORE_ACCESS]) == {"A", "C"})
check("store master join", "Causeway Bay" in
      final[final[cl.STORE_ACCESS] == "A"][cl.STORE_NAME].iloc[0])
check("NO RULE row stays visible",
      (final[final[cl.EMAIL] == "d@x.com"]["Source"] == "NO RULE").all()
      and any("d@x.com" in w for w in warns))
check("exact match wins", final[final[cl.EMAIL] == "a@x.com"][cl.STORE_ACCESS].iloc[0] == "A")

# exception override
exc = re.sample_exceptions()
hr2 = pd.DataFrame([{cl.EMAIL: "temp.cover@example.com", cl.DEPT: "A", cl.POS: "Sales"}])
f2, _ = re.simulate_rls(hr2, rules, exc, None)
check("exception wins per email",
      set(f2[cl.STORE_ACCESS]) == {"A", "B"}
      and (f2["Source"] == "Exception").all())

# unknown code falls back to the code itself
hr3 = pd.DataFrame([{cl.EMAIL: "e@x.com", cl.DEPT: "A", cl.POS: "Sales"}])
r3 = rules.copy()
r3.loc[(r3[cl.DEPT] == "A") & (r3[cl.POS] == "Sales"), cl.STORE_ACCESS] = "ZZZ"
f3, _ = re.simulate_rls(hr3, r3, None, re.sample_store_master())
check("unknown store code fallback", f3[cl.STORE_NAME].iloc[0] == "ZZZ")

# deltas
old = pd.DataFrame([
    {cl.EMAIL: "stay@x.com", cl.DEPT: "A", cl.POS: "Sales"},
    {cl.EMAIL: "leave@x.com", cl.DEPT: "A", cl.POS: "Sales"},
    {cl.EMAIL: "move@x.com", cl.DEPT: "A", cl.POS: "Sales"},
])
new = pd.DataFrame([
    {cl.EMAIL: "stay@x.com", cl.DEPT: "A", cl.POS: "Sales"},
    {cl.EMAIL: "move@x.com", cl.DEPT: "B", cl.POS: "Manager"},
    {cl.EMAIL: "join@x.com", cl.DEPT: "A", cl.POS: "Sales"},
])
d = re.compute_deltas(old, new, rules, re.sample_store_master())
check("leaver detected", list(d["leavers"][cl.EMAIL]) == ["leave@x.com"])
check("joiner detected + suggested access",
      list(d["joiners"][cl.EMAIL]) == ["join@x.com"]
      and d["joiners"][cl.STORE_ACCESS].iloc[0] == "A")
check("mover detected", list(d["movers"][cl.EMAIL]) == ["move@x.com"])

# gap analysis both directions
expected = pd.DataFrame([{cl.EMAIL: "a@x.com", cl.REPORT_ACCESS: "R1;R2"}])
audit = pd.DataFrame([
    {"Date": "2026-10-01", cl.EMAIL: "a@x.com", "Asset_Name": "R1",
     "Permission_Level": "Viewer", "Remark": ""},
    {"Date": "2026-10-01", cl.EMAIL: "a@x.com", "Asset_Name": "Rogue",
     "Permission_Level": "Admin", "Remark": ""},
])
missing, excess = re.gap_analysis(expected, audit)
check("gap: missing required", list(missing["Asset"]) == ["R2"])
check("gap: excess access", list(excess["Asset"]) == ["Rogue"])
m0, e0 = re.gap_analysis(expected, pd.DataFrame())
check("gap: empty audit -> all missing", len(m0) == 2 and e0.empty)

# unmapped master data
np_, nd_ = re.check_unmapped_master_data(
    pd.DataFrame([{cl.EMAIL: "x", cl.DEPT: "NewDept", cl.POS: "NewPos"}]), rules)
check("unmapped detection", np_ == ["NewPos"] and nd_ == ["NewDept"])

# ========================================================= theme_builder
s = tb.default_settings()
theme = tb.build_theme(s)
check("theme top-level keys",
      all(k in theme for k in ("name", "dataColors", "background", "foreground",
                               "tableAccent", "visualStyles", "textClasses")))
check("theme visualStyles wildcard",
      "padding" in theme["visualStyles"]["*"]["*"]
      and "dropShadow" in theme["visualStyles"]["*"]["*"])
check("theme validates clean", tb.validate_theme(theme) == [])
bad = dict(theme); bad["background"] = "red"
check("theme validator flags bad hex",
      any("background" in w for w in tb.validate_theme(bad)))
check("theme json serializes", json.loads(tb.theme_to_json(theme))["name"] == s["name"])

preview = tb.render_preview_html(s)
check("preview html", "<div" in preview and s["page_bg"] in preview)

visual = json.loads((FIX / "visual_sample.json").read_text())
scan = tb.scan_visual_jsons([("v.json", visual)])
check("scan finds padding", ((scan["container_object"] == "padding")
                             & (scan["property"] == "top")).any())
new_v, changes = tb.apply_vco_standard(
    visual, {"padding": {"top": 8, "bottom": 8, "left": 8, "right": 8},
             "border": {"radius": 8}})
vco = new_v["visualContainerObjects"]
check("bulk edit sets padding uniformly",
      vco["padding"][0] == {"top": 8, "bottom": 8, "left": 8, "right": 8})
check("bulk edit preserves sibling keys",
      vco["border"][0]["width"] == 1 and vco["border"][0]["radius"] == 8)
check("bulk edit preserves objects section",
      new_v["objects"]["labels"][0]["show"] is True)
check("bulk edit reports changes", len(changes) == 5)  # 4 padding + 1 radius
check("bulk edit is idempotent",
      tb.apply_vco_standard(new_v, {"padding": {"top": 8, "bottom": 8,
                                                "left": 8, "right": 8}})[1] == [])

# --- measure rename: declaration line only, everything else byte-identical
lines1 = (FIX / "DimCustomer.tmdl").read_text().splitlines()
before_tags = lineage_lines(lines1)
m = obj_by(t1.objects, "DimCustomer", "measure", "Total Sales")
ops = tio.build_edit_ops(m, None, None, "Total Revenue")
check("rename is a single decl-line op",
      len(ops) == 1 and ops[0].kind == "replace" and ops[0].line == m.decl_line)
out = tio.apply_line_ops(lines1, ops)
check("rename keeps DAX + lineageTag",
      out[m.decl_line].strip() == "measure 'Total Revenue' = SUM ( FactSales[Amount] )"
      and lineage_lines(out) == before_tags)
t1r = tio.parse_tmdl_text("\n".join(out), "x")
mr = obj_by(t1r.objects, "DimCustomer", "measure", "Total Revenue")
check("renamed measure re-parses", mr.expression == m.expression
      and mr.description == m.description)
check("old name gone", not any(o.name == "Total Sales" and o.kind == "measure"
                               for o in t1r.objects))

# --- rename a bare (unquoted) name stays bare; quoted name needing quotes
bare_src = "table T\n\n\tmeasure MyMeasure = 1 + 1\n"
bt = tio.parse_tmdl_text(bare_src, "b")
bm = obj_by(bt.objects, "T", "measure", "MyMeasure")
bout = tio.apply_line_ops(bare_src.splitlines(),
                           tio.build_edit_ops(bm, None, None, "MyMeasure2"))
check("bare name stays bare", bout[2].strip() == "measure MyMeasure2 = 1 + 1")
bout2 = tio.apply_line_ops(bare_src.splitlines(),
                           tio.build_edit_ops(bm, None, None, "My Measure 2"))
check("name with space gets quoted", bout2[2].strip() == "measure 'My Measure 2' = 1 + 1")

# --- rename + DAX edit on inline measure: one decl-line op, no overlap
ytd = obj_by(t1.objects, "DimCustomer", "measure", "Sales YTD")
ops = tio.build_edit_ops(ytd, "TOTALYTD([Total Revenue], DimDate[Date])",
                         None, "Sales YTD New")
decl_ops = [o for o in ops if o.line == ytd.decl_line and o.kind == "replace"]
check("rename+dax is one decl op", len(decl_ops) == 1)
out = tio.apply_line_ops(lines1, ops)
check("rename+dax decl line",
      out[ytd.decl_line].strip() == "measure 'Sales YTD New' = TOTALYTD([Total Revenue], DimDate[Date])")
t1r2 = tio.parse_tmdl_text("\n".join(out), "x")
mr2 = obj_by(t1r2.objects, "DimCustomer", "measure", "Sales YTD New")
check("rename+dax re-parses",
      mr2.expression == "TOTALYTD([Total Revenue], DimDate[Date])")
check("lineageTag untouched by rename+dax", lineage_lines(out) == before_tags)

# --- rename on property-form measure (FactSales Avg Sale)
lines2 = (FIX / "FactSales.tmdl").read_text().splitlines()
before_tags2 = lineage_lines(lines2)
avg = obj_by(t2.objects, "FactSales", "measure", "Avg Sale")
ops = tio.build_edit_ops(avg, None, None, "Average Sale")
out = tio.apply_line_ops(lines2, ops)
t2r = tio.parse_tmdl_text("\n".join(out), "x")
ar = obj_by(t2r.objects, "FactSales", "measure", "Average Sale")
check("property-form rename keeps expression", ar.expression == avg.expression)
check("lineageTag untouched by property rename", lineage_lines(out) == before_tags2)

# --- no-op rename produces no ops
check("same-name rename is no-op",
      tio.build_edit_ops(m, None, None, "Total Sales") == [])

# --- global find & replace planning
plans = tio.plan_dax_replace(t1.objects, "[Total Sales]", "[Total Revenue]")
check("find/replace finds dependents",
      len(plans) == 1 and plans[0]["name"] == "Sales YTD" and plans[0]["count"] == 1)
check("find/replace builds new DAX",
      plans[0]["new_expression"] == "TOTALYTD (\n[Total Revenue],\nDimDate[Date]\n)")
check("find/replace empty find is no-op", tio.plan_dax_replace(t1.objects, "", "x") == [])
check("find/replace no match", tio.plan_dax_replace(t1.objects, "[Nope]", "x") == [])
# applying the plan + the rename yields a consistent model
for p in plans:
    p["obj"].expression = p["new_expression"]
m2 = obj_by(t1.objects, "DimCustomer", "measure", "Total Sales")
ytd_mut = obj_by(t1.objects, "DimCustomer", "measure", "Sales YTD")
ops = tio.build_edit_ops(m2, None, None, "Total Revenue")
ops += tio.build_edit_ops(obj_by(tio.parse_tmdl_text(
    "\n".join(lines1), "x").objects, "DimCustomer", "measure", "Sales YTD"),
    ytd_mut.expression, None)
out = tio.apply_line_ops(lines1, ops)
t1f = tio.parse_tmdl_text("\n".join(out), "x")
check("rename + replaced refs re-parse consistently",
      obj_by(t1f.objects, "DimCustomer", "measure", "Total Revenue").expression
      == "SUM ( FactSales[Amount] )"
      and "[Total Revenue]" in
      obj_by(t1f.objects, "DimCustomer", "measure", "Sales YTD").expression)

print(f"\nAll {passed} checks passed.")
