"""Tests for the Command Center's Linked Data Folder (link_core only —
no Streamlit needed).

Run:  python tests/run_tests.py   (from the app dir)
"""

import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import link_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


class FakeUpload(io.BytesIO):
    """Minimal stand-in for a Streamlit UploadedFile (real uploads are
    file-like; BytesIO gives us read/seek/getvalue like the real thing)."""

    def __init__(self, name, raw: bytes):
        super().__init__(raw)
        self.name = name


def write_xlsx(path: Path, rows: list[dict]):
    pd.DataFrame(rows).to_excel(path, index=False)


# ---------------------------------------------------------- link.json
with tempfile.TemporaryDirectory() as td:
    store = Path(td) / "storage"
    data = Path(td) / "data"
    data.mkdir()

    check("load_link empty", core.load_link(store) is None)

    folder = core.save_link(str(data), store)
    check("save_link returns resolved path", folder == str(data.resolve()))
    check("load_link round-trip", core.load_link(store) == str(data.resolve()))
    raw = json.loads((store / "link.json").read_text(encoding="utf-8"))
    check("link.json shape", raw == {"folder": str(data.resolve())})

    core.clear_link(store)
    check("clear_link", core.load_link(store) is None)

    try:
        core.save_link(str(data / "nope"), store)
        check("save_link rejects non-dir", False)
    except ValueError:
        check("save_link rejects non-dir", True)

    try:
        core.save_link("", store)
        check("save_link rejects empty", False)
    except ValueError:
        check("save_link rejects empty", True)

# ---------------------------------------------------------- resolution
with tempfile.TemporaryDirectory() as td:
    data = Path(td)
    write_xlsx(data / "rule_book.csv", [])  # placeholder, replaced below
    (data / "rule_book.csv").unlink()
    (data / "rule_book.csv").write_text("Department,Position\nA,Sales\n",
                                        encoding="utf-8")
    write_xlsx(data / "Rule_Book.xlsx",
               [{"Department": "A", "Position": "Manager"}])

    p = core.resolve_slot(data, "rls_rules")
    check("xlsx preferred over csv", p is not None and p.name == "Rule_Book.xlsx")

    (data / "Rule_Book.xlsx").unlink()
    p = core.resolve_slot(data, "rls_rules")
    check("case-insensitive csv fallback", p is not None and p.name == "rule_book.csv")

    write_xlsx(data / "HR Staff List.XLSX",
               [{"Work Email": "a@x.com", "Department": "A", "Position": "Sales"}])
    p = core.resolve_slot(data, "rls_hr")
    check("case-insensitive xlsx ext", p is not None and p.name == "HR Staff List.XLSX")

    check("missing slot -> None", core.resolve_slot(data, "rls_sm") is None)
    check("missing folder -> None", core.resolve_slot(data / "nope", "rls_rules") is None)

    found = core.scan_folder(data)
    check("scan_folder keys", set(found) >= {"rls_rules", "rls_hr", "gap_hr"})
    check("shared stem both slots", found["rls_hr"].name == found["gap_hr"].name)

# ---------------------------------------------------------- reload + parse
with tempfile.TemporaryDirectory() as td:
    store = Path(td) / "storage"
    data = Path(td) / "data"
    data.mkdir()
    rules_xlsx = data / "Rule_Book.xlsx"
    write_xlsx(rules_xlsx, [{"Department": "A", "Position": "Sales",
                             "Store_Access": "A", "Report_Access": "R1"}])
    core.save_link(str(data), store)
    folder = core.load_link(store)

    src = core.pick_source("rls_rules", None, folder)
    check("pick_source linked", isinstance(src, core.LinkedFile)
          and src.name == "Rule_Book.xlsx")
    df = core.read_table_upload(src)
    check("linked v1 parsed", df.iloc[0]["Position"] == "Sales"
          and df.attrs["source_encoding"] == "excel")

    # Modify the file on disk -> reload must see v2.
    write_xlsx(rules_xlsx, [{"Department": "B", "Position": "Manager",
                             "Store_Access": "B", "Report_Access": "R2"}])
    src2 = core.pick_source("rls_rules", None, folder)
    df2 = core.read_table_upload(src2)
    check("reload picks up v2", df2.iloc[0]["Department"] == "B")

    # CSV slot end-to-end.
    (data / "Store_Master.csv").write_text(
        "Store_Code,Store_Name\nA,Flagship\n", encoding="utf-8-sig")
    sm = core.read_table_upload(core.pick_source("rls_sm", None, folder))
    check("linked csv parsed", sm.iloc[0]["Store_Name"] == "Flagship"
          and sm.attrs["source_encoding"] == "utf-8-sig")

    # Manual upload wins over the linked file.
    buf = io.BytesIO()
    pd.DataFrame([{"Department": "Z", "Position": "X",
                   "Store_Access": "Z", "Report_Access": "RZ"}]).to_excel(buf, index=False)
    up = FakeUpload("custom.xlsx", buf.getvalue())
    src3 = core.pick_source("rls_rules", up, folder)
    check("uploader overrides linked", src3 is up)
    df3 = core.read_table_upload(src3)
    check("override content used", df3.iloc[0]["Department"] == "Z")

    # Nothing anywhere -> None.
    check("no source -> None",
          core.pick_source("rls_ex", None, folder) is None)
    check("no folder -> None",
          core.pick_source("rls_rules", None, None) is None)

print(f"\nAll {passed} checks passed.")
