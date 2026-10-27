# Power Apps ALM & Masking Tool — Developer Guidelines

> Shared repo conventions (testing, encoding, git/PAT, security) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app.

## Layout

```
power-apps-alm-masking/
├── app.py                 # Streamlit UI only (4 steps + pac check)
├── pac_core.py            # pure logic, ZERO st.* imports (unit-testable)
├── requirements.txt       # streamlit + pandas (stdlib otherwise)
├── tests/run_tests.py     # 33 checks, no Streamlit needed
└── storage/               # gitignored: mapping_*.json + backups/
```

Runs standalone (`streamlit run app.py`, guarded `set_page_config`) and as
a launcher page (`../power-apps-alm-masking/app.py`, Governance & Security
pillar). The launcher owns page config in that mode.

## Core design (pac_core.py)

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
  Same warning applies to the original `.msapp` and to `storage/backups/`.
- **Validation**: empty keys/values rejected; duplicate masked values are
  errors (unmasking would be ambiguous); a masked value that is itself
  another real value warns (mask/unmask order could swap them).
- **Backup** (optional checkbox): `shutil.copytree` to a timestamped
  `storage/backups/` folder, excluding `.git` (sources folders are often
  git checkouts after the GitHub round-trip).

## UI conventions (app.py)

- Session keys prefixed `pam_`. One shared sources-folder input at the top
  feeds all four steps (no per-step retyping, no widget-state sync hacks).
- Per-step status lines (`success` / `error` / `info`) live in session
  state and render at the top of each card; pac stdout/stderr go in
  collapsible expanders, never in the main flow.
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

Unpack → mask → upload ONLY the masked sources folder to GitHub → AI
revises → download revised sources over the folder → unmask → pack a NEW
`.msapp` (never overwrite the original) → import into Power Apps. After
the GitHub round-trip, diff the revised sources against the masked copy
before unmasking: if the AI renamed a masked value, unmasking cannot
restore it, and the diff is where that gets caught.

## Tests

```
python3 tests/run_tests.py        # 33 checks, no Streamlit needed
```

Covers: mask/unmask round-trip, dry-run writes nothing, longest-first
replacement, mapping save/load + per-folder path naming, validation and
reverse-collision errors, BOM preservation, backup (excludes `.git`),
pac-missing friendly error, and bad-path errors for unpack/pack/scan.
