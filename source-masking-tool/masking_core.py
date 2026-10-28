"""Core logic for the Power Apps ALM & Masking Tool. Pure — no ``st.*`` calls.

Workflow this supports (all local, nothing uploaded by this module):
    1. For a Power App: unpack a ``.msapp`` into source code with the
       Power Platform CLI (``pac``). For a PBIP project or any other
       text folder: point the tool at the folder directly (no unpack).
    2. Mask sensitive strings (URLs, table names, ...) in the sources
       for the selected project profile, saving the mapping locally.
    3. Upload the *masked* sources to GitHub for an AI agent to revise.
    4. Download the revised sources, unmask, and finish per profile:
       pack back into a ``.msapp`` (Power App) or open in
       Power BI Desktop (PBIP) / use the files directly (generic).

Security notes (read before touching the mapping file):
    * ``mapping_state.json`` maps masked values BACK to real values — it is
      the key to your sensitive data. It is stored in the app's ``storage/``
      directory (gitignored by the repo root ``.gitignore``: ``storage/``),
      NEVER inside the sources folder, and must never be committed or
      uploaded to GitHub. Uploading it defeats the masking entirely.
    * Masking is plain-text replacement on the selected profile's
      text files only. It does not touch binaries, and it cannot find
      sensitive values that are not in the mapping — always run the
      post-mask verification report and eyeball the result before
      uploading.
    * Replacements run longest-real-value-first so a short key (``Table``)
      can never eat part of a longer one (``TableName``).
"""

import difflib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

# ---------------------------------------------------------------- constants
PAC_TIMEOUT = 600          # seconds for a single pac unpack/pack run
PAC_VERSION_TIMEOUT = 30   # seconds for `pac --version`
# Legacy default: the original Power App profile. New code should use
# PROFILES / get_suffixes() so PBIP and generic folders are scanned too.
SCAN_SUFFIXES = (".pa.yaml", ".json")
POWER_APP_SUFFIXES = SCAN_SUFFIXES
PBIP_SUFFIXES = (".tmdl", ".json", ".pbip")
GENERIC_SUFFIXES = (".txt", ".md", ".yaml", ".yml", ".json", ".tmdl",
                    ".pa.yaml", ".xml")
PROFILES = {
    "power-app": {
        "label": "Power App (.msapp via pac)",
        "suffixes": POWER_APP_SUFFIXES,
        "uses_pac": True,
        "finish": "pack",
    },
    "pbip": {
        "label": "Power BI PBIP project (folder, no pac)",
        "suffixes": PBIP_SUFFIXES,
        "uses_pac": False,
        "finish": "desktop",
    },
    "generic": {
        "label": "Generic text folder",
        "suffixes": GENERIC_SUFFIXES,
        "uses_pac": False,
        "finish": "direct",
    },
    "custom": {
        "label": "Custom suffixes (typed in the UI)",
        "suffixes": GENERIC_SUFFIXES,
        "uses_pac": False,
        "finish": "direct",
    },
}


def parse_custom_suffixes(text):
    """Parse a comma/space-separated suffix list into a tuple.

    Each entry gets a leading dot if missing (``tmdl`` -> ``.tmdl``).
    Raises PacError on an empty result.
    """
    parts = []
    for raw in (text or "").replace(",", " ").split():
        s = raw.strip().lower()
        if not s:
            continue
        if not s.startswith("."):
            s = "." + s
        if s not in parts:
            parts.append(s)
    if not parts:
        raise PacError("Custom suffixes are empty — type at least one "
                       "suffix, e.g. .tmdl, .json")
    return tuple(parts)


