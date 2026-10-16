"""Pure logic for the Linked Data Folder feature. No ``st.*`` calls.

A linked folder is a local directory whose files are auto-loaded into the
Command Center's input slots by conventional filename. Manual uploads always
take precedence over linked files. Reads only — nothing is ever written
into the linked folder.

The link itself (just the folder path) is persisted to
``<app>/storage/link.json``; ``storage/`` is gitignored.
"""

import io
import json
from pathlib import Path

import pandas as pd


# slot key (matches each st.file_uploader key in app.py) ->
# (conventional filename stem, allowed extensions in preference order)
LINKED_SLOTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "rls_hr":      ("HR Staff List",    ("xlsx", "xls")),
    "rls_rules":   ("Rule_Book",        ("xlsx", "xls", "csv")),
    "rls_ex":      ("Exceptions",       ("xlsx", "xls", "csv")),
    "rls_sm":      ("Store_Master",     ("xlsx", "xls", "csv")),
    "delta_old":   ("Previous HR List", ("xlsx", "xls")),
    "delta_new":   ("New HR List",      ("xlsx", "xls")),
    "delta_rules": ("Rule_Book",        ("xlsx", "xls", "csv")),
    "audit_load":  ("Access_Audit",     ("xlsx", "xls", "csv")),
    "gap_hr":      ("HR Staff List",    ("xlsx", "xls")),
    "gap_rules":   ("Rule_Book",        ("xlsx", "xls", "csv")),
}


# ------------------------------------------------------------ link file
def _storage_dir(storage: Path | None = None) -> Path:
    d = Path(storage) if storage else Path(__file__).resolve().parent / "storage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _link_path(storage: Path | None = None) -> Path:
    return _storage_dir(storage) / "link.json"


def load_link(storage: Path | None = None) -> str | None:
    """Return the linked folder path, or None if not linked."""
    p = _link_path(storage)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        folder = str(data.get("folder", "")).strip()
        return folder or None
    except (json.JSONDecodeError, OSError, AttributeError):
        return None


def save_link(folder: str, storage: Path | None = None) -> str:
    """Persist a linked folder. Raises ValueError if not a directory."""
    folder = str(folder or "").strip().strip("\"'")
    if not folder:
        raise ValueError("Please enter a folder path.")
    target = Path(folder).expanduser()
    if not target.is_dir():
        raise ValueError(f"Not a folder: {folder}")
    resolved = str(target.resolve())
    _link_path(storage).write_text(json.dumps({"folder": resolved}, indent=2),
                                   encoding="utf-8")
    return resolved


def clear_link(storage: Path | None = None) -> None:
    _link_path(storage).unlink(missing_ok=True)


# ------------------------------------------------------------ resolution
def resolve_slot(folder: str | Path, slot: str) -> Path | None:
    """Find the conventional file for a slot (top level of folder only).

    Case-insensitive stem match; when several extensions exist the first
    in the slot's preference order wins (e.g. .xlsx over .csv).
    """
    stem, exts = LINKED_SLOTS[slot]
    base = Path(folder).expanduser()
    if not base.is_dir():
        return None
    try:
        entries = [p for p in base.iterdir() if p.is_file()]
    except OSError:
        return None
    for ext in exts:
        for p in entries:
            if p.stem.lower() == stem.lower() and p.suffix.lower() == f".{ext}":
                return p
    return None


def scan_folder(folder: str | Path) -> dict[str, Path]:
    """Resolve every slot against the folder. Returns {slot: path}."""
    return {slot: p for slot in LINKED_SLOTS
            if (p := resolve_slot(folder, slot)) is not None}


class LinkedFile(io.BytesIO):
    """A disk file masquerading as a Streamlit UploadedFile.

    ``io.BytesIO`` already provides ``read``/``seek``/``getvalue``, so the
    existing ``read_table_upload`` / ``pd.read_excel`` call sites work
    unchanged. ``.name`` mirrors the UploadedFile attribute.
    """

    def __init__(self, path: str | Path):
        super().__init__(Path(path).read_bytes())
        self.name = Path(path).name
        self.disk_path = str(path)


def pick_source(slot: str, uploaded, folder: str | Path | None):
    """Manual upload wins; else the linked file; else None.

    ``uploaded`` is a Streamlit UploadedFile or None (falsy when empty).
    """
    if uploaded:
        return uploaded
    if folder:
        path = resolve_slot(folder, slot)
        if path is not None:
            return LinkedFile(path)
    return None


# ------------------------------------------------------------ readers
def read_csv_bytes(raw: bytes) -> tuple[pd.DataFrame, str]:
    """Robust CSV reader. Tries utf-8-sig first (handles BOM + most files),
    then plain utf-8, then cp1252 (covers é/ü-style Latin characters that
    break utf-8 decoding), with latin-1 as the final safety net."""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, encoding=enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1"), "latin-1"


def _clean_str_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def read_table_upload(uploaded) -> pd.DataFrame:
    """Read a CSV or Excel upload (or LinkedFile) into a cleaned string dataframe.

    Excel uploads (.xlsx/.xls) sidestep CSV encoding issues entirely.
    The detected encoding is stored on df.attrs['source_encoding'].
    """
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded, dtype=str)
        enc = "excel"
    else:
        df, enc = read_csv_bytes(uploaded.getvalue())
    df = _clean_str_df(df)
    df.attrs["source_encoding"] = enc
    return df
