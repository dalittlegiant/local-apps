"""Core logic for the Power Apps ALM & Masking Tool. Pure — no ``st.*`` calls.

Workflow this supports (all local, nothing uploaded by this module):
    1. Unpack a ``.msapp`` into source code with the Power Platform CLI (``pac``).
    2. Mask sensitive strings (URLs, table names, ...) in the unpacked
       ``.pa.yaml`` / ``.json`` sources, saving the mapping locally.
    3. Upload the *masked* sources to GitHub for an AI agent to revise.
    4. Download the revised sources, unmask, pack back into a ``.msapp``.

Security notes (read before touching the mapping file):
    * ``mapping_state.json`` maps masked values BACK to real values — it is
      the key to your sensitive data. It is stored in the app's ``storage/``
      directory (gitignored by the repo root ``.gitignore``: ``storage/``),
      NEVER inside the sources folder, and must never be committed or
      uploaded to GitHub. Uploading it defeats the masking entirely.
    * Masking is plain-text replacement on ``.pa.yaml`` / ``.json`` files
      only. It does not touch binaries, and it cannot find sensitive values
      that are not in the mapping — always run the post-mask verification
      report and eyeball the result before uploading.
    * Replacements run longest-real-value-first so a short key (``Table``)
      can never eat part of a longer one (``TableName``).
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

# ---------------------------------------------------------------- constants
PAC_TIMEOUT = 600          # seconds for a single pac unpack/pack run
PAC_VERSION_TIMEOUT = 30   # seconds for `pac --version`
SCAN_SUFFIXES = (".pa.yaml", ".json")
MAPPING_FILENAME = "mapping_state.json"
MAPPING_STATE_EXCLUDE = "mapping_state.json"


class PacError(Exception):
    """User-friendly error: message is safe to show verbatim in the UI."""


# ---------------------------------------------------------------- pac CLI
def find_pac():
    """Return the ``pac`` executable path, or None when it is not on PATH."""
    return shutil.which("pac")


def check_pac():
    """Check whether the Power Platform CLI is usable.

    Returns {"available": bool, "version": str|None, "hint": str|None}.
    Never raises — a missing CLI is a normal, reportable state.
    """
    exe = find_pac()
    if not exe:
        return {
            "available": False,
            "version": None,
            "hint": ("The Power Platform CLI (pac) was not found on this machine. "
                     "Install it from the Microsoft docs "
                     "(aka.ms/PowerAppsCLI) or with: "
                     "dotnet tool install --global Microsoft.PowerApps.CLI.Tool"),
        }
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True,
                              text=True, timeout=PAC_VERSION_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "version": None,
                "hint": "Found a `pac` executable but it did not answer "
                        "`pac --version` — reinstall the Power Platform CLI."}
    version = (proc.stdout or proc.stderr).strip().splitlines()
    return {"available": proc.returncode == 0,
            "version": version[0] if version else None,
            "hint": None if proc.returncode == 0 else
            "pac answered with an error — reinstall the Power Platform CLI."}


def run_pac(args, timeout=PAC_TIMEOUT):
    """Run one ``pac`` command (list form — no shell, no quoting pitfalls).

    ``args`` is the argument list *after* ``pac`` (e.g. ["canvas", "unpack",
    "--msapp", ...]). Returns {"returncode", "stdout", "stderr"}.
    Raises PacError when pac is missing, times out, or exits non-zero
    (the stderr tail is included so the UI can show pac's own message).
    """
    exe = find_pac()
    if not exe:
        raise PacError(
            "The Power Platform CLI (pac) is not installed on this machine, "
            "so this step cannot run. Install it from the Microsoft docs "
            "(aka.ms/PowerAppsCLI), then restart Streamlit and try again.")
    try:
        proc = subprocess.run([exe] + list(args), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise PacError(
            f"pac took longer than {timeout} seconds and was stopped. "
            "The app may be very large — try again, or run the same "
            "command in a terminal to see its progress.") from None
    except OSError as exc:
        raise PacError(f"Could not start pac: {exc}") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()
        tail = "\n".join(tail.splitlines()[-15:])
        raise PacError(
            f"pac exited with code {proc.returncode}."
            + (f"\npac said:\n{tail}" if tail else
               "\n(pac printed no error detail — check the paths and try again.)"))
    return {"returncode": proc.returncode,
            "stdout": proc.stdout or "", "stderr": proc.stderr or ""}


def unpack_msapp(msapp_path, sources_dir, timeout=PAC_TIMEOUT):
    """``pac canvas unpack --msapp <file> --sources <folder>``.

    Validates paths first so a typo fails fast with a clear message
    instead of a cryptic pac error. Returns the run_pac result dict.
    """
    msapp = Path(msapp_path)
    if not msapp.is_file():
        raise PacError(f"Source .msapp file not found: {msapp_path}")
    if msapp.suffix.lower() != ".msapp":
        raise PacError(f"Expected a .msapp file, got: {msapp_path}")
    sources = Path(sources_dir)
    if not str(sources_dir).strip():
        raise PacError("Please enter a destination folder for the sources.")
    # pac creates the sources folder itself; its parent must exist.
    sources.parent.mkdir(parents=True, exist_ok=True)
    return run_pac(["canvas", "unpack", "--msapp", str(msapp),
                    "--sources", str(sources)], timeout=timeout)


def pack_msapp(sources_dir, msapp_path, timeout=PAC_TIMEOUT):
    """``pac canvas pack --sources <folder> --msapp <file>``.

    Validates the sources folder first; creates the output file's parent
    folders when they are missing. Returns the run_pac result dict.
    """
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    out = Path(msapp_path)
    if not str(msapp_path).strip():
        raise PacError("Please enter an output path for the new .msapp file.")
    if out.suffix.lower() != ".msapp":
        raise PacError(f"Output file should end with .msapp, got: {msapp_path}")
    out.parent.mkdir(parents=True, exist_ok=True)
    return run_pac(["canvas", "pack", "--sources", str(sources),
                    "--msapp", str(out)], timeout=timeout)


# ---------------------------------------------------------------- scanning
def scan_files(sources_dir):
    """All ``.pa.yaml`` / ``.json`` files under ``sources_dir``, recursive.

    The mapping file itself is excluded by name, defensively, in case one
    ever lands inside a sources folder. Raises PacError for a bad folder.
    """
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    found = []
    for suffix in SCAN_SUFFIXES:
        found.extend(p for p in sources.rglob(f"*{suffix}")
                     if p.name != MAPPING_STATE_EXCLUDE and p.is_file())
    return sorted(found, key=lambda p: str(p.relative_to(sources)))


def _read_text(path):
    """Read a source file as text. Returns (text, had_bom).

    Tries utf-8 (with BOM stripped), then cp1252, then latin-1, so a
    stray encoding never blocks the whole run. The BOM flag lets the
    writer restore the file byte-for-byte apart from replacements.
    """
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(enc), had_bom
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1"), had_bom


def _write_text(path, text, had_bom):
    data = text.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    path.write_bytes(data)


def _sorted_pairs(mapping):
    """Mapping pairs sorted longest-key-first (see module docstring)."""
    return sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)


def apply_mapping(sources_dir, mapping, dry_run=False):
    """Replace mapping keys with values across all scanned files.

    Returns a report dict:
        {"files_scanned", "files_changed", "total",
         "replacements": {key: count}, "per_file": {relpath: count}}.
    With dry_run=True nothing is written — the report is a preview.
    Files are rewritten only when at least one replacement happened.
    """
    pairs = _sorted_pairs(mapping)
    files = scan_files(sources_dir)
    report = {"files_scanned": len(files), "files_changed": 0, "total": 0,
              "replacements": {k: 0 for k, _ in pairs}, "per_file": {}}
    for path in files:
        text, had_bom = _read_text(path)
        new_text, count = text, 0
        for real, masked in pairs:
            n = new_text.count(real)
            if n:
                new_text = new_text.replace(real, masked)
                report["replacements"][real] += n
                count += n
        if count:
            report["per_file"][str(path.relative_to(sources_dir))] = count
            report["total"] += count
            if not dry_run:
                _write_text(path, new_text, had_bom)
                report["files_changed"] += 1
        elif not dry_run:
            pass  # unchanged files are left byte-identical
    if dry_run:
        report["files_changed"] = len(report["per_file"])
    return report


def count_occurrences(sources_dir, strings):
    """Count occurrences of each string across scanned files (no writes).

    Used for post-mask / post-unmask verification: after masking, every
    real value should count 0; after unmasking, every masked value 0.
    """
    files = scan_files(sources_dir)
    counts = {s: 0 for s in strings}
    for path in files:
        text, _ = _read_text(path)
        for s in strings:
            counts[s] += text.count(s)
    return counts


# ---------------------------------------------------------------- mapping
def validate_mapping(mapping):
    """Validate a {real: masked} dict. Returns (errors, warnings) lists.

    Errors block the run; warnings are shown but do not block, except
    duplicate masked values, which make unmasking ambiguous — those are
    returned as errors too.
    """
    errors, warnings = [], []
    if not isinstance(mapping, dict) or not mapping:
        return ["The mapping is empty — add at least one row."], []
    seen_masked = {}
    for real, masked in mapping.items():
        if not isinstance(real, str) or not real.strip():
            errors.append("A mapping row has an empty real value.")
        if not isinstance(masked, str) or not masked.strip():
            errors.append(f"Real value {real!r} has an empty masked value.")
        if isinstance(masked, str) and masked in seen_masked:
            errors.append(
                f"Masked value {masked!r} is used for both "
                f"{seen_masked[masked]!r} and {real!r} — unmasking would be "
                "ambiguous. Give each real value a distinct masked value.")
        seen_masked[masked] = real
    reals = set(mapping)
    for real, masked in mapping.items():
        if masked in reals and masked != real:
            warnings.append(
                f"Masked value {masked!r} is itself another real value — "
                "masking then unmasking in the wrong order could swap them. "
                "Prefer masked values that appear nowhere in the sources.")
    return errors, warnings


def reverse_mapping(mapping):
    """Swap {real: masked} to {masked: real} for unmasking.

    Raises PacError on duplicate masked values (ambiguous restore).
    """
    reversed_map = {}
    for real, masked in mapping.items():
        if masked in reversed_map:
            raise PacError(
                f"Cannot unmask: masked value {masked!r} maps back to both "
                f"{reversed_map[masked]!r} and {real!r}. Fix the mapping "
                "file first so each masked value is unique.")
        reversed_map[masked] = real
    return reversed_map


def mask_directory(sources_dir, mapping, dry_run=False):
    """Mask a sources folder. Returns the apply_mapping report."""
    errors, _ = validate_mapping(mapping)
    if errors:
        raise PacError(" ".join(errors))
    return apply_mapping(sources_dir, mapping, dry_run=dry_run)


def unmask_directory(sources_dir, mapping, dry_run=False):
    """Restore a sources folder from a {real: masked} mapping."""
    return apply_mapping(sources_dir, reverse_mapping(mapping),
                         dry_run=dry_run)


def mapping_path_for(sources_dir, storage_dir):
    """Deterministic mapping-file path for one sources folder.

    The filename carries the folder name plus a short hash of its absolute
    path, so two projects with the same folder name never share a file.
    The file lives in ``storage_dir`` (gitignored), never in the sources
    folder itself — it must not be uploaded to GitHub with the sources.
    """
    resolved = str(Path(sources_dir).expanduser().resolve())
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(resolved).name) or "sources"
    return Path(storage_dir) / f"mapping_{safe}_{digest}.json"


def save_mapping(path, mapping):
    """Write a mapping as indented JSON (UTF-8, human-readable)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_mapping(path):
    """Load a mapping JSON file. Raises PacError on any problem."""
    path = Path(path)
    if not path.is_file():
        raise PacError(f"Mapping file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PacError(f"Mapping file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise PacError("Mapping file must be a JSON object of "
                       "{real value: masked value} string pairs.")
    return data


def backup_directory(sources_dir, backup_root):
    """Copy a sources folder to a timestamped backup (excludes .git).

    Returns the backup path. Used as an optional safety net before
    masking — unmasking via the mapping is the normal restore path;
    the backup is the belt-and-braces copy.
    """
    import datetime
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = Path(backup_root) / f"{sources.name}_{stamp}"
    if dest.exists():
        dest = Path(backup_root) / f"{sources.name}_{stamp}_2"
    shutil.copytree(sources, dest, ignore=shutil.ignore_patterns(".git"))
    return dest
