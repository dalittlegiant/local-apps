"""Core logic for the AI Prompt & Privacy Hub. Pure — no ``st.*`` calls.

Covers: framework-based prompt assembly (RTC / CoT / Few-Shot / Repo
Upgrade), custom template storage, reversible PII/schema masking, and the
local repo context packer.
"""

import html
import json
import re
from pathlib import Path

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
def _tpl_path() -> Path:
    p = Path(__file__).resolve().parent / "storage"
    p.mkdir(exist_ok=True)
    return p / "prompt_templates.json"


def load_custom_templates(path: Path | None = None) -> dict:
    path = Path(path) if path else _tpl_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_custom_template(name: str, body: str, path: Path | None = None) -> None:
    if not name.strip() or not body.strip():
        raise ValueError("Template name and body are required.")
    path = Path(path) if path else _tpl_path()
    tpl = load_custom_templates(path)
    tpl[name.strip()] = body
    path.write_text(json.dumps(tpl, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def delete_custom_template(name: str, path: Path | None = None) -> None:
    path = Path(path) if path else _tpl_path()
    tpl = load_custom_templates(path)
    tpl.pop(name, None)
    path.write_text(json.dumps(tpl, indent=2, ensure_ascii=False),
                    encoding="utf-8")


# ------------------------------------------------------------ masker
def _map_path() -> Path:
    p = Path(__file__).resolve().parent / "storage"
    p.mkdir(exist_ok=True)
    return p / "mask_map.json"


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


def save_mapping(mapping: dict, path: Path | None = None) -> Path:
    path = Path(path) if path else _map_path()
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_mapping(path: Path | None = None) -> dict:
    path = Path(path) if path else _map_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def clear_mapping(path: Path | None = None) -> bool:
    """Permanently delete the local mask dictionary (the plaintext
    {token: original PII} mapping). Returns True if a file was removed."""
    path = Path(path) if path else _map_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


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
