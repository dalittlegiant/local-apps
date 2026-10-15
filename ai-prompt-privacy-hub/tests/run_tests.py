"""Tests for ai-prompt-privacy-hub/prompt_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import prompt_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


# --- prompt builder ---------------------------------------------------------
for fw_key, fw in core.FRAMEWORKS.items():
    vals = {name: f"<{name}>" for name, _, _ in fw["fields"]}
    out = core.build_prompt(fw_key, "DAX Optimization", vals)
    check(f"framework {fw_key} fills fields",
          all(f"<{n}>" in out for n, _, _ in fw["fields"]))
    check(f"framework {fw_key} category hint", "Category hint" in out)
check("repo guardrails present",
      "READ-ONLY" in core.build_prompt(
          "repo", "App Building",
          {n: "x" for n, _, _ in core.FRAMEWORKS["repo"]["fields"]}))

check("detect vars", core.detect_vars("Hi {name}, see {topic}!") == ["name", "topic"])

# --- custom templates ----------------------------------------------------------
tmp = Path(tempfile.mkdtemp()) / "t.json"
core.save_custom_template("t1", "Hello {who}", tmp)
check("template saved", core.load_custom_templates(tmp) == {"t1": "Hello {who}"})
core.delete_custom_template("t1", tmp)
check("template deleted", core.load_custom_templates(tmp) == {})
try:
    core.save_custom_template(" ", " ", tmp)
    check("empty template rejected", False)
except ValueError:
    check("empty template rejected", True)

# --- masker -----------------------------------------------------------------------
raw = ("Contact Amy Chan (amy.chan@company.com) about Store TST-01. "
       "Amy Chan also owns Net Profit Margin. Backup: bob@company.com.")
masked, mapping = core.mask_text(raw, ["Amy Chan"], ["Store TST-01"],
                                 ["Net Profit Margin"])
check("email masked", "amy.chan@company.com" not in masked
      and "bob@company.com" not in masked)
check("name masked", "Amy Chan" not in masked)
check("store masked", "Store TST-01" not in masked)
check("metric masked", "Net Profit Margin" not in masked)
check("token format",
      any(t.startswith("User_") for t in mapping)
      and any(t.startswith("Store_") for t in mapping)
      and any(t.startswith("Metric_") for t in mapping))
tok_amy = next(t for t, o in mapping.items() if o == "Amy Chan")
check("same original same token",
      masked.count(tok_amy) == 2
      and list(mapping.values()).count("Amy Chan") == 1)
# longest-first: "Store TST-01 Flagship" beats "Store TST-01"
m2, _ = core.mask_text("Visit Store TST-01 Flagship today",
                       [], ["Store TST-01", "Store TST-01 Flagship"], [])
check("longest term wins", "Flagship" not in m2 and "Store TST-01" not in m2)

restored = core.unmask_text(masked, mapping)
check("round trip", restored == raw, f"\n{restored}\n!=\n{raw}")

# mapping persistence
mp = Path(tempfile.mkdtemp()) / "m.json"
core.save_mapping(mapping, mp)
check("mapping persisted", core.load_mapping(mp) == mapping)

# --- repo packer --------------------------------------------------------------------
d = Path(tempfile.mkdtemp())
(d / "etl").mkdir()
(d / "etl" / "load.py").write_text("print('hi')")
(d / "model.tmdl").write_text("table Sales")
(d / "secret.csv").write_text("a,b\n1,2")
(d / "cache.db").write_text("x")
(d / "__pycache__").mkdir()
(d / "__pycache__" / "x.py").write_text("junk")
md, stats = core.pack_repo(str(d))
check("packs code", "load.py" in md and "print('hi')" in md)
check("packs tmdl", "model.tmdl" in md)
check("excludes csv", "secret.csv" not in md)
check("excludes db", "cache.db" not in md)
check("skips pycache", "junk" not in md)
check("stats", stats["files_packed"] == 2
      and stats["data_files_excluded"] == 2, str(stats))
try:
    core.pack_repo(str(d / "nope"))
    check("bad folder rejected", False)
except ValueError:
    check("bad folder rejected", True)

print(f"\nAll {passed} checks passed.")
