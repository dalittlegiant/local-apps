# Source Masking Tool — Developer Guidelines (generalised)

> Shared repo conventions (testing, encoding, git/PAT, security) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app.

## Layout

```
source-masking-tool/
├── app.py                 # Streamlit UI only (4 steps + pac check)
├── masking_core.py        # pure logic, ZERO st.* imports (unit-testable)
├── requirements.txt       # streamlit + pandas (stdlib otherwise)
├── tests/run_tests.py     # 33 checks, no Streamlit needed
└── storage/               # gitignored: mapping_*.json + backups/
```

Runs standalone (`streamlit run app.py`, guarded `set_page_config`) and as
a launcher page (`../source-masking-tool/app.py`, Governance & Security
pillar). The launcher owns page config in that mode.

## Profiles (2026-10-28 generalisation)

Project type is chosen in the UI before masking; every scan/mask/unmask/
diff/leftover call passes that profile's suffixes through
`masking_core.get_suffixes(profile)`:

- `power-app` — `.pa.yaml`, `.json`; only profile that uses `pac`
  Unpack/Pack. Default for backward compatibility in core calls.
- `pbip` — `.tmdl`, `.json`, `.pbip`; no pac. Point the sources folder
  at a COPY of the PBIP project folder (.pbip + .SemanticModel + .Report).
  After unmasking, open it in Power BI Desktop to refresh/test/publish.
- `generic` — `.txt`, `.md`, `.yaml`, `.yml`, `.json`, `.tmdl`,
  `.pa.yaml`, `.xml`; no pac, use files directly after unmasking.
- `custom` — suffixes typed in the UI (comma-separated); no pac.

Do NOT switch profile after masking without re-masking: snapshot/diff/
mapping must use the same suffix set, or files scanned under one profile
will look added/removed under another. Snapshot records its suffixes.

## Core design (masking_core.py)

- **pac runner**: `run_pac()` uses list-form `subprocess.run` (no shell, so
  Windows paths with spaces need no quoting). `FileNotFoundError` → a
  `PacError` telling the user pac is not installed (aka.ms/PowerAppsCLI),
  never a crash. Non-zero exit → `PacError` with pac's stderr tail.
  Timeout 600 s for unpack/pack, 30 s for `--version`.
- **Path validation before subprocess**: unpack requires an existing
  `.msapp` file; pack requires an existing sources folder and a `.msapp`
  output path (parents auto-created). Typos fail fast, in plain language.
- **Masking = exact-text replacement** on `*.pa.yaml` / `*.json` files,
  recursive, longest-real-value-first (so `Table` never half-eats
  `TableName`). Files are rewritten only when changed; BOMs are preserved;
  encoding fallback is utf-8 → cp1252 → latin-1. Other suffixes
  (`.txt`, binaries) are never touched.
- **Verification is built into the UI**: after masking, real-value counts
  must be 0; after unmasking, masked-value counts must be 0. Leftovers mean
  the value lives in an unscanned file or a different spelling — surfaced,
  never silently ignored.
- **Mapping storage (security-critical)**: `mapping_path_for()` names the
  file `mapping_<folder>_<8-hex path hash>.json` inside the app's
  `storage/` dir (repo `.gitignore` already excludes `storage/`). It is
  NEVER written inside the sources folder. The mapping file maps masked
  values back to real ones — uploading it to GitHub defeats the masking.
  Same warning applies to the original `.msapp`, to `storage/backups/`,
  and to mapping templates. The state file additionally records the
  rename log (`from` → `to` relative paths) for audit.
- **Validation**: empty keys/values rejected; duplicate masked values are
  errors (unmasking would be ambiguous); a masked value that is itself
  another real value warns (mask/unmask order could swap them).
- **Backup** (optional checkbox): `shutil.copytree` to a timestamped
  `storage/backups/` folder, excluding `.git` (sources folders are often
  git checkouts after the GitHub round-trip).

## UI conventions (app.py)

- Session keys prefixed `smk_`. One shared sources-folder input at the top
  feeds all four steps (no per-step retyping, no widget-state sync hacks).
- Per-step status lines (`success` / `error` / `info`) live in session
  state and render at the top of each card; pac stdout/stderr go in
  collapsible expanders, never in the main flow. Step order is ① Unpack,
  ② Mask, ③ Diff, ④ Unmask, ⑤ Pack.
