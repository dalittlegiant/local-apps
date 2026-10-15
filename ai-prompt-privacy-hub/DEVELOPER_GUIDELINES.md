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
├── storage/                # prompt_templates.json, mask_map.json (gitignored)
├── tests/run_tests.py      # 29 checks, no Streamlit needed
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
- Custom templates: `save/load/delete_custom_template` (JSON in `storage/`);
  `detect_vars` finds `{vars}` for the fill-in form.
- `mask_text(text, staff, stores, metrics)` — emails via regex → `User_01…`;
  custom terms (longest first) → staff `User_NN`, stores `Store_NN`,
  metrics `Metric_A…`. Same original always reuses its token. Returns
  `(masked, {token: original})`.
- `save/load_mapping` — `storage/mask_map.json`; `unmask_text` swaps tokens
  back longest-first (exact round-trip).
- `pack_repo(root, …)` — walks a folder, packs `.py/.tmdl/.sql/.m/.md`
  into one Markdown block; **strictly excludes** `.csv/.xlsx/.db/.parquet`
  and skips `.git/__pycache__/storage/data` etc.; per-file and total char
  caps with truncation notes. Raises `ValueError` on a bad path.

## App-specific conventions

- Mask before sending anything to a cloud LLM; the mapping never leaves
  the machine (and is gitignored).
- Metric tokens are letters (`Metric_A`) so they read naturally in code.

## Testing

`python3 tests/run_tests.py` (temp paths only) covers: all 4 frameworks +
category hints, guardrail text, var detection, template save/load/delete +
validation, email/name/store/metric masking, token formats, token reuse,
longest-term-first, exact mask→unmask round-trip, mapping persistence,
packer inclusion/exclusion/stats, bad-folder rejection. `AppTest` boot
verified for `app.py`.

## Future work

- Named masking profiles (per-project term lists).
- Token-count estimate before sending to an LLM.
- Diff view of masked vs original.
