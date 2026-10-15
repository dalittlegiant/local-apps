"""Shared pure-logic libraries for the Unified Data Studio.

Every module here is Streamlit-free so it can be unit-tested directly.
"""

import shutil
import tempfile
import time
import zipfile
from pathlib import Path


def safe_extractall(zf: zipfile.ZipFile, dest: Path) -> list[str]:
    """Extract a zip without ZipSlip.

    Members that would escape ``dest`` via ``../`` or absolute paths are
    skipped — never extracted. Returns the extracted member names.
    """
    dest = Path(dest).resolve()
    kept: list[str] = []
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        if not target.is_relative_to(dest):
            continue  # path-traversal member — skipped, never extracted
        zf.extract(member, dest)
        kept.append(member.filename)
    return kept


def drop_temp_dir(path: str | Path | None) -> None:
    """Best-effort removal of a ``tempfile.mkdtemp`` directory."""
    if path:
        shutil.rmtree(str(path), ignore_errors=True)


def sweep_stale_temp_dirs(prefix: str, max_age_hours: float = 24) -> int:
    """Delete ``tempfile.mkdtemp(prefix=...)`` leftovers older than
    ``max_age_hours`` from the OS temp dir. Returns the count removed."""
    now = time.time()
    removed = 0
    base = Path(tempfile.gettempdir())
    for p in base.glob(prefix + "*"):
        try:
            if p.is_dir() and now - p.stat().st_mtime > max_age_hours * 3600:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed
