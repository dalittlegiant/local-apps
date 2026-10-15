# Developer Guidelines — Stlite Sandbox Builder

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Export any standalone `app.py` tool in this repo as a single,
self-contained WebAssembly `.html` file (stlite + Pyodide via the
`@stlite/mountable` CDN) that runs in a desktop or mobile browser with no
Python install — e.g. open it in iPhone Safari.

## Layout

```
mobile-stlite-sandbox-builder/
├── app.py                  # Streamlit UI only
├── stlite_core.py          # pure logic — no st.*
├── tests/run_tests.py      # 29 checks, no Streamlit needed
└── requirements.txt        # streamlit>=1.36 only
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`sl13_` prefix; guarded `st.set_page_config` (try/except — no-op inside
the suite launcher).

## Functions & methodology (`stlite_core.py`, all pure)

- `scan_apps(repo_root)` — finds `<dir>/app.py` directly under the repo
  (sorted). Suite pages are excluded: they `from lib.… import`, which the
  flat bundle cannot satisfy.
- `read_requirements(app_path)` — bare package names from the app's
  `requirements.txt`; version pins stripped (micropip resolves Pyodide
  wheels best unpinned — a pin newer than Pyodide's built wheel, e.g.
  `pillow>=12.2.0` vs built 10.2.0, forces a PyPI lookup that fails);
  `streamlit` dropped (stlite ships its own).
- `WASM_REQ_SUBSTITUTIONS` / `apply_wasm_substitutions(names)` — packages
  with no WASM wheel are swapped for pure-Python equivalents at build
  time (`pypdfium2` → `pypdf`) or dropped (`pdfplumber`), so an export
  survives even if a desktop requirements.txt lists them.
- `bundle_files(app)` — `{virtual_name: source}` for the stlite `files`
  dict; the entry `app.py` becomes `streamlit_app.py`, sibling `*_core`
  modules keep their names so plain `import diff_core` works.
- `js_escape(s)` — escapes `\`, backticks, and `${` so Python source is
  safe inside a JS template literal.
- `build_html(title, files, requirements)` — renders the standalone page:
  pinned `@stlite/mountable@<version>` CSS+JS from jsDelivr, then
  `stlite.mount({requirements, entrypoint, files}, root)`.
- `DISCLAIMER` — shown verbatim in the UI: local-path reading cannot work
  in the browser sandbox (use each app's “Upload File” toggle on mobile);
  first load needs internet for the CDN runtime/Pyodide/packages;
  packages without Pyodide wheels (e.g. `duckdb`) may fail to install.

## App-specific conventions

- The CDN version is pinned in `STLITE_VERSION` — bump deliberately, then
  re-run the live-boot QA below.
- The generated HTML is a plain download; nothing is uploaded anywhere.

## Testing

`python3 tests/run_tests.py` covers: app scanning (count, labels, entry,
sibling modules), requirement parsing (pins stripped, streamlit dropped),
JS escaping (backslash/backtick/`${`, incl. double-backtick docstrings),
bundling (entry rename, sibling kept), template structure (pinned CDN
URLs, entrypoint, requirements, files, title escaping, mount call), and
disclaimer content. `AppTest` boot verified for `app.py`.
**Live QA** (on template changes): serve the pinned `stlite.js` locally and
open a generated HTML in real Chromium — verified 2026-10-15 that
`stlite.mount({requirements, entrypoint, files})` is accepted and the
kernel boot proceeds to wheel resolution (full UI render additionally
needs CDN access for Pyodide + wheels).

### Bundle escaping (2026-10-15)

`js_escape()` neutralizes `</script` → `<\/script` so bundled sources containing
embedded HTML/JS can never break out of the outer `<script>` block. Requirement
names go through `_safe_requirement()` (`json.dumps` + `^[A-Za-z0-9_.\-+]+$`
validation) — raw f-string interpolation into JS is forbidden (see root
DEVELOPER_GUIDE.md Security).
