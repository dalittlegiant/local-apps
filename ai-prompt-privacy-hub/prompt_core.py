"""Core logic for the AI Prompt & Privacy Hub. Pure — no ``st.*`` calls.

Covers: framework-based prompt assembly (RTC / CoT / Few-Shot / Repo
Upgrade), custom template storage (central workspace DB), reversible
PII/schema masking (mask dictionary in the central workspace DB), and
the local repo context packer.
"""

import html
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import workspace_db as wdb

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

FRAMEWORKS = {
    "rtc": {
        "name": "RTC — Role / Task / Context",
        "fields": [
            ("role", "Role", "You are a senior Power BI DAX consultant…"),
            ("task", "Task", "Optimize the following measure…"),
            ("context", "Context", "Dataset: retail sales, 50M rows…"),
        ],
        "template": ("# ROLE\n{role}\n\n# TASK\n{task}\n\n"
                     "# CONTEXT\n{context}\n\n{category_hint}"),
    },
    "cot": {
        "name": "Chain-of-Thought — Step-by-Step",
        "fields": [
            ("task", "Task", "Debug why this measure returns blank…"),
            ("code", "Code / input", "Paste the DAX / SQL / Python here…"),
            ("constraints", "Constraints", "Must not change the grain…"),
        ],
        "template": ("# TASK\n{task}\n\n# INPUT\n```\n{code}\n```\n\n"
                     "# CONSTRAINTS\n{constraints}\n\n"
                     "Think step by step:\n"
                     "1. Restate what the code is intended to do.\n"
                     "2. Identify the most likely failure points, in order.\n"
                     "3. Propose the smallest fix first, then alternatives.\n"
                     "4. Show the corrected code and explain why it works.\n\n"
                     "{category_hint}"),
    },
    "fewshot": {
        "name": "Few-Shot — With Examples",
        "fields": [
            ("task", "Task", "Convert these M queries to use Table.AddColumn…"),
            ("example_input", "Example input", "…"),
            ("example_output", "Example output", "…"),
            ("actual_input", "Your actual input", "…"),
        ],
        "template": ("# TASK\n{task}\n\n# EXAMPLE\nInput:\n```\n{example_input}\n```\n"
                     "Output:\n```\n{example_output}\n```\n\n"
                     "# NOW DO THE SAME FOR\n```\n{actual_input}\n```\n\n"
                     "Match the example's style exactly.\n\n{category_hint}"),
    },
    "repo": {
        "name": "Iterative Repo Upgrade — Read-Only Guardrails",
        "fields": [
            ("goal", "Upgrade goal", "Add error handling to the ETL…"),
            ("repo_context", "Repo context (paste the packer output)", "…"),
            ("scope", "Files in scope", "etl/load.py only"),
        ],
        "template": ("# UPGRADE GOAL\n{goal}\n\n# FILES IN SCOPE\n{scope}\n\n"
                     "# REPO CONTEXT\n```\n{repo_context}\n```\n\n"
                     "# GUARDRAILS (non-negotiable)\n"
                     "- READ-ONLY analysis first: explain what you found before proposing changes.\n"
                     "- Never delete files or data; never invent APIs that don't exist in the context.\n"
                     "- Every change must be the smallest diff that achieves the goal.\n"
                     "- If a test file exists for the area, keep it passing; note how to verify.\n"
                     "- Ask before expanding scope beyond the files listed above.\n\n"
                     "{category_hint}"),
    },
}

CATEGORIES = {
    "DAX Optimization": "Category hint: prefer iterator-free patterns where possible; "
                        "watch filter context vs row context; give the final measure code.",
    "Python / ETL": "Category hint: use Polars or pandas as appropriate; "
                    "handle nulls explicitly; keep it runnable as a script.",
    "App Building": "Category hint: assume Streamlit; keep everything local/offline; "
                    "no placeholder code.",
    "Statistical Modeling": "Category hint: state assumptions; show the math; "
                            "give validation steps.",
    "Business Comms": "Category hint: concise, professional tone; "
                      "lead with the ask; keep it under 150 words unless asked otherwise.",
}


def build_prompt(framework: str, category: str, values: dict) -> str:
    fw = FRAMEWORKS[framework]
    safe = {k: values.get(k, "") for k, _, _ in fw["fields"]}
    safe["category_hint"] = CATEGORIES.get(category, "")
    return fw["template"].format(**safe)


def detect_vars(body: str) -> list[str]:
    return sorted(set(re.findall(r"\{([A-Za-z0-9_ ]+?)\}", body)))