- Mapping editor uses `st.data_editor(num_rows="dynamic")` with the
  explicit-commit pattern: edits are committed only on "Save mapping"
  (rows with a real value but no masked value block the save). The editor
  key is versioned (`map_editor_v{n}`) and bumped on JSON load so a loaded
  mapping reliably refreshes the widget.
- Mapping JSON upload is explicit ("Load this JSON into the editor" button),
  not auto-applied, so it can never overwrite a just-saved edit on rerun.
- All actions wrap `PacError` (user-friendly) and generic `Exception`
  (unexpected error, no crash) around the core call.

## Workflow the app assumes

Unpack → mask (contents + file/folder names) → leftover scan → upload
ONLY the masked sources folder to GitHub (or the ZIP for a one-off) →
AI revises → download revised sources over the folder → diff against
the masked baseline → unmask (names first, then contents) → pack a NEW
`.msapp` (never overwrite the original) → import into Power Apps. After
the GitHub round-trip, diff the revised sources against the masked copy
before unmasking: if the AI renamed a masked value, unmasking cannot
restore it, and the diff is where that gets caught.

## Tests

```
python3 tests/run_tests.py        # 65 checks, no Streamlit needed
```

Covers: mask/unmask round-trip, dry-run writes nothing, longest-first
replacement, mapping save/load + per-folder path naming, validation and
reverse-collision errors, BOM preservation, backup (excludes `.git`),
pac-missing friendly error, bad-path errors for unpack/pack/scan,
filename/folder renames (bottom-up mask, top-down unmask, collision
never overwrites, `.git` never renamed, dry-run), full round-trip with
names, mapping-state format + bare-dict backward compatibility,
snapshot/diff (modified/added/removed/renamed-by-hash, orphaned masked
values, inline diffs), leftover-scan patterns + masked-value exclusion,
templates (save/list/load/delete), and ZIP export exclusions.

## Filename / folder name obfuscation

- Same mapping dict drives renames as contents. Mask renames bottom-up
  (`rename_paths(..., topdown=False)`): files, then the folders holding
  them, so a renamed parent never orphans a child mid-run. Unmask
  renames top-down (`topdown=True`): parents first, with the walk list
  updated in place so it descends into restored names.
- Only one path component is rewritten at a time, so a mapping key
  containing `/` cannot escape its folder. `.git` internals are never
  renamed. A rename whose target exists is recorded in `skipped` and
  left alone — never overwritten.
- The Mask step saves a mapping state file
  (`{"version": 1, "mapping": {...}, "renames": [{from, to}]}`) instead
  of a bare dict. `load_mapping` unwraps the state format, so uploading
  a saved state file works anywhere a mapping JSON is accepted, and
  `load_mapping_state` returns the rename log for audit display.

## Diff baseline (Step 3)

- Mask saves a snapshot (`snapshot_<folder>_<hash>.json`) of the masked
  sources: SHA-256 for every file, plus full text for scanned
  `.pa.yaml` / `.json` files under 2 MB. The snapshot holds masked
  values only and lives in gitignored storage.
- `diff_against_snapshot` reports added / removed / modified / renamed
  (removed + added sharing a hash) files, inline unified diffs (capped
  at 300 lines/file) for modified text files, and orphaned masked
  values — a masked value present in neither current contents nor
  current filenames. Orphaned = the AI renamed or deleted it, so Unmask
  cannot restore it; the UI shows these as errors, not warnings.

## Leftover scan, templates, ZIP

- `scan_leftovers` (URLs, emails, domains, SQL-connection fragments,
  IPv4) runs automatically after Mask and on demand. A match that is,
  or sits inside, an already-masked value is excluded. The UI offers to
  append distinct leftovers to the mapping editor with empty masked
  cells — the user fills them, saves, and re-masks.
- Templates (`storage/templates/<name>.json`, bare-dict format) save and
  load whole mappings; names are sanitized to `[A-Za-z0-9_-]`.
- `zip_sources_bytes` zips the sources folder excluding `.git` and any
  mapping-state file. The UI prepares the zip on button click (not on
  every rerun) and then offers the download.
