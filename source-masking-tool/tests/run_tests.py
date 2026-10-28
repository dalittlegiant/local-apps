"""Tests for source-masking-tool/masking_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import masking_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


def make_tree():
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "MyApp_sources"
    src.mkdir(parents=True)
    (src / "CanvasManifest.json").write_text(
        json.dumps({"url": "https://real-company.sharepoint.com/sites/X",
                    "table": "RealTableName"}), encoding="utf-8")
    (src / "Src").mkdir()
    (src / "Src" / "Screen1.pa.yaml").write_text(
        "OnSelect: Navigate(RealTableName)\n"
        "  url: \"https://real-company.sharepoint.com/sites/X\"\n",
        encoding="utf-8")
    (src / "Src" / "notes.txt").write_text(
        "RealTableName should NOT be touched (wrong suffix).",
        encoding="utf-8")
    return tmp, src


MAPPING = {"https://real-company.sharepoint.com": "https://masked-url.com",
           "RealTableName": "MaskedTableA"}

# --- mask round-trip -------------------------------------------------------
tmp, src = make_tree()
rep = core.mask_directory(src, MAPPING)
check("mask files scanned", rep["files_scanned"] == 2, rep)
check("mask files changed", rep["files_changed"] == 2, rep)
check("mask total", rep["total"] == 4, rep)
check("mask json replaced",
      "https://masked-url.com" in (src / "CanvasManifest.json").read_text())
check("mask yaml replaced",
      "MaskedTableA" in (src / "Src" / "Screen1.pa.yaml").read_text())
check("txt untouched", "RealTableName" in (src / "Src" / "notes.txt").read_text())
left = core.count_occurrences(src, list(MAPPING))
check("mask verify zero real", all(v == 0 for v in left.values()), left)
rep2 = core.unmask_directory(src, MAPPING)
check("unmask total", rep2["total"] == 4, rep2)
check("unmask restores url",
      "https://real-company.sharepoint.com" in
      (src / "CanvasManifest.json").read_text())
check("unmask restores table",
      "RealTableName" in (src / "Src" / "Screen1.pa.yaml").read_text())
left2 = core.count_occurrences(src, list(MAPPING.values()))
check("unmask verify zero masked", all(v == 0 for v in left2.values()), left2)

# --- dry run writes nothing --------------------------------------------------
tmp, src = make_tree()
before = (src / "Src" / "Screen1.pa.yaml").read_bytes()
rep = core.mask_directory(src, MAPPING, dry_run=True)
check("dry run counts", rep["total"] == 4, rep)
check("dry run writes nothing",
      (src / "Src" / "Screen1.pa.yaml").read_bytes() == before)

# --- longest-first: short key must not eat a longer one ----------------------
tmp2 = Path(tempfile.mkdtemp())
src2 = tmp2 / "S"
src2.mkdir()
(src2 / "a.pa.yaml").write_text("TableName and Table\n", encoding="utf-8")
core.mask_directory(src2, {"Table": "T1", "TableName": "T2"})
check("longest-first",
      (src2 / "a.pa.yaml").read_text() == "T2 and T1\n",
      (src2 / "a.pa.yaml").read_text())

# --- mapping save/load + path naming -----------------------------------------
tmp, src = make_tree()
storage = tmp / "storage"
p1 = core.mapping_path_for(src, storage)
p2 = core.mapping_path_for(tmp / "Other" / "MyApp_sources", storage)
check("mapping path differs per folder", p1 != p2, (p1, p2))
check("mapping path outside sources", storage in p1.parents)
core.save_mapping(p1, MAPPING)
check("mapping round-trip", core.load_mapping(p1) == MAPPING)
bad = tmp / "bad.json"
bad.write_text('{"a": 1}', encoding="utf-8")
try:
    core.load_mapping(bad)
    check("mapping non-string rejected", False)
except core.PacError:
    check("mapping non-string rejected", True)
missing = tmp / "nope.json"
try:
    core.load_mapping(missing)
    check("mapping missing file error", False)
except core.PacError:
    check("mapping missing file error", True)

# --- validation + reverse -----------------------------------------------------
errors, _ = core.validate_mapping({"A": "X", "B": "X"})
check("duplicate masked is error", bool(errors), errors)
errors, _ = core.validate_mapping({"A": ""})
check("empty masked is error", bool(errors))
try:
    core.reverse_mapping({"A": "X", "B": "X"})
    check("reverse collision raises", False)
except core.PacError:
    check("reverse collision raises", True)
check("reverse ok", core.reverse_mapping(MAPPING) ==
      {"https://masked-url.com": "https://real-company.sharepoint.com",
       "MaskedTableA": "RealTableName"})

# --- BOM preservation ----------------------------------------------------------
tmp3 = Path(tempfile.mkdtemp())
src3 = tmp3 / "S"
src3.mkdir()
f3 = src3 / "b.json"
f3.write_bytes(b"\xef\xbb\xbf" + b'{"t": "RealTableName"}')
core.mask_directory(src3, MAPPING)
raw = f3.read_bytes()
check("BOM preserved", raw.startswith(b"\xef\xbb\xbf"))
check("BOM content replaced", b"MaskedTableA" in raw)

# --- backup excludes .git -------------------------------------------------------
tmp, src = make_tree()
(src / ".git").mkdir()
(src / ".git" / "objects").write_text("x", encoding="utf-8")
bk = core.backup_directory(src, tmp / "backups")
check("backup exists", bk.is_dir())
check("backup excludes .git", not (bk / ".git").exists())
check("backup has sources", (bk / "Src" / "Screen1.pa.yaml").is_file())

# --- pac missing / bad paths ------------------------------------------------------
try:
    core.run_pac(["--version"])
    # pac genuinely installed in this env: acceptable — just record it.
    print("note: pac IS installed here; missing-pac path not exercised")
    passed += 1
except core.PacError as exc:
    check("pac missing friendly error", "not installed" in str(exc), str(exc))
try:
    core.unpack_msapp(tmp / "nope.msapp", tmp / "Out")
    check("unpack missing file error", False)
except core.PacError as exc:
    check("unpack missing file error", "not found" in str(exc), str(exc))
try:
    core.unpack_msapp(src / "CanvasManifest.json", tmp / "Out")
    check("unpack wrong suffix error", False)
except core.PacError as exc:
    check("unpack wrong suffix error", ".msapp" in str(exc), str(exc))
try:
    core.pack_msapp(tmp / "nope_folder", tmp / "Out.msapp")
    check("pack missing folder error", False)
except core.PacError as exc:
    check("pack missing folder error", "not found" in str(exc), str(exc))
try:
    core.scan_files(tmp / "nope_folder")
    check("scan missing folder error", False)
except core.PacError:
    check("scan missing folder error", True)

# --- filename/folder rename: mask bottom-up ----------------------------------
import os
tmp4 = Path(tempfile.mkdtemp())
src4 = tmp4 / "S"
(src4 / "AcmeCorp_Data").mkdir(parents=True)
(src4 / "AcmeCorp_Data" / "My_Real_Company_DataSource.json").write_text(
    '{"t": "RealTableName"}', encoding="utf-8")
(src4 / "AcmeCorp_Data" / "Screen_AcmeCorp.pa.yaml").write_text(
    "x: AcmeCorp\n", encoding="utf-8")
(src4 / ".git").mkdir()
(src4 / ".git" / "AcmeCorp_config").write_text("x", encoding="utf-8")
rmap = {"AcmeCorp": "MaskedCo", "Real_Company": "Masked_Company"}
rep = core.rename_paths(src4, rmap)
check("rename folder", (src4 / "MaskedCo_Data").is_dir())
check("rename file in folder",
      (src4 / "MaskedCo_Data" / "My_Masked_Company_DataSource.json").is_file())
check("rename nested file",
      (src4 / "MaskedCo_Data" / "Screen_MaskedCo.pa.yaml").is_file())
check("rename count", rep["total"] == 3, rep)
check("rename .git skipped", (src4 / ".git" / "AcmeCorp_config").is_file())

# --- rename collision: never overwrite -----------------------------------------
tmp5 = Path(tempfile.mkdtemp())
src5 = tmp5 / "S"
src5.mkdir()
(src5 / "A_Data.json").write_text("AAA", encoding="utf-8")
(src5 / "B_Data.json").write_text("BBB", encoding="utf-8")
rep = core.rename_paths(src5, {"A": "X", "B": "X"})
check("rename collision one renamed", rep["total"] == 1, rep)
check("rename collision one skipped", len(rep["skipped"]) == 1, rep)
check("rename collision no overwrite",
      (src5 / "X_Data.json").read_text() in ("AAA", "BBB"))
check("rename collision loser intact",
      ((src5 / "A_Data.json").is_file() or (src5 / "B_Data.json").is_file()))

# --- rename dry run ---------------------------------------------------------------
tmp6 = Path(tempfile.mkdtemp())
src6 = tmp6 / "S"
src6.mkdir()
(src6 / "AcmeCorp_f.json").write_text("x", encoding="utf-8")
rep = core.rename_paths(src6, {"AcmeCorp": "MaskedCo"}, dry_run=True)
check("rename dry run counts", rep["total"] == 1, rep)
check("rename dry run writes nothing", (src6 / "AcmeCorp_f.json").is_file())

# --- full round-trip WITH names ----------------------------------------------------
tmp7 = Path(tempfile.mkdtemp())
src7 = tmp7 / "S"
(src7 / "AcmeCorp_Data").mkdir(parents=True)
(src7 / "AcmeCorp_Data" / "Screen_AcmeCorp.pa.yaml").write_text(
    "t: RealTableName @ AcmeCorp\n", encoding="utf-8")
orig = {str(p.relative_to(src7)): p.read_bytes()
        for p in src7.rglob("*") if p.is_file()}
core.mask_directory(src7, {"RealTableName": "MaskedTableA",
                           "AcmeCorp": "MaskedCo"})
rrep = core.rename_paths(src7, {"AcmeCorp": "MaskedCo"})
check("round-trip masked name",
      (src7 / "MaskedCo_Data" / "Screen_MaskedCo.pa.yaml").is_file())
core.rename_paths(src7, {"MaskedCo": "AcmeCorp"}, topdown=True)
core.unmask_directory(src7, {"RealTableName": "MaskedTableA",
                             "AcmeCorp": "MaskedCo"})
restored = {str(p.relative_to(src7)): p.read_bytes()
            for p in src7.rglob("*") if p.is_file()}
check("round-trip names+contents restored", restored == orig,
      (set(orig), set(restored)))

# --- mapping state format ------------------------------------------------------------
st_path = tmp7 / "state.json"
core.save_mapping_state(st_path, MAPPING, [("a/b", "c/d")])
m2, r2 = core.load_mapping_state(st_path)
check("state round-trip mapping", m2 == MAPPING)
check("state round-trip renames", r2 == [("a/b", "c/d")])
bare = tmp7 / "bare.json"
bare.write_text(json.dumps(MAPPING), encoding="utf-8")
m3, r3 = core.load_mapping_state(bare)
check("state accepts bare dict", m3 == MAPPING and r3 == [])
check("load_mapping unwraps state", core.load_mapping(st_path) == MAPPING)

# --- snapshot / diff ------------------------------------------------------------------
tmp8 = Path(tempfile.mkdtemp())
src8 = tmp8 / "S"
src8.mkdir()
(src8 / "f1.pa.yaml").write_text("a: MaskedTableA\nb: MaskedCo\n",
                                 encoding="utf-8")
(src8 / "f2.json").write_text('{"x": "MaskedCo"}', encoding="utf-8")
(src8 / "gone.json").write_text('{"y": 1}', encoding="utf-8")
snap = core.snapshot_directory(src8)
check("snapshot files", set(snap["files"]) == {"f1.pa.yaml", "f2.json",
                                              "gone.json"})
# AI edits: modify f1, delete gone.json, add new.json, rename f2.json
(src8 / "f1.pa.yaml").write_text("a: MaskedTableA\nb: CHANGED\n",
                                 encoding="utf-8")
(src8 / "gone.json").unlink()
(src8 / "new.json").write_text('{"z": 2}', encoding="utf-8")
os.rename(src8 / "f2.json", src8 / "f2_renamed.json")
# orphan MaskedCo? No — still in f1? f1 now has CHANGED, no MaskedCo...
# f2_renamed still has MaskedCo, so MaskedCo is NOT orphaned; MaskedTableA
# still in f1. Delete MaskedTableA too: rewrite f1 without it.
(src8 / "f1.pa.yaml").write_text("a: CHANGED\nb: CHANGED\n", encoding="utf-8")
diff = core.diff_against_snapshot(src8, snap,
                                  {"RealTableName": "MaskedTableA",
                                   "AcmeCorp": "MaskedCo"})
check("diff modified", diff["modified"] == ["f1.pa.yaml"], diff)
check("diff added", diff["added"] == ["new.json"], diff)
check("diff removed", diff["removed"] == ["gone.json"], diff)
check("diff renamed", diff["renamed"] == [("f2.json", "f2_renamed.json")],
      diff)
check("diff inline text", "CHANGED" in diff["diffs"].get("f1.pa.yaml", ""),
      diff["diffs"].keys())
check("diff orphaned", [o["masked"] for o in diff["orphaned_masked"]] ==
      ["MaskedTableA"], diff["orphaned_masked"])

# --- leftover scan -----------------------------------------------------------------------
tmp9 = Path(tempfile.mkdtemp())
src9 = tmp9 / "S"
src9.mkdir()
(src9 / "a.pa.yaml").write_text(
    'url: "https://real-company.sharepoint.com/x"\n'
    'mail: "someone@example.com"\n'
    'ip: 10.1.2.3\n'
    'conn: "Server=sql01;Password=hunter2"\n'
    'masked: "https://masked-url.com/ok"\n', encoding="utf-8")
scan = core.scan_leftovers(src9, masked_values=["https://masked-url.com"])
pats = sorted({f["pattern"] for f in scan["findings"]})
check("leftover patterns", pats == ["Domain", "Email", "IPv4 address",
                                    "SQL connection", "URL"], pats)
check("leftover masked excluded",
      all("masked-url" not in f["match"] for f in scan["findings"]))
check("leftover distinct", "someone@example.com" in
      core.distinct_leftovers(scan))

# --- templates ------------------------------------------------------------------------------
tstore = tmp9 / "storage"
core.save_template(tstore, "company standard", MAPPING)
check("template listed", core.list_templates(tstore) == ["company_standard"])
check("template round-trip", core.load_template(tstore, "company standard")
      == MAPPING)
core.delete_template(tstore, "company standard")
check("template deleted", core.list_templates(tstore) == [])
try:
    core.save_template(tstore, "   ", MAPPING)
    check("template bad name rejected", False)
except core.PacError:
    check("template bad name rejected", True)

# --- zip export --------------------------------------------------------------------------------
tmp10 = Path(tempfile.mkdtemp())
src10 = tmp10 / "S"
(src10 / ".git").mkdir(parents=True)
(src10 / ".git" / "x").write_text("g", encoding="utf-8")
(src10 / "a.pa.yaml").write_text("hi", encoding="utf-8")
(src10 / "mapping_state.json").write_text("{}", encoding="utf-8")
import zipfile as _zf
import io as _io
names = _zf.ZipFile(_io.BytesIO(core.zip_sources_bytes(src10))).namelist()
check("zip contents", names == ["a.pa.yaml"], names)


# --- profiles: PBIP, generic, custom -------------------------------------------
check("profiles present", set(core.PROFILES) >= {"power-app", "pbip", "generic", "custom"})
check("pbip suffixes", core.get_suffixes("pbip") == (".tmdl", ".json", ".pbip"))
check("generic suffixes include tmdl/md", ".tmdl" in core.get_suffixes("generic") and ".md" in core.get_suffixes("generic"))
check("custom suffixes parsed", core.get_suffixes("custom", ".tmdl, json") == (".tmdl", ".json"))
try:
    core.get_suffixes("nope")
    check("unknown profile rejected", False)
except core.PacError:
    check("unknown profile rejected", True)

tmp11 = Path(tempfile.mkdtemp())
src11 = tmp11 / "PBIP"
(src11 / "MyModel.SemanticModel" / "definition" / "tables").mkdir(parents=True)
(src11 / "MyModel.SemanticModel" / "definition" / "tables" / "Sales.tmdl").write_text(
    'table Sales\n  source: "https://real-company.sharepoint.com/sites/X"\n', encoding="utf-8")
(src11 / "MyModel.Report").mkdir(parents=True)
(src11 / "MyModel.Report" / "definition.json").write_text(
    '{"site": "https://real-company.sharepoint.com/sites/X"}', encoding="utf-8")
(src11 / "MyModel.pbip").write_text(
    '{"version": "1.0", "site": "https://real-company.sharepoint.com/sites/X"}', encoding="utf-8")
(src11 / "notes.txt").write_text("https://real-company.sharepoint.com/sites/X should NOT be touched in pbip profile.", encoding="utf-8")
pbip_suffixes = core.get_suffixes("pbip")
rep = core.mask_directory(src11, {"https://real-company.sharepoint.com": "https://masked-url.com"}, suffixes=pbip_suffixes)
check("pbip files scanned", rep["files_scanned"] == 3, rep)
check("pbip tmdl masked", "https://masked-url.com" in (src11 / "MyModel.SemanticModel" / "definition" / "tables" / "Sales.tmdl").read_text())
check("pbip txt untouched", "https://real-company.sharepoint.com" in (src11 / "notes.txt").read_text())
rep = core.unmask_directory(src11, {"https://real-company.sharepoint.com": "https://masked-url.com"}, suffixes=pbip_suffixes)
check("pbip unmask restores tmdl", "https://real-company.sharepoint.com" in (src11 / "MyModel.SemanticModel" / "definition" / "tables" / "Sales.tmdl").read_text())

tmp12 = Path(tempfile.mkdtemp())
src12 = tmp12 / "G"
src12.mkdir()
(src12 / "a.md").write_text("RealTableName here\n", encoding="utf-8")
(src12 / "b.yaml").write_text("table: RealTableName\n", encoding="utf-8")
(src12 / "c.bin").write_bytes(b"RealTableName")
rep = core.mask_directory(src12, {"RealTableName": "MaskedTableA"}, suffixes=core.get_suffixes("generic"))
check("generic md+yaml masked", rep["files_scanned"] == 2, rep)
check("generic bin untouched", b"RealTableName" in (src12 / "c.bin").read_bytes())

# snapshot/diff with pbip suffixes
tmp13 = Path(tempfile.mkdtemp())
src13 = tmp13 / "S"
src13.mkdir()
(src13 / "x.tmdl").write_text("a: MaskedTableA\n", encoding="utf-8")
snap = core.snapshot_directory(src13, suffixes=core.get_suffixes("pbip"))
check("pbip snapshot suffixes recorded", snap.get("suffixes") == list(core.get_suffixes("pbip")), snap)
(src13 / "x.tmdl").write_text("a: CHANGED\n", encoding="utf-8")
diff = core.diff_against_snapshot(src13, snap, {"RealTableName": "MaskedTableA"}, suffixes=core.get_suffixes("pbip"))
check("pbip diff modified", diff["modified"] == ["x.tmdl"], diff)
check("pbip diff orphaned", [o["masked"] for o in diff["orphaned_masked"]] == ["MaskedTableA"], diff)

print(f"\n{passed} checks passed")
