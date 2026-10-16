"""Tests for knowledge-snippet-vault/vault_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vault_core as core  # noqa: E402
import workspace_db as wsdb  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


tmp = Path(tempfile.mkdtemp()) / "v.db"
con = core.connect(tmp)

# --- snippets ---------------------------------------------------------------
s1 = core.add_snippet(con, "YoY Sales", "DAX",
                      "YoY = CALCULATE(SUM(Sales[Amt]), SAMEPERIODLASTYEAR(Date[Date]))",
                      "Use in sales dashboards", "dax, time-intelligence")
s2 = core.add_snippet(con, "Read parquet", "Python",
                      "import polars as pl\ndf = pl.read_parquet('f.parquet')",
                      "", "python, etl")
check("snippet ids", s1 < s2)

res = core.search(con)
check("all snippets", len(res["snippets"]) == 2)
check("language filter",
      len(core.search(con, language="DAX")["snippets"]) == 1)
check("text search",
      core.search(con, query="SAMEPERIODLASTYEAR")["snippets"][0]["id"] == s1)
check("tag search",
      len(core.search(con, tags=["etl"])["snippets"]) == 1)
check("all tags", set(core.all_tags(con)) >= {"dax", "etl", "python"})

core.update_snippet(con, s1, {"title": "YoY Sales v2"})
check("snippet updated",
      core.search(con, query="v2")["snippets"][0]["title"] == "YoY Sales v2")
core.delete_snippet(con, s2)
check("snippet deleted", len(core.search(con)["snippets"]) == 1)

try:
    core.add_snippet(con, "", "DAX", "")
    check("empty snippet rejected", False)
except ValueError:
    check("empty snippet rejected", True)
try:
    core.add_snippet(con, "t", "Brainfuck", "x")
    check("bad language rejected", False)
except ValueError:
    check("bad language rejected", True)

# --- notes ---------------------------------------------------------------------
n1 = core.add_note(con, "Bayes rule",
                   "# Bayes\n\n$$P(A|B) = \\frac{P(B|A)P(A)}{P(B)}$$\n\nInline $x^2$.",
                   "stats, bayesian")
check("note added", n1 > 0)
check("note search",
      core.search(con, query="Bayes")["notes"][0]["id"] == n1)
check("latex preserved",
      "\\frac" in core.search(con, query="Bayes")["notes"][0]["body_md"])
core.update_note(con, n1, {"tags": "stats"})
check("note tags updated",
      core.search(con, tags=["stats"])["notes"][0]["id"] == n1)
core.delete_note(con, n1)
check("note deleted", core.search(con)["notes"] == [])

# --- export ----------------------------------------------------------------------
n2 = core.add_note(con, "KPI def", "Churn = leavers / base.", "kpi")
md = core.export_cheatsheet(core.search(con)["snippets"],
                            core.search(con)["notes"])
check("cheatsheet sections",
      "# Cheat Sheet" in md and "## Code Snippets" in md
      and "## Study Notes" in md)
check("cheatsheet code fence", "```dax" in md and "YoY" in md)
check("cheatsheet note body", "Churn = leavers / base." in md)

# --- central workspace DB -------------------------------------------------------
# Isolated central-style DB on a tmp path: never touches the real
# <repo>/workspace/workspace_master.db.
wdb_path = Path(tempfile.mkdtemp()) / "workspace_master.db"
wcon = wsdb.connect(wdb_path)
wsdb.init_db(wcon)
check("central tables exist",
      {r[0] for r in wcon.execute(
          "SELECT name FROM sqlite_master WHERE type='table'")}
      >= {"snippets", "notes", "requirements", "prompt_templates",
          "mask_map", "app_meta"})
check("record counts start at zero",
      wsdb.record_counts(wcon)["snippets"] == 0
      and wsdb.record_counts(wcon)["notes"] == 0)

# Core functions work unchanged against a central-DB connection
# (same columns as the old vault.db).
cs = core.add_snippet(wcon, "Central test", "Python", "x = 1", "", "t")
core.update_snippet(wcon, cs, {"title": "Central test v2"})
check("resume-update round-trip on central con",
      core.search(wcon, query="v2")["snippets"][0]["title"]
      == "Central test v2")

# One-time legacy import: fixture app dir named knowledge-snippet-vault
# with a legacy storage/vault.db holding rows. Uses a FRESH central DB —
# import_legacy only fills empty tables (by design).
wcon2 = wsdb.connect(Path(tempfile.mkdtemp()) / "ws2.db")
wsdb.init_db(wcon2)
fix_app = Path(tempfile.mkdtemp()) / "knowledge-snippet-vault"
(fix_app / "storage").mkdir(parents=True)
legacy_path = fix_app / "storage" / "vault.db"
lcon = core.connect(legacy_path)  # explicit path = old-style isolated DB
core.add_snippet(lcon, "Legacy snippet", "SQL", "SELECT 1", "ctx", "old")
core.add_note(lcon, "Legacy note", "body here", "oldtag")
lcon.close()
check("legacy fixture built", legacy_path.exists())

done = wsdb.import_legacy(wcon2, fix_app)
check("legacy import row counts",
      done.get("snippets") == 1 and done.get("notes") == 1)
check("legacy snippet visible in central DB",
      core.search(wcon2, query="Legacy snippet")["snippets"][0]["code"]
      == "SELECT 1")
check("legacy note visible in central DB",
      core.search(wcon2, query="Legacy note")["notes"][0]["body_md"]
      == "body here")
check("legacy import idempotent", wsdb.import_legacy(wcon2, fix_app) == {})
check("legacy file untouched (still on disk)",
      legacy_path.exists()
      and legacy_path.stat().st_size > 0)

# No-path connect() delegates to the central workspace DB (creates the
# gitignored <repo>/workspace/workspace_master.db on first use).
c0 = core.connect()
check("no-path connect hits central DB",
      c0.execute("SELECT COUNT(*) FROM snippets").fetchone()[0] >= 0)
c0.close()

print(f"\nAll {passed} checks passed.")