# ------------------------------------------------------------ templates
# Templates live in the central workspace DB (workspace_db.prompt_templates).
# The `path` parameter is kept for signature compatibility: when given it
# is treated as a SQLite database *file* (used by tests for isolation).
# Legacy JSON storage (storage/prompt_templates.json) is imported once by
# workspace_db.import_legacy — never read here.

_ws_con: sqlite3.Connection | None = None


def _workspace_con() -> sqlite3.Connection:
    """Lazily opened central-DB connection (init + one-time legacy import)."""
    global _ws_con
    if _ws_con is None:
        _ws_con = wdb.open_workspace(Path(__file__).parent)
    return _ws_con


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve(path: Path | str | None = None,
             con: sqlite3.Connection | None = None
             ) -> tuple[sqlite3.Connection, bool]:
    """Return ``(connection, owns)`` — ``owns`` means the caller closes it."""
    if con is not None:
        return con, False
    if path is not None:
        c = sqlite3.connect(str(path), check_same_thread=False)
        c.row_factory = sqlite3.Row
        wdb.init_db(c)
        return c, True
    return _workspace_con(), False


def load_custom_templates(path: Path | str | None = None,
                          con: sqlite3.Connection | None = None) -> dict:
    c, owns = _resolve(path, con)
    try:
        rows = c.execute(
            "SELECT name, body FROM prompt_templates ORDER BY name").fetchall()
        return {r["name"]: r["body"] for r in rows}
    finally:
        if owns:
            c.close()


def save_custom_template(name: str, body: str,
                         path: Path | str | None = None,
                         con: sqlite3.Connection | None = None) -> None:
    """Insert or replace a custom template (upsert)."""
    if not name.strip() or not body.strip():
        raise ValueError("Template name and body are required.")
    c, owns = _resolve(path, con)
    try:
        c.execute(
            "INSERT INTO prompt_templates (name, body, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET body=excluded.body, "
            "updated_at=excluded.updated_at",
            (name.strip(), body, _now()))
        c.commit()
    finally:
        if owns:
            c.close()


def update_custom_template(name: str, body: str,
                           path: Path | str | None = None,
                           con: sqlite3.Connection | None = None) -> None:
    """Update the body of an existing template. Raises KeyError when the
    name does not exist (unlike save, this never creates)."""
    if not body.strip():
        raise ValueError("Template body is required.")
    c, owns = _resolve(path, con)
    try:
        cur = c.execute(
            "UPDATE prompt_templates SET body = ?, updated_at = ? "
            "WHERE name = ?", (body, _now(), name.strip()))
        if cur.rowcount == 0:
            raise KeyError(f"No such template: {name!r}")
        c.commit()
    finally:
        if owns:
            c.close()


def delete_custom_template(name: str,
                           path: Path | str | None = None,
                           con: sqlite3.Connection | None = None) -> None:
    c, owns = _resolve(path, con)
    try:
        c.execute("DELETE FROM prompt_templates WHERE name = ?",
                  (name.strip(),))
        c.commit()
    finally:
        if owns:
            c.close()


# ------------------------------------------------------------ masker
# The mask dictionary lives in the central workspace DB
# (workspace_db.mask_map) as plaintext rows on this machine only.
# Legacy JSON storage (storage/mask_map.json) is imported once by
# workspace_db.import_legacy — never read here.


def mask_text(text: str, staff: list[str], stores: list[str],
              metrics: list[str]) -> tuple[str, dict]:
    """Replace PII/schema terms with tokens. Returns (masked, {token: original}).

    Tokens: emails/staff -> User_01…, stores -> Store_01…, metrics -> Metric_A….
    Same original always maps to the same token; longest terms first.
    """
    mapping: dict[str, str] = {}
    counters = {"User_": 0, "Store_": 0}
    metric_n = 0

    def make_token(label: str, original: str) -> str:
        nonlocal metric_n
        for tok, orig in mapping.items():
            if orig == original and tok.startswith(label):
                return tok
        if label == "Metric_":
            metric_n += 1
            tok = f"Metric_{chr(64 + metric_n)}"
        else:
            counters[label] += 1
            tok = f"{label}{counters[label]:02d}"
        mapping[tok] = original
        return tok

    out = EMAIL_RE.sub(lambda m: make_token("User_", m.group(0)), text)
    terms = ([(t, "User_") for t in staff]
             + [(t, "Store_") for t in stores]
             + [(t, "Metric_") for t in metrics])
    for term, label in sorted(terms, key=lambda x: -len(x[0].strip())):
        term = term.strip()
        if not term:
            continue
        pat = re.compile(re.escape(term))
        out = pat.sub(lambda m: make_token(label, m.group(0)), out)
    return out, mapping


def save_mapping(mapping: dict,
                 path: Path | str | None = None,
                 con: sqlite3.Connection | None = None) -> None:
    """Replace the whole mask dictionary (whole-replace, same as the old
    JSON-file semantics: the UI always saves the complete current mapping)."""
    c, owns = _resolve(path, con)
    try:
        c.execute("DELETE FROM mask_map")
        c.executemany("INSERT INTO mask_map (token, original) VALUES (?, ?)",
                      list(mapping.items()))
        c.commit()
    finally:
        if owns:
            c.close()


def load_mapping(path: Path | str | None = None,
                 con: sqlite3.Connection | None = None) -> dict:
    c, owns = _resolve(path, con)
    try:
        rows = c.execute(
            "SELECT token, original FROM mask_map").fetchall()
        return {r["token"]: r["original"] for r in rows}
    finally:
        if owns:
            c.close()


def clear_mapping(path: Path | str | None = None,
                  con: sqlite3.Connection | None = None) -> bool:
    """Permanently delete the local mask dictionary (the plaintext
    {token: original PII} rows). Returns True if any rows were removed."""
    c, owns = _resolve(path, con)
    try:
        cur = c.execute("DELETE FROM mask_map")
        c.commit()
        return cur.rowcount > 0
    finally:
        if owns:
            c.close()


def unmask_text(text: str, mapping: dict) -> str:
    """Swap tokens back to originals (longest token first).

    Also strips a square-bracket wrapper around tokens: LLMs frequently
    echo placeholders as ``[User_01]``, and a naive token swap would leave
    ``[Amy Chan]`` behind. Both passes are longest-token-first so a short
    token can never corrupt a longer one (``User_1`` inside ``User_10``).
    Brackets that do NOT wrap a known token (e.g. ``[note]``) are left
    untouched. The result is clean, copy-pasteable plain text.
    """
    out = text
    for tok in sorted(mapping, key=len, reverse=True):
        out = out.replace(f"[{tok}]", mapping[tok])
    for tok in sorted(mapping, key=len, reverse=True):
        out = out.replace(tok, mapping[tok])
    return out


def highlight_unmasked(restored: str, mapping: dict) -> str:
    """Render restored text as HTML with unmasked keywords highlighted.

    The plain text is ``html.escape``d FIRST; then every restored original
    is wrapped in ``<mark>`` via a single regex pass (longest originals
    first, so overlapping names can't nest). ``<mark>`` tags are the only
    raw HTML emitted — an original containing ``<script>`` is rendered as
    inert text and can never break the preview. Safe to render with
    ``st.markdown(..., unsafe_allow_html=True)``.
    """
    escaped = html.escape(restored)
    originals = sorted({o for o in mapping.values() if o},
                       key=len, reverse=True)
    if not originals:
        return escaped
    pat = re.compile("|".join(re.escape(html.escape(o)) for o in originals))
    return pat.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped)


# ------------------------------------------------------------ repo packer
PACK_EXTS = {".py", ".tmdl", ".sql", ".m", ".md"}
DATA_EXTS = {".csv", ".xlsx", ".xls", ".db", ".sqlite", ".sqlite3", ".parquet"}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules",
             ".idea", ".vscode", "storage", "data"}


def pack_repo(root: str, max_total_chars: int = 120_000,
              max_file_chars: int = 20_000) -> tuple[str, dict]:
    """Bundle code/metadata files into one Markdown block for LLM context.

    Excludes data files (.csv/.xlsx/.db/…) and skipped dirs. Returns
    (markdown, stats).
    """
    root_p = Path(root).expanduser()
    if not root_p.is_dir():
        raise ValueError(f"Not a folder: {root}")
    files: list[Path] = []
    skipped_data, skipped_big = 0, 0
    for p in sorted(root_p.rglob("*")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        ext = p.suffix.lower()
        if ext in DATA_EXTS:
            skipped_data += 1
            continue
        if ext not in PACK_EXTS:
            continue
        files.append(p)
    chunks, total = [], 0
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > max_file_chars:
            text = text[:max_file_chars] + "\n…[truncated: file too large]"
            skipped_big += 1
        rel = p.relative_to(root_p).as_posix()
        fence = "```" + (p.suffix.lstrip(".") or "text")
        chunk = f"\n\n## {rel}\n{fence}\n{text}\n```"
        if total + len(chunk) > max_total_chars:
            chunks.append("\n\n…[truncated: total context budget reached]")
            break
        chunks.append(chunk)
        total += len(chunk)
    md = f"# Repo context: {root_p.name}\n" + "".join(chunks)
    stats = {"files_packed": len(chunks), "chars": total,
             "data_files_excluded": skipped_data,
             "files_truncated": skipped_big}
    return md, stats
