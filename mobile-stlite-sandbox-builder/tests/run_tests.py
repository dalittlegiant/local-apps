"""Tests for mobile-stlite-sandbox-builder/stlite_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import stlite_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


REPO = Path(__file__).resolve().parent.parent.parent

# --- scanning -----------------------------------------------------------
apps = core.scan_apps(REPO)
labels = [a["label"] for a in apps]
check("finds standalone apps", len(apps) >= 12, f"found {len(apps)}")
check("includes duckdb app", any(a["dir"] == "data-diff-duckdb-sandbox"
                                 for a in apps))
check("includes self", any(a["dir"] == "mobile-stlite-sandbox-builder"
                           for a in apps))
check("labels end with app.py", all(l.endswith("app.py") for l in labels))
dd = next(a for a in apps if a["dir"] == "data-diff-duckdb-sandbox")
check("entry recorded", dd["entry"].name == "app.py")
check("sibling modules found",
      any(p.name == "diff_core.py" for p in dd["py_files"]))

# --- requirements --------------------------------------------------------
reqs = core.read_requirements(REPO / "data-diff-duckdb-sandbox")
check("bare names", all("=" not in r and ">" not in r for r in reqs), str(reqs))
check("duckdb detected", "duckdb" in reqs)
check("streamlit dropped", "streamlit" not in reqs)
reqs_self = core.read_requirements(REPO / "mobile-stlite-sandbox-builder")
check("self reqs parsed", reqs_self == [])

# --- js escaping ----------------------------------------------------------
check("escape backslash", core.js_escape("a\\b") == "a\\\\b")
check("escape backtick", core.js_escape("a`b") == "a\\`b")
check("escape template", core.js_escape("a${b}") == "a\\${b}")
evil = "C:\\data\\x`y${z}"
esc = core.js_escape(evil)
import re as _re
check("backticks escaped",
      all(m.start() > 0 and esc[m.start() - 1] == "\\"
          for m in _re.finditer("`", esc)))
check("no raw ${", "${" not in esc.replace("\\${", ""))

# --- bundling --------------------------------------------------------------
files = core.bundle_files(dd)
check("entry renamed", core.ENTRY_NAME in files
      and "app.py" not in files)
check("sibling kept", "diff_core.py" in files)
check("entry is app source",
      "Local Parquet/CSV SQL Sandbox" in files[core.ENTRY_NAME])

# --- html template ----------------------------------------------------------
html = core.build_html("DuckDB Sandbox", files,
                       ["pandas", "duckdb"])
check("cdn js pinned", core.STLITE_JS in html and "@stlite/mountable@" in html)
check("cdn css present", core.STLITE_CSS in html)
check("entrypoint set", f'entrypoint: "{core.ENTRY_NAME}"' in html)
check("requirements embedded", '"pandas"' in html and '"duckdb"' in html)
check("files embedded", '"diff_core.py": `' in html)
check("title set", "<title>DuckDB Sandbox — stlite</title>" in html)
check("title escaped", "<title>" in core.build_html("<b>x</b>", {}, []))
check("mount call", "stlite.mount(" in html
      and 'document.getElementById("root")' in html)
seg = html.split('"diff_core.py": `')[1].rsplit("`", 2)[0]
check("no unescaped backticks in files block",
      "`" not in seg.replace("\\`", ""))

# --- wasm substitutions -------------------------------------------------------
check("pypdfium2 swapped",
      core.apply_wasm_substitutions(["pypdfium2", "pandas"]) == ["pypdf", "pandas"])
check("pdfplumber dropped",
      core.apply_wasm_substitutions(["pdfplumber", "pandas"]) == ["pandas"])
check("case-insensitive",
      core.apply_wasm_substitutions(["PyPDFium2"]) == ["pypdf"])
check("dedup on swap",
      core.apply_wasm_substitutions(["pypdf", "pypdfium2"]) == ["pypdf"])
check("safe list untouched",
      core.apply_wasm_substitutions(["pandas", "pillow", "pypdf"]) ==
      ["pandas", "pillow", "pypdf"])

# --- disclaimer --------------------------------------------------------------
check("disclaimer warns on paths",
      "Local Path" in core.DISCLAIMER and "will NOT work" in core.DISCLAIMER)
check("disclaimer warns on offline",
      "internet" in core.DISCLAIMER)

print(f"\nAll {passed} checks passed.")