def get_suffixes(profile, custom=None):
    """Return the scan suffixes for a profile name.

    ``custom`` is only used when profile == "custom" (a string or a
    tuple/list of suffixes); otherwise the profile's built-in suffixes
    are returned. Unknown profiles raise PacError.
    """
    if profile not in PROFILES:
        raise PacError(f"Unknown project profile: {profile!r} "
                       f"(expected one of {sorted(PROFILES)})")
    if profile == "custom" and custom:
        if isinstance(custom, str):
            return parse_custom_suffixes(custom)
        cleaned = []
        for s in custom:
            s = str(s).strip().lower()
            if s and not s.startswith("."):
                s = "." + s
            if s and s not in cleaned:
                cleaned.append(s)
        if not cleaned:
            raise PacError("Custom suffixes are empty.")
        return tuple(cleaned)
    return PROFILES[profile]["suffixes"]
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
def scan_files(sources_dir, suffixes=None):
    """All files matching ``suffixes`` under ``sources_dir``, recursive.

    ``suffixes`` defaults to the Power App profile (``.pa.yaml`` /
    ``.json``) for backward compatibility; pass
    ``get_suffixes(profile)`` for PBIP / generic / custom projects.
    The mapping file itself is excluded by name, defensively, in case one
    ever lands inside a sources folder. Raises PacError for a bad folder.
    """
    if suffixes is None:
        suffixes = SCAN_SUFFIXES
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    found = []
    for suffix in suffixes:
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


def apply_mapping(sources_dir, mapping, dry_run=False, suffixes=None):
    """Replace mapping keys with values across all scanned files.

    Returns a report dict:
        {"files_scanned", "files_changed", "total",
         "replacements": {key: count}, "per_file": {relpath: count}}.
    With dry_run=True nothing is written — the report is a preview.
    Files are rewritten only when at least one replacement happened.
    """
    pairs = _sorted_pairs(mapping)
    files = scan_files(sources_dir, suffixes=suffixes)
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


def count_occurrences(sources_dir, strings, suffixes=None):
    """Count occurrences of each string across scanned files (no writes).

    Used for post-mask / post-unmask verification: after masking, every
    real value should count 0; after unmasking, every masked value 0.
    """
    files = scan_files(sources_dir, suffixes=suffixes)
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


def mask_directory(sources_dir, mapping, dry_run=False, suffixes=None):
    """Mask a sources folder. Returns the apply_mapping report."""
    errors, _ = validate_mapping(mapping)
    if errors:
        raise PacError(" ".join(errors))
    return apply_mapping(sources_dir, mapping, dry_run=dry_run,
                         suffixes=suffixes)


def unmask_directory(sources_dir, mapping, dry_run=False, suffixes=None):
    """Restore a sources folder from a {real: masked} mapping."""
    return apply_mapping(sources_dir, reverse_mapping(mapping),
                         dry_run=dry_run, suffixes=suffixes)


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
    """Load a mapping JSON file. Raises PacError on any problem.

    Accepts both formats: a bare {real: masked} dict (templates, hand-made
    uploads) and the mapping-state format {"mapping": {...}, ...} written
    by save_mapping_state — uploading a saved state file just works.
    """
    path = Path(path)
    if not path.is_file():
        raise PacError(f"Mapping file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PacError(f"Mapping file is not valid JSON: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("mapping"), dict):
        data = data["mapping"]
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


# ---------------------------------------------------------------- filename /
# folder name obfuscation
def _rename_component(name, pairs):
    """Apply mapping replacements to one path component (longest-first)."""
    new = name
    for real, masked in pairs:
        if real in new:
            new = new.replace(real, masked)
    return new


def _under_git(rel):
    return ".git" in Path(rel).parts


