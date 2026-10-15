"""Core logic for the Knowledge & Snippet Vault. Pure — no ``st.*`` calls.

SQLite-backed store for code snippets (DAX / M / Python / R / SQL) and
Markdown study notes with LaTeX, plus full-text search and Markdown
cheat-sheet export.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

LANGUAGES = ("DAX", "Power Query (M)", "Python", "R", "SQL")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    language TEXT NOT NULL,
    code TEXT NOT NULL,
    context_notes TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body_md TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def db_path() -> Path:
    p = Path(__file__).resolve().parent / "storage"
    p.mkdir(exist_ok=True)
    return p / "vault.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = Path(path) if path else db_path()
    con = sqlite3.connect(path, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------ snippets
def add_snippet(con, title: str, language: str, code: str,
                context_notes: str = "", tags: str = "") -> int:
    if not title.strip() or not code.strip():
        raise ValueError("Title and code are required.")
    if language not in LANGUAGES:
        raise ValueError(f"Bad language: {language}")
    cur = con.execute(
        "INSERT INTO snippets (title, language, code, context_notes, tags,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (title.strip(), language, code, context_notes.strip(),
         _norm_tags(tags), _now(), _now()))
    con.commit()
    return cur.lastrowid


def update_snippet(con, sid: int, fields: dict) -> None:
    allowed = {"title", "language", "code", "context_notes", "tags"}
    sets = [f"{k} = ?" for k in fields if k in allowed]
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed] + [_now(), sid]
    con.execute(f"UPDATE snippets SET {', '.join(sets)}, updated_at = ? "
                f"WHERE id = ?", vals)
    con.commit()


def delete_snippet(con, sid: int) -> None:
    con.execute("DELETE FROM snippets WHERE id = ?", (sid,))
    con.commit()


# ------------------------------------------------------------ notes
def add_note(con, title: str, body_md: str, tags: str = "") -> int:
    if not title.strip() or not body_md.strip():
        raise ValueError("Title and body are required.")
    cur = con.execute(
        "INSERT INTO notes (title, body_md, tags, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        (title.strip(), body_md, _norm_tags(tags), _now(), _now()))
    con.commit()
    return cur.lastrowid


def update_note(con, nid: int, fields: dict) -> None:
    allowed = {"title", "body_md", "tags"}
    sets = [f"{k} = ?" for k in fields if k in allowed]
    if not sets:
        return
    vals = [fields[k] for k in fields if k in allowed] + [_now(), nid]
    con.execute(f"UPDATE notes SET {', '.join(sets)}, updated_at = ? "
                f"WHERE id = ?", vals)
    con.commit()


def delete_note(con, nid: int) -> None:
    con.execute("DELETE FROM notes WHERE id = ?", (nid,))
    con.commit()


# ------------------------------------------------------------ search
def _norm_tags(tags: str) -> str:
    return ", ".join(t.strip() for t in tags.split(",") if t.strip())


def all_tags(con) -> list[str]:
    tags: set[str] = set()
    for table in ("snippets", "notes"):
        for (t,) in con.execute(f"SELECT tags FROM {table}").fetchall():
            tags.update(x.strip() for x in (t or "").split(",") if x.strip())
    return sorted(tags)


def search(con, query: str = "", language: str | None = None,
           tags: list[str] | None = None) -> dict:
    """Full-text search across snippets and notes. Returns
    {"snippets": [...], "notes": [...]}."""
    tags = tags or []
    out: dict[str, list[dict]] = {"snippets": [], "notes": []}

    sq, params = "SELECT * FROM snippets WHERE 1=1", []
    if language:
        sq += " AND language = ?"
        params.append(language)
    if query.strip():
        like = f"%{query.strip()}%"
        sq += " AND (title LIKE ? OR code LIKE ? OR context_notes LIKE ?)"
        params += [like] * 3
    sq += " ORDER BY updated_at DESC"
    for r in con.execute(sq, params).fetchall():
        d = dict(r)
        if tags and not any(t in (d["tags"] or "") for t in tags):
            continue
        out["snippets"].append(d)

    nq, params = "SELECT * FROM notes WHERE 1=1", []
    if query.strip():
        like = f"%{query.strip()}%"
        nq += " AND (title LIKE ? OR body_md LIKE ?)"
        params += [like] * 2
    nq += " ORDER BY updated_at DESC"
    for r in con.execute(nq, params).fetchall():
        d = dict(r)
        if tags and not any(t in (d["tags"] or "") for t in tags):
            continue
        out["notes"].append(d)
    return out


# ------------------------------------------------------------ export
def export_cheatsheet(snippets: list[dict], notes: list[dict]) -> str:
    parts = ["# Cheat Sheet\n"]
    if snippets:
        parts.append("## Code Snippets\n")
        for s in snippets:
            fence = {"DAX": "dax", "Power Query (M)": "powerquery",
                     "Python": "python", "R": "r", "SQL": "sql"}[s["language"]]
            parts.append(f"### {s['title']} `[{s['language']}]`\n")
            if s["tags"]:
                parts.append(f"_Tags: {s['tags']}_\n")
            if s["context_notes"]:
                parts.append(f"{s['context_notes']}\n")
            parts.append(f"```{fence}\n{s['code']}\n```\n")
    if notes:
        parts.append("## Study Notes\n")
        for n in notes:
            parts.append(f"### {n['title']}\n")
            if n["tags"]:
                parts.append(f"_Tags: {n['tags']}_\n")
            parts.append(f"{n['body_md']}\n")
    return "\n".join(parts)
