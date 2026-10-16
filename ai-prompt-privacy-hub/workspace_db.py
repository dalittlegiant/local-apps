"""Central workspace database for the local-apps suite.

Single SQLite file (``workspace_master.db``) holding the records of every
storage-backed module: code snippets, study notes, meeting requirements,
prompt templates, and the mask dictionary. The Global Data Manager page
(``unified-data-studio/pages/workspace_manager.py``) is the control plane:
linked-folder location, one-click backup download, and backup restore.

Copies of this file live in each storage-backed app dir:
``knowledge-snippet-vault/`` (canonical — edit here first),
``bi-requirement-meeting-hub/``, ``ai-prompt-privacy-hub/``,
``unified-data-studio/`` (manager page). Keep the copies identical.

Resolution order for the DB location:
1. ``link.json`` next to the default location (set via the manager page),
2. ``<repo>/workspace/workspace_master.db``,
3. ``./workspace_master.db`` fallback (e.g. stlite browser export where the
   repo layout is unavailable).

Pure stdlib, no ``st.*`` calls.
"""

import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

DB_FILENAME = "workspace_master.db"
LINK_FILENAME = "link.json"
SCHEMA_VERSION = 1

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
CREATE TABLE IF NOT EXISTS prompt_templates (
    name TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS mask_map (
    token TEXT PRIMARY KEY,
    original TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
"""

# app dir name -> (legacy storage file, [(table, kind)]) for one-time import
_LEGACY = {
    "knowledge-snippet-vault": ("storage/vault.db",
                                [("snippets", "table"), ("notes", "table")]),
    "bi-requirement-meeting-hub": ("storage/meetings.db",
                                   [("requirements", "table")]),
    "ai-prompt-privacy-hub": ("storage/prompt_templates.json",
                              [("prompt_templates", "json_dict")]),
}

_MASK_LEGACY = ("ai-prompt-privacy-hub", "storage/mask_map.json")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _repo_workspace_dir() -> Path | None:
    """``<repo>/workspace`` if the repo layout is detectable, else None."""
    try:
        root = Path(__file__).resolve().parent.parent
        if (root / ".gitignore").exists() or (root / "DEVELOPER_GUIDE.md").exists():
            return root / "workspace"
    except OSError:
        pass
    return None


def default_db_path() -> Path:
    ws = _repo_workspace_dir()
    if ws is not None:
        ws.mkdir(parents=True, exist_ok=True)
        return ws / DB_FILENAME
    return Path(DB_FILENAME).resolve()


def link_file() -> Path:
    ws = _repo_workspace_dir()
    if ws is not None:
        return ws / LINK_FILENAME
    return Path(LINK_FILENAME).resolve()


def resolve_db_path() -> Path:
    """The effective DB path: linked override, else the default."""
    try:
        raw = json.loads(link_file().read_text(encoding="utf-8"))
        p = Path(raw["db_path"]).expanduser()
        if p.is_absolute():
            return p
    except (OSError, ValueError, KeyError):
        pass
    return default_db_path()


def set_linked_folder(folder: str | Path) -> Path:
    """Point the workspace DB at a user-chosen folder (persistent).

    Creates the folder, copies the current DB there when the target does
    not already have one (never overwrites an existing target DB), and
    records the override in ``link.json``. Returns the effective DB path.
    """
    folder = Path(folder).expanduser()
    if not str(folder).strip():
        raise ValueError("Folder path is empty.")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / DB_FILENAME
    current = resolve_db_path()
    if not target.exists() and current.exists() and target != current:
        shutil.copy2(current, target)
    link_file().write_text(json.dumps({"db_path": str(target)}, indent=2),
                           encoding="utf-8")
    return target


def clear_linked_folder() -> None:
    """Forget the linked-folder override (falls back to the default)."""
    try:
        link_file().unlink()
    except FileNotFoundError:
        pass


def connect(path: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(str(path or resolve_db_path()),
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES "
                "('schema_version', ?)", (str(SCHEMA_VERSION),))
    con.commit()


def _table_empty(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def import_legacy(con: sqlite3.Connection,
                  app_dir: str | Path) -> dict[str, int]:
    """One-time import of an app's legacy storage into the central DB.

    Only imports into empty central tables (idempotent — safe to call on
    every startup). Returns ``{table: rows_imported}``.
    """
    done: dict[str, int] = {}
    name = Path(app_dir).name
    flag = f"migrated_{name}"
    if get_meta(con, flag) == "1":
        return done  # already migrated — never re-import
    spec = _LEGACY.get(name)
    if spec:
        rel, tables = spec
        legacy = Path(app_dir) / rel
        if legacy.exists():
            if legacy.suffix == ".db":
                src = sqlite3.connect(str(legacy))
                try:
                    for table, _kind in tables:
                        if not _table_empty(con, table):
                            continue
                        cols = [r[1] for r in
                                src.execute(f"PRAGMA table_info({table})")]
                        placeholders = ", ".join("?" for _ in cols)
                        rows = src.execute(f"SELECT {', '.join(cols)} "
                                           f"FROM {table}").fetchall()
                        con.executemany(
                            f"INSERT INTO {table} ({', '.join(cols)}) "
                            f"VALUES ({placeholders})", rows)
                        done[table] = len(rows)
                finally:
                    src.close()
            elif legacy.suffix == ".json":
                for table, kind in tables:
                    if kind == "json_dict" and _table_empty(con, table):
                        try:
                            data = json.loads(
                                legacy.read_text(encoding="utf-8"))
                        except (ValueError, OSError):
                            data = {}
                        for k, v in data.items():
                            con.execute(
                                f"INSERT OR IGNORE INTO {table} "
                                f"(name, body, updated_at) VALUES (?, ?, ?)",
                                (k, v, _now()))
                        done[table] = len(data)
    # mask_map.json lived next to prompt_templates.json
    if name == _MASK_LEGACY[0] and _table_empty(con, "mask_map"):
        legacy = Path(app_dir) / _MASK_LEGACY[1]
        if legacy.exists():
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                data = {}
            for tok, orig in data.items():
                con.execute("INSERT OR IGNORE INTO mask_map (token, original)"
                            " VALUES (?, ?)", (tok, orig))
            done["mask_map"] = len(data)
    if done:
        con.commit()
    set_meta(con, flag, "1")
    return done


def open_workspace(app_dir: str | Path | None = None) -> sqlite3.Connection:
    """Resolve, connect, init schema, one-time legacy import. One-liner
    replacing each app's old ``_con()``."""
    con = connect()
    init_db(con)
    if app_dir:
        import_legacy(con, app_dir)
    return con


def get_meta(con: sqlite3.Connection, key: str,
             default: str = "") -> str:
    row = con.execute("SELECT value FROM app_meta WHERE key = ?",
                      (key,)).fetchone()
    return row["value"] if row else default


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute("INSERT INTO app_meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value))
    con.commit()


def record_counts(con: sqlite3.Connection) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("snippets", "notes", "requirements",
                      "prompt_templates", "mask_map")}


def backup_bytes(path: Path | None = None) -> bytes:
    """Raw bytes of the workspace DB (for the download button)."""
    return (path or resolve_db_path()).read_bytes()


def restore_bytes(data: bytes) -> Path:
    """Validate and install an uploaded workspace DB backup.

    Validates the SQLite magic and the expected tables, backs the current
    DB up to ``workspace_master.backup-<timestamp>.db`` beside it, then
    replaces it. Returns the installed path.
    """
    if data[:16] != b"SQLite format 3\x00":
        raise ValueError("Not a SQLite database file.")
    target = resolve_db_path()
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("SELECT name FROM sqlite_master")  # sanity
    finally:
        probe.close()
    tmp = target.with_suffix(".restore-tmp")
    tmp.write_bytes(data)
    try:
        chk = sqlite3.connect(str(tmp))
        try:
            have = {r[0] for r in chk.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            chk.close()
        missing = {"snippets", "notes", "requirements",
                   "prompt_templates", "mask_map"} - have
        if missing:
            raise ValueError("Backup is missing tables: "
                             + ", ".join(sorted(missing)))
    except sqlite3.DatabaseError as exc:
        tmp.unlink(missing_ok=True)
        raise ValueError(f"Unreadable database: {exc}") from exc
    if target.exists():
        backup = target.with_name(
            f"workspace_master.backup-{time.strftime('%Y%m%d-%H%M%S')}.db")
        shutil.copy2(target, backup)
    tmp.replace(target)
    return target
