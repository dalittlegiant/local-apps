"""Tests for bi-requirement-meeting-hub/meeting_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import meeting_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


tmp = Path(tempfile.mkdtemp()) / "t.db"
con = core.connect(tmp)

# --- CRUD -----------------------------------------------------------------
r1 = core.add_requirement(con, "Sales Dash", "2026-10-01", "Amy", "Change",
                          "Feasible (Confirmed)", "Add YoY column",
                          "Add to sales table", "Use SAMEPERIODLASTYEAR")
r2 = core.add_requirement(con, "Sales Dash", "2026-10-01", "Bob", "Suggestion",
                          "Pending Data Check", "Forecast tab", "",
                          "Needs data science effort estimate")
r3 = core.add_requirement(con, "Sales Dash", "2026-10-01", "Cat", "Remove",
                          "Not Feasible (Blocked)", "Drop legacy KPI", "",
                          "KPI is referenced by 3 downstream reports")
r4 = core.add_requirement(con, "Sales Dash", "2026-10-01", "Dan", "To Confirm",
                          "Pending Data Check", "Drill to store level", "")
check("ids increment", r1 < r2 < r3 < r4)

rows = core.list_requirements(con)
check("list all", len(rows) == 4)
check("filter project",
      len(core.list_requirements(con, project="Sales Dash")) == 4)
check("filter action",
      len(core.list_requirements(con, action_type="Suggestion")) == 1)
check("filter feasibility",
      len(core.list_requirements(con,
                                 feasibility_status="Not Feasible (Blocked)")) == 1)
check("search", len(core.list_requirements(con, search="YoY")) == 1)
check("distinct projects", core.distinct(con, "project") == ["Sales Dash"])

core.update_requirement(con, r2, {"feasibility_status": "Feasible (Confirmed)",
                                  "title": "Forecast tab v2"})
rows = core.list_requirements(con, action_type="Suggestion")
check("update works", rows[0]["feasibility_status"] == "Feasible (Confirmed)"
      and rows[0]["title"] == "Forecast tab v2")

n = core.delete_requirements(con, [r4])
check("delete works", n == 1 and len(core.list_requirements(con)) == 3)

try:
    core.add_requirement(con, "", "2026-10-01", "", "Change",
                         "Feasible (Confirmed)", "")
    check("empty project/title rejected", False)
except ValueError:
    check("empty project/title rejected", True)
try:
    core.add_requirement(con, "P", "2026-10-01", "", "Bogus",
                         "Feasible (Confirmed)", "T")
    check("bad action rejected", False)
except ValueError:
    check("bad action rejected", True)

# --- minutes ---------------------------------------------------------------
rows = core.list_requirements(con)
mins = core.generate_minutes(rows, "meeting 2026-10-01")
c = mins["counts"]
check("minutes grouping",
      c["confirmed"] == 1 and c["suggestions"] == 1
      and c["blocked"] == 1 and c["open"] == 0, str(c))
check("md sections",
      all(s in mins["markdown"] for s in
          ("Confirmed Changes", "Under Feasibility Review", "Not Feasible")))
check("blocked reason polite",
      "referenced by 3 downstream reports" in mins["markdown"]
      and "happy to revisit" in mins["markdown"])
check("email format", "Minutes:" in mins["email_subject"]
      and "Hi all" in mins["email"])
check("teams compact", mins["teams"].startswith("📝"))

# empty scope
mins0 = core.generate_minutes([], "nothing")
check("empty minutes", mins0["counts"]["confirmed"] == 0
      and "0 item(s)" in mins0["markdown"])

print(f"\nAll {passed} checks passed.")