def rename_paths(sources_dir, mapping, dry_run=False, topdown=False):
    """Rename files/folders whose names contain mapping keys.

    Mask direction: topdown=False (bottom-up) — children are renamed
    before their parent folders, so a renamed parent never orphans a
    child path mid-run. Unmask direction: topdown=True — parents first,
    so the walk descends into already-restored folders.

    Only one path component is rewritten at a time, so a mapping key
    containing "/" can never escape its own folder. ``.git`` internals
    are never renamed (renaming them would corrupt a git checkout).
    A rename whose target already exists is SKIPPED, never overwriting.

    Returns {"renames": [(old_rel, new_rel)], "skipped": [(old_rel, reason)],
    "total": len(renames)}. With dry_run=True nothing is renamed.
    """
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    pairs = _sorted_pairs(mapping)
    renames, skipped = [], []
    claimed = set()  # targets already promised this run (dry-run safety)

    def attempt(old_abs, old_rel):
        new_name = _rename_component(old_abs.name, pairs)
        if new_name == old_abs.name or not new_name:
            return None
        new_abs = old_abs.with_name(new_name)
        new_rel = str(Path(old_rel).with_name(new_name))
        if new_rel in claimed or (new_abs.exists() and new_abs != old_abs):
            skipped.append((old_rel, f"target already exists: {new_rel}"))
            return None
        claimed.add(new_rel)
        if not dry_run:
            try:
                os.rename(old_abs, new_abs)
            except OSError as exc:
                skipped.append((old_rel, f"rename failed: {exc}"))
                return None
        renames.append((old_rel, new_rel))
        return new_rel

    for dirpath, dirnames, filenames in os.walk(sources, topdown=topdown):
        rel_dir = os.path.relpath(dirpath, sources)
        if rel_dir != "." and _under_git(rel_dir):
            continue
        if topdown:
            # Parents first: rename dirs, then fix the walk list so it
            # descends into the new names.
            for i, d in enumerate(sorted(dirnames)):
                child_rel = d if rel_dir == "." else f"{rel_dir}/{d}"
                if _under_git(child_rel) or d == ".git":
                    continue
                new = attempt(Path(dirpath) / d, child_rel)
                if new:
                    dirnames[dirnames.index(d)] = new
            for f in sorted(filenames):
                child_rel = f if rel_dir == "." else f"{rel_dir}/{f}"
                attempt(Path(dirpath) / f, child_rel)
        else:
            # Children first: files, then the dirs that hold them.
            for f in sorted(filenames):
                child_rel = f if rel_dir == "." else f"{rel_dir}/{f}"
                attempt(Path(dirpath) / f, child_rel)
            for d in sorted(dirnames):
                if d == ".git":
                    continue
                child_rel = d if rel_dir == "." else f"{rel_dir}/{d}"
                attempt(Path(dirpath) / d, child_rel)
    return {"renames": renames, "skipped": skipped, "total": len(renames)}


