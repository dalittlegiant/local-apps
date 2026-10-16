# Developer Guidelines — BI Requirement & Meeting Hub

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Capture, categorize, and track user requests from dashboard review
meetings; evaluate technical feasibility; auto-generate stakeholder
follow-up notes — central workspace SQLite storage, 100% offline.

## Layout

```
bi-requirement-meeting-hub/
├── app.py                  # Streamlit UI only
├── meeting_core.py         # pure logic — no st.*
├── workspace_db.py         # shared central-DB helper — DO NOT EDIT HERE
│                           # (canonical copy lives in knowledge-snippet-vault/)
├── storage/                # legacy meetings.db (import-once, then untouched;
│                           # gitignored, never committed)
├── tests/run_tests.py      # 23 checks, no Streamlit needed
└── requirements.txt
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`mt9_` prefix; no `st.set_page_config` (suite launcher owns it).

## Storage — central workspace DB

The `requirements` table lives in the central `<repo>/workspace/
workspace_master.db` (same columns as the legacy schema). `app.py` connects
via `workspace_db.open_workspace(<app dir>)`, which resolves the DB path
(linked-folder override → `<repo>/workspace/` → local fallback), inits the
schema, and one-time imports legacy `storage/meetings.db` rows (idempotent
per-app `migrated_*` flag in `app_meta`; the legacy file is only ever read).
`workspace/` is gitignored. Never edit `workspace_db.py` here — keep the
copies identical (canonical: `knowledge-snippet-vault/`).

## Schema (`requirements`)

`id`, `project`, `meeting_date` (ISO), `stakeholder`, `action_type`
(Change/Remove/Suggestion/To Confirm), `feasibility_status` (Pending Data
Check / Feasible (Confirmed) / Not Feasible (Blocked) / Completed),
`title`, `detail`, `technical_notes`, `created_at`, `updated_at`.

## Functions & methodology (`meeting_core.py`, all pure)

- `connect(path=None)` — default: central workspace DB via
  `workspace_db.open_workspace()` (see above); explicit `path`: standalone
  SQLite file with idempotent schema init (tests use a temp DB — never
  touches real storage). All CRUD functions take `con`.
- `add_requirement(...)` — validates enums + required fields, stamps
  created/updated.
- `update_requirement(rid, fields)` — allowlist of columns; stamps
  `updated_at`.
- `list_requirements(...)` — optional project/date/action/feasibility
  filters + LIKE search across title/detail/notes/stakeholder.
- `generate_minutes(rows, scope)` → `{markdown, email_subject, email,
  teams, counts}` grouped into: (a) Confirmed Changes & Removals
  (Change/Remove × Feasible/Completed), (b) Suggestions Under Feasibility
  Review, (c) Not Feasible with a polite technical explanation from
  `technical_notes`, (d) Open / To Confirm.

## App-specific conventions

- Triage board edits go through an explicit Save (diffed by `id`); deletion
  is a two-step tick + button. This in-place `st.data_editor` is the app's
  edit/resume UI (verified discoverable — no separate resume panel needed).
- Minutes scopes: one meeting date or one dashboard.

## Testing

`python3 tests/run_tests.py` (temp DBs + isolated temp workspace dir, never
touches real storage) covers: CRUD, all filters + search, enum validation,
minutes grouping/counts, polite blocked-reason phrasing, all three output
formats, empty scope, central-DB delegation, legacy `meetings.db` import
(rows + ids preserved, idempotent), update round-trip on the central DB.
`AppTest` boot verified for `app.py` (0 errors; triage board editor
renders when rows exist).

## Future work

- Attendee list + action-owner assignment per item.
- Minutes history (regenerate past meetings).
- CSV import of backlog items.
