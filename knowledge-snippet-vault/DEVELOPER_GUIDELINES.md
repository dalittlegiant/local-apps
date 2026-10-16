# Developer Guidelines — Knowledge & Snippet Vault

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

A local SQLite-backed personal knowledge base for reusable code snippets
and technical/statistical study notes — 100% offline.

## Layout

```
knowledge-snippet-vault/
├── app.py                  # Streamlit UI only
├── vault_core.py           # pure logic — no st.*
├── storage/                # vault.db (gitignored, never committed)
├── tests/run_tests.py      # 18 checks, no Streamlit needed
└── requirements.txt
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`kv11_` prefix; no `st.set_page_config` (suite launcher owns it).

## Schema

- `snippets`: `id`, `title`, `language` (DAX / Power Query (M) / Python /
  R / SQL), `code`, `context_notes`, `tags`, `created_at`, `updated_at`.
- `notes`: `id`, `title`, `body_md` (Markdown + LaTeX), `tags`,
  `created_at`, `updated_at`.

## Functions & methodology (`vault_core.py`, all pure)

- **Central workspace DB (2026-10-16):** `connect()` with no path now
  delegates to `workspace_db.open_workspace()` — records live in the
  single `<repo>/workspace/workspace_master.db` (`snippets`/`notes`
  tables, same columns as the old `storage/vault.db`). The one-time
  legacy import from `storage/vault.db` runs automatically and is
  idempotent (`migrated_knowledge-snippet-vault` flag); the old file
  stays on disk untouched (gitignored). Explicit `connect(path)` still
  opens an isolated DB (used by tests). `db_path()` returns the effective
  central path via `workspace_db.resolve_db_path()`. `workspace_db.py`
  is the canonical copy — identical copies live in
  `bi-requirement-meeting-hub/`, `ai-prompt-privacy-hub/`,
  `unified-data-studio/`; edit here first.
- CRUD for both tables with required-field and language validation.
- `search(query, language, tags)` — LIKE full-text over title/code/notes
  (or title/body for notes), optional language + multi-tag post-filter.
- `all_tags()` — union of tags across both tables for filter dropdowns.
- `export_cheatsheet(snippets, notes)` — one Markdown doc with fenced
  code blocks per language and full note bodies (LaTeX untouched).

## App-specific conventions

- Tags are comma-separated, normalized on write.
- LaTeX renders via Streamlit's built-in KaTeX (`$…$` / `$$…$$`).
- Code display uses `st.code` with a per-language fence map; copy from the
  block.
- **Resume panel (2026-10-16):** each tab opens with a prominent
  "📂 Resume / edit" panel — a selectbox listing existing records by
  title loads the record into an edit form (widget keys suffixed with
  the record id so switching records resets state); 💾 Save calls the
  existing `update_snippet`/`update_note`. The per-expander ✏️ Edit
  buttons remain as a secondary path.

## Testing

`python3 tests/run_tests.py` (temp DB) covers: snippet/note CRUD,
validation, language/text/tag search, tag union, LaTeX preservation,
cheat-sheet structure and fences. `AppTest` boot verified for `app.py`.

## Future work

- Import/export the whole vault as JSON.
- Pin/favorite items.
- Spaced-repetition prompts for study notes.