# ---------------------------------------------------------------- mapping state
def save_mapping_state(path, mapping, renames=None):
    """Write the mapping state: mapping dict + the rename log.

    The rename log is the audit trail of what Mask renamed (old → new
    relative paths). The state file lives in gitignored storage, never
    in the sources folder, for the same reason as the mapping itself.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {"version": 1, "mapping": dict(mapping),
             "renames": [{"from": a, "to": b}
                         for a, b in (renames or [])]}
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_mapping_state(path):
    """Load a mapping state file. Returns (mapping, renames).

    Accepts the state format and, for files saved by older versions of
    this app, a bare {real: masked} dict (renames then = []).
    """
    path = Path(path)
    if not path.is_file():
        raise PacError(f"Mapping state file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PacError(f"Mapping state file is not valid JSON: {exc}") from exc
    if isinstance(data, dict) and isinstance(data.get("mapping"), dict):
        renames = data.get("renames") or []
        mapping = data["mapping"]
    elif isinstance(data, dict):
        renames, mapping = [], data
    else:
        raise PacError("Mapping state file must be a JSON object.")
    if not all(isinstance(k, str) and isinstance(v, str)
               for k, v in mapping.items()):
        raise PacError("Mapping state must hold {real: masked} string pairs.")
    clean = []
    for r in renames:
        if isinstance(r, dict) and "from" in r and "to" in r:
            clean.append((str(r["from"]), str(r["to"])))
    return mapping, clean


# ---------------------------------------------------------------- diff baseline
SNAPSHOT_MAX_TEXT = 2_000_000  # only store text content for files <= 2 MB


def snapshot_path_for(sources_dir, storage_dir):
    """Deterministic snapshot-file path for one sources folder."""
    resolved = str(Path(sources_dir).expanduser().resolve())
    digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(resolved).name) or "sources"
    return Path(storage_dir) / f"snapshot_{safe}_{digest}.json"


def snapshot_directory(sources_dir, suffixes=None):
    """Fingerprint a sources folder: {relpath: {sha256, content?}}.

    Content is stored only for scanned text files (the selected
    profile's suffixes) under 2 MB, so inline diffs are possible;
    everything else is tracked by hash alone. ``.git`` internals and
    mapping-state files are excluded. The snapshot is taken AFTER
    masking, so it holds masked values only.
    """
    if suffixes is None:
        suffixes = SCAN_SUFFIXES
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    scanned = {str(p.relative_to(sources))
               for p in scan_files(sources, suffixes=suffixes)}
    files = {}
    for path in sorted(sources.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(sources))
        if _under_git(rel) or path.name == MAPPING_STATE_EXCLUDE:
            continue
        raw = path.read_bytes()
        entry = {"sha256": hashlib.sha256(raw).hexdigest(), "content": None}
        if rel in scanned and len(raw) <= SNAPSHOT_MAX_TEXT:
            try:
                entry["content"] = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                entry["content"] = None
        files[rel] = entry
    return {"version": 1, "files": files, "suffixes": list(suffixes)}


def save_snapshot(path, snapshot):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    return path


def load_snapshot(path):
    path = Path(path)
    if not path.is_file():
        raise PacError(
            f"No masked baseline snapshot found ({path}). Snapshots are "
            "created when you Mask from this app — mask first, then the "
            "Diff step can compare the AI-revised sources against it.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise PacError(f"Snapshot file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
        raise PacError("Snapshot file is damaged (no file table). Re-mask "
                       "to create a fresh baseline.")
    return data


def diff_against_snapshot(sources_dir, snapshot, mapping, suffixes=None):
    """Compare current sources against a masked baseline snapshot.

    Returns {"added", "removed", "modified", "renamed": [(old, new)],
    "orphaned_masked": [{"masked", "real"}], "diffs": {relpath: text},
    "counts": {...}}. Renames are detected when a removed file and an
    added file share a hash. A masked value that appears NOWHERE in the
    current contents or filenames is flagged orphaned — the AI renamed or
    deleted it, so Unmask cannot restore it. Diff text is capped at 300
    lines per file.
    """
    if suffixes is None:
        suffixes = tuple(snapshot.get("suffixes") or SCAN_SUFFIXES)
    current = snapshot_directory(sources_dir, suffixes=suffixes)
    old_files = snapshot["files"]
    new_files = current["files"]
    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    modified = sorted(p for p in set(old_files) & set(new_files)
                      if old_files[p]["sha256"] != new_files[p]["sha256"])
    # rename detection: removed + added with identical content hash
    renamed = []
    by_hash_added = {}
    for a in added:
        by_hash_added.setdefault(new_files[a]["sha256"], []).append(a)
    still_removed = []
    for r in removed:
        cands = by_hash_added.get(old_files[r]["sha256"]) or []
        if cands:
            renamed.append((r, cands.pop(0)))
        else:
            still_removed.append(r)
    used_added = {new for _, new in renamed}
    added = [a for a in added if a not in used_added]
    removed = still_removed
    # inline diffs for modified text files
    diffs = {}
    for p in modified:
        old_c = old_files[p].get("content")
        new_c = new_files[p].get("content")
        if old_c is None or new_c is None:
            continue
        lines = list(difflib.unified_diff(
            old_c.splitlines(), new_c.splitlines(),
            fromfile=f"a/{p} (masked baseline)",
            tofile=f"b/{p} (AI revised)", lineterm=""))
        if len(lines) > 300:
            lines = lines[:300] + ["... (diff truncated at 300 lines)"]
        diffs[p] = "\n".join(lines)
    # orphaned masked values: in neither contents nor filenames
    scanned_now = {str(p.relative_to(sources_dir))
                   for p in scan_files(sources_dir, suffixes=suffixes)}
    content_hits = {}
    for p in scanned_now:
        text, _ = _read_text(Path(sources_dir) / p)
        for masked in mapping.values():
            if masked and masked in text:
                content_hits[masked] = True
    name_hits = set()
    for rel in new_files:
        for part in Path(rel).parts:
            for masked in mapping.values():
                if masked and masked in part:
                    name_hits.add(masked)
    orphaned = [{"masked": m, "real": r} for r, m in mapping.items()
                if m and m not in content_hits and m not in name_hits]
    return {"added": added, "removed": removed, "modified": modified,
            "renamed": renamed, "orphaned_masked": orphaned, "diffs": diffs,
            "counts": {"added": len(added), "removed": len(removed),
                       "modified": len(modified), "renamed": len(renamed),
                       "orphaned": len(orphaned)}}


# ---------------------------------------------------------------- leftover scan
LEFTOVER_PATTERNS = [
    ("URL", re.compile(r"https?://[^\s\"'<>]+")),
    ("Email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("Domain", re.compile(
        r"\b(?:[A-Za-z0-9-]+\.)+(?:com|net|org|io|co|ai|app|dev|hk)\b",
        re.IGNORECASE)),
    ("SQL connection", re.compile(
        r"\b(?:server|data source|initial catalog|user id|password)\s*=\s*[^;\s,]+",
        re.IGNORECASE)),
    ("IPv4 address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def scan_leftovers(sources_dir, masked_values=(), limit=500, suffixes=None):
    """Heuristic scan for sensitive-looking strings left after masking.

    Runs over the scanned text files, line by line. A match containing
    any already-masked value is skipped (it is a placeholder, not a
    leak). Returns {"findings": [{file, line, pattern, match}],
    "total": int} — findings are capped at ``limit`` but ``total`` counts
    everything found, so the UI can say "showing first N of M".
    """
    masked = [m for m in masked_values if m]
    findings, total = [], 0
    for path in scan_files(sources_dir, suffixes=suffixes):
        text, _ = _read_text(path)
        rel = str(path.relative_to(sources_dir))
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, rx in LEFTOVER_PATTERNS:
                for m in rx.finditer(line):
                    value = m.group(0)
                    # Skip placeholders: the match is a masked value, or
                    # sits inside one (e.g. a domain inside a masked URL).
                    if any(mv in value or value in mv for mv in masked):
                        continue
                    total += 1
                    if len(findings) < limit:
                        findings.append({"file": rel, "line": lineno,
                                         "pattern": name, "match": value})
    return {"findings": findings, "total": total}


def distinct_leftovers(scan_result):
    """Sorted unique matched strings from a scan_leftovers result."""
    return sorted({f["match"] for f in scan_result["findings"]})


# ---------------------------------------------------------------- templates
def templates_dir(storage_dir):
    return Path(storage_dir) / "templates"


def sanitize_template_name(name):
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip())
    if not clean:
        raise PacError("Please give the template a name (letters, digits, "
                       "- or _).")
    return clean


def save_template(storage_dir, name, mapping):
    if not mapping:
        raise PacError("Cannot save an empty mapping as a template.")
    path = templates_dir(storage_dir) / f"{sanitize_template_name(name)}.json"
    return save_mapping(path, mapping)


def list_templates(storage_dir):
    d = templates_dir(storage_dir)
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_template(storage_dir, name):
    return load_mapping(templates_dir(storage_dir)
                        / f"{sanitize_template_name(name)}.json")


def delete_template(storage_dir, name):
    path = templates_dir(storage_dir) / f"{sanitize_template_name(name)}.json"
    if not path.is_file():
        raise PacError(f"Template not found: {name}")
    path.unlink()
    return name


# ---------------------------------------------------------------- zip export
def zip_sources_bytes(sources_dir):
    """Zip a sources folder (for upload to GitHub / an LLM chat).

    Excludes ``.git`` internals and any mapping-state file, so the zip
    cannot leak the restore key. Returns the zip as bytes.
    """
    sources = Path(sources_dir)
    if not sources.is_dir():
        raise PacError(f"Sources folder not found: {sources_dir}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(sources.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(sources))
            if _under_git(rel) or path.name == MAPPING_STATE_EXCLUDE:
                continue
            zf.write(path, arcname=Path(rel).as_posix())
    return buf.getvalue()
