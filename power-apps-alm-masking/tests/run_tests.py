"""Tests for power-apps-alm-masking/pac_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pac_core as core  # noqa: E402

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

print(f"\n{passed} checks passed")
