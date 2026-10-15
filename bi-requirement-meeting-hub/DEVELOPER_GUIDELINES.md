# Developer Guidelines — BI Requirement & Meeting Hub

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Capture, categorize, and track user requests from dashboard review
meetings; evaluate technical feasibility; auto-generate stakeholder
follow-up notes — local SQLite storage, 100% offline.

## Layout

```
bi-requirement-meeting-hub/
├── app.py                  # Streamlit UI only
├── meeting_core.py         # pure logic — no st.*
├── storage/                # meetings.db (gitignored, never committed)
├── tests/run_tests.py      # 17 checks, no Streamlit needed
└── requirements.txt
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`mt9_` prefix; no `st.set_page_config` (suite launcher owns it).

## Schema (`requirements`)

`id`, `project`, `meeting_date` (ISO), `stakeholder`, `action_type`
(Change/Remove/Suggestion/To Confirm), `feasibility_status` (Pending Data
Check / Feasible (Confirmed) / Not Feasible (Blocked) / Completed),
`title`, `detail`, `technical_notes`, `created_at`, `updated_at`.

## Functions & methodology (`meeting_core.py`, all pure)

- `db_path()` — `<app>/storage/meetings.db`, directory auto-created.
- `connect(path=None)` — row-factory dicts, idempotent schema init.
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
  is a two-step tick + button.
- Minutes scopes: one meeting date or one dashboard.

## Testing

`python3 tests/run_tests.py` (temp DB, never touches real storage) covers:
CRUD, all filters + search, enum validation, minutes grouping/counts,
polite blocked-reason phrasing, all three output formats, empty scope.
`AppTest` boot verified for `app.py`.

## Future work

- Attendee list + action-owner assignment per item.
- Minutes history (regenerate past meetings).
- CSV import of backlog items.
