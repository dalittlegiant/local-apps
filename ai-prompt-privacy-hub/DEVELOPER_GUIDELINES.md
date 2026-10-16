# Developer Guidelines — AI Prompt & Privacy Hub

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Write high-precision AI prompts systematically and sanitize sensitive
company data locally before it reaches any cloud LLM — 100% offline.

## Layout

```
ai-prompt-privacy-hub/
├── app.py                  # Streamlit UI only
├── prompt_core.py          # pure logic — no st.*
├── workspace_db.py         # central workspace DB (copy; canonical in vault)
├── storage/                # legacy JSON (one-time import only, gitignored)
├── tests/run_tests.py      # 54 checks, no Streamlit needed
└── requirements.txt
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`pp10_` prefix; no `st.set_page_config` (suite launcher owns it).

## Functions & methodology (`prompt_core.py`, all pure)

- `FRAMEWORKS` — rtc (Role/Task/Context), cot (Chain-of-Thought), fewshot,
  repo (Iterative Repo Upgrade with read-only guardrails). Each: named
  fields + a `str.format` template. `CATEGORIES` appends a tailored hint
  (DAX, Python/ETL, App Building, Statistical Modeling, Business Comms).
- `build_prompt(framework, category, values)` — fills fields + category hint.
- Custom templates: `save/load/delete_custom_template` on the central
  workspace DB table `prompt_templates` (via `workspace_db.open_workspace`,
  cached in session state by `app.py:_con()`); `update_custom_template`
  updates an existing name only (raises `KeyError` when missing).
  `detect_vars` finds `{vars}` for the fill-in form. Legacy
  `storage/prompt_templates.json` is imported once by
  `workspace_db.import_legacy` and never read directly.
- `mask_text(text, staff, stores, metrics)` — emails via regex → `User_01…`;
  custom terms (longest first) → staff `User_NN`, stores `Store_NN`,
  metrics `Metric_A…`. Same original always reuses its token. Returns
  `(masked, {token: original})`.
- `save/load_mapping` — central workspace DB table `mask_map` (whole-dict
  replace, same as the old JSON semantics); `clear_mapping()` deletes the
  rows; `unmask_text` swaps tokens back longest-first (exact round-trip)
  and strips a square-bracket wrapper around tokens (`[User_01]` →
  `Amy Chan`, brackets gone — LLMs echo placeholders bracketed). Brackets
  not wrapping a known token are left alone. Output is clean
  copy-pasteable plain text.
- `highlight_unmasked(restored, mapping)` — HTML preview of restored text:
  `html.escape` FIRST, then a single longest-first regex pass wraps each
  restored original in `<mark>` (the only raw HTML emitted, so an original
  containing `<script>` renders as inert text). Rendered via
  `st.markdown(..., unsafe_allow_html=True)` in the Unmask tab preview only;
  `st.code` beside it holds the clean text with a copy button.
- `pack_repo(root, …)` — walks a folder, packs `.py/.tmdl/.sql/.m/.md`
  into one Markdown block; **strictly excludes** `.csv/.xlsx/.db/.parquet`
  and skips `.git/__pycache__/storage/data` etc.; per-file and total char
  caps with truncation notes. Raises `ValueError` on a bad path.

## App-specific conventions

- Mask before sending anything to a cloud LLM; the mapping never leaves
  the machine (and is gitignored).
- Metric tokens are letters (`Metric_A`) so they read naturally in code.

## Testing

`python3 tests/run_tests.py` (temp DBs only) covers: all 4 frameworks +
category hints, guardrail text, var detection, template save/load/upsert/
update/delete + validation + legacy `path` fallback, email/name/store/metric
masking, token formats, token reuse, longest-term-first, exact mask→unmask
round-trip, bracket-wrapped token stripping (mixed/bare/adjacent/boundary/
non-token-bracket/longest-token-first), highlight preview (mark wrapping,
HTML escaping, evil-original safety, longest-original-wins, adjacent
originals), mapping save/load/whole-replace/clear round-trip, legacy JSON
import (templates + mask map, idempotent), packer inclusion/exclusion/stats,
bad-folder rejection. `AppTest` boot verified for `app.py`.

## Future work

- Named masking profiles (per-project term lists).
- Token-count estimate before sending to an LLM.
- Diff view of masked vs original.

### Mask-map hygiene (2026-10-15, central DB 2026-10-16)

The mask dictionary holds the plaintext {token: original PII} mapping, local
only — since 2026-10-16 as rows in the central workspace DB table `mask_map`
(previously `storage/mask_map.json`, one-time imported). `prompt_core.clear_mapping()`
+ the "Clear Local Mask Dictionary" button permanently delete the rows; the UI
caption states the contents and location.
