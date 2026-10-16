"""Core logic for the BI Requirement & Meeting Hub. Pure — no ``st.*`` calls.

SQLite-backed requirement triage: capture, filter/edit, and one-click
meeting-minutes generation (Markdown / Email / Teams).

Storage is the central workspace DB (``workspace_master.db``) via
``workspace_db.open_workspace()`` — the legacy ``storage/meetings.db``
is imported once on first run and then left untouched.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import workspace_db

ACTION_TYPES = ("Change", "Remove", "Suggestion", "To Confirm")
FEASIBILITY = ("Pending Data Check", "Feasible (Confirmed)",
               "Not Feasible (Blocked)", "Completed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    meeting_date TEXT NOT NULL,
    stakeholder TEXT NOT NULL DEFAULT '',
    action_type TEXT NOT NULL,
    feasibility_status TEXT NOT NULL DEFAULT 'Pending Data Check',
    title TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    technical_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Connect to the requirements store.

    Default (``path=None``): the central workspace DB — resolves
    ``<repo>/workspace/workspace_master.db``, inits the schema, and
    one-time imports legacy ``storage/meetings.db`` rows (idempotent).
    Explicit ``path``: standalone SQLite file, used by tests with a temp
    DB so they never touch real storage.
    """
    if path is None:
        return workspace_db.open_workspace(Path(__file__).resolve().parent)
    path = Path(path)
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute(SCHEMA)
    return con


def add_requirement(con: sqlite3.Connection, project: str, meeting_date: str,
                    stakeholder: str, action_type: str, feasibility_status: str,
                    title: str, detail: str = "",
                    technical_notes: str = "") -> int:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Bad action_type: {action_type}")
    if feasibility_status not in FEASIBILITY:
        raise ValueError(f"Bad feasibility_status: {feasibility_status}")
    if not project.strip() or not title.strip():
        raise ValueError("Project and title are required.")
    now = datetime.now().isoformat(timespec="seconds")
    cur = con.execute(
        """INSERT INTO requirements
           (project, meeting_date, stakeholder, action_type, feasibility_status,
            title, detail, technical_notes, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (project.strip(), meeting_date.strip(), stakeholder.strip(),
         action_type, feasibility_status, title.strip(), detail.strip(),
         technical_notes.strip(), now, now))
    con.commit()
    return cur.lastrowid


def update_requirement(con: sqlite3.Connection, rid: int, fields: dict) -> None:
    allowed = {"project", "meeting_date", "stakeholder", "action_type",
               "feasibility_status", "title", "detail", "technical_notes"}
    sets = [f"{k} = ?" for k in fields if k in allowed]
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed]
    vals.append(datetime.now().isoformat(timespec="seconds"))
    vals.append(rid)
    con.execute(f"UPDATE requirements SET {', '.join(sets)}, updated_at = ? "
                f"WHERE id = ?", vals)
    con.commit()


def delete_requirements(con: sqlite3.Connection, rids: list[int]) -> int:
    cur = con.execute(
        f"DELETE FROM requirements WHERE id IN "
        f"({','.join('?' for _ in rids)})", rids)
    con.commit()
    return cur.rowcount


def list_requirements(con: sqlite3.Connection, project: str | None = None,
                      meeting_date: str | None = None,
                      action_type: str | None = None,
                      feasibility_status: str | None = None,
                      search: str = "") -> list[dict]:
    q = "SELECT * FROM requirements WHERE 1=1"
    params: list = []
    if project:
        q += " AND project = ?"
        params.append(project)
    if meeting_date:
        q += " AND meeting_date = ?"
        params.append(meeting_date)
    if action_type:
        q += " AND action_type = ?"
        params.append(action_type)
    if feasibility_status:
        q += " AND feasibility_status = ?"
        params.append(feasibility_status)
    if search.strip():
        q += (" AND (title LIKE ? OR detail LIKE ? OR technical_notes LIKE ? "
              "OR stakeholder LIKE ?)")
        like = f"%{search.strip()}%"
        params += [like] * 4
    q += " ORDER BY meeting_date DESC, id DESC"
    return [dict(r) for r in con.execute(q, params).fetchall()]


def distinct(con: sqlite3.Connection, column: str) -> list[str]:
    if column not in {"project", "meeting_date", "stakeholder"}:
        raise ValueError(f"Bad column: {column}")
    rows = con.execute(
        f"SELECT DISTINCT {column} FROM requirements WHERE {column} != '' "
        f"ORDER BY {column}").fetchall()
    return [r[0] for r in rows]


# ------------------------------------------------------------ minutes
def _item_line(r: dict) -> str:
    bits = [f"**{r['title']}**"]
    if r["stakeholder"]:
        bits.append(f"(raised by {r['stakeholder']})")
    if r["detail"]:
        bits.append(f"— {r['detail']}")
    return " ".join(bits)


def generate_minutes(rows: list[dict], scope: str) -> dict:
    """Group rows into the 4 stakeholder sections; 3 output formats."""
    confirmed = [r for r in rows
                 if r["action_type"] in ("Change", "Remove")
                 and r["feasibility_status"] in ("Feasible (Confirmed)",
                                                "Completed")]
    suggestions = [r for r in rows
                   if r["action_type"] == "Suggestion"
                   and r["feasibility_status"] in ("Pending Data Check",
                                                  "Feasible (Confirmed)")]
    blocked = [r for r in rows
               if r["feasibility_status"] == "Not Feasible (Blocked)"]
    open_items = [r for r in rows
                  if r not in confirmed and r not in suggestions
                  and r not in blocked]

    def section(title: str, items: list[dict], empty: str,
                note_fn=None) -> str:
        if not items:
            return f"### {title}\n\n_{empty}_\n"
        lines = [f"### {title}\n"]
        for r in items:
            line = f"- {_item_line(r)}"
            extra = note_fn(r) if note_fn else ""
            if extra:
                line += f"\n  - {extra}"
            lines.append(line)
        return "\n".join(lines) + "\n"

    def blocked_note(r: dict) -> str:
        reason = r["technical_notes"] or "technical constraints"
        return (f"_Why: {reason}. We'd be happy to revisit if the underlying "
                f"data changes._")

    md = (f"# Meeting Minutes — {scope}\n\n"
          f"_{len(rows)} item(s) triaged._\n\n"
          + section("✅ Confirmed Changes & Removals", confirmed,
                    "Nothing confirmed in this round.")
          + section("💡 New Suggestions Under Feasibility Review", suggestions,
                    "No new suggestions.")
          + section("🚫 Items Not Feasible", blocked,
                    "Everything requested is feasible.",
                    note_fn=blocked_note)
          + section("❓ Open Items / To Confirm", open_items,
                    "No open items."))

    email_body = (
        f"Hi all,\n\nHere are the minutes from our review ({scope}):\n\n"
        f"CONFIRMED CHANGES & REMOVALS\n"
        + ("\n".join(f"• {r['title']}"
                     + (f" — {r['detail']}" if r['detail'] else "")
                     for r in confirmed) or "• (none)") + "\n\n"
        f"SUGGESTIONS UNDER FEASIBILITY REVIEW\n"
        + ("\n".join(f"• {r['title']}" for r in suggestions) or "• (none)")
        + "\n\n"
        f"NOT FEASIBLE (with reason)\n"
        + ("\n".join(
            f"• {r['title']} — {r['technical_notes'] or 'technical constraints'}"
            for r in blocked) or "• (none)") + "\n\n"
        f"OPEN / TO CONFIRM\n"
        + ("\n".join(f"• {r['title']}" for r in open_items) or "• (none)")
        + "\n\nThanks all!"
    )

    teams = (
        f"📝 **Minutes — {scope}** ({len(rows)} items)\n"
        f"✅ Confirmed: {len(confirmed)} · 💡 Under review: {len(suggestions)} "
        f"· 🚫 Not feasible: {len(blocked)} · ❓ Open: {len(open_items)}\n"
        + ("".join(f"\n🚫 {r['title']}: {r['technical_notes'] or 'see notes'}"
                   for r in blocked[:5]))
    )
    return {"markdown": md, "email_subject": f"Minutes: {scope}",
            "email": email_body, "teams": teams,
            "counts": {"confirmed": len(confirmed),
                       "suggestions": len(suggestions),
                       "blocked": len(blocked), "open": len(open_items)}}
