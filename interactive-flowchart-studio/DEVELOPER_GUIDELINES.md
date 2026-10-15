# Developer Guidelines — Interactive Flowchart Studio

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Build interactive business-logic flowcharts, SOPs, and decision trees to
share with end-users or embed in playbooks — 100% local. Four tabs:

1. **Node & Edge Editor** — `st.data_editor` tables (Node_ID, Label,
   Node_Type, Detailed_Description / Source_ID, Target_ID, Condition_Label),
   quick-add edge form, 2 starter templates.
2. **Live Preview** — the same viewer as the export, embedded; viewer style
   & layout controls (direction, gaps, default info-panel text).
3. **Export** — standalone interactive HTML, Mermaid, SVG (carries the
   preview's layout/spacing/info-panel settings).
4. **AI HTML Studio** — paste/upload AI-generated HTML, smart SharePoint
   iframe wrapper, live preview, prompt helper, one-click download.

## Layout

```
interactive-flowchart-studio/
├── app.py                  # Streamlit UI only (4 tabs)
├── flow_core.py            # pure logic — no st.*
├── tests/run_tests.py      # 48 checks, no Streamlit needed
└── requirements.txt        # streamlit + pandas only (viewer is vanilla JS)
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`fc8_` prefix; no `st.set_page_config` (suite launcher owns it).

**Widget-state rule:** never assign a widget-bound session key
(e.g. `fc8_title`) inline after its widget has been instantiated — it
raises `StreamlitWidgetAlreadyInstantiatedError` and aborts the run
(this once made the second template button vanish). Template loading
uses `on_click` callbacks (which run before the script body); the
callback also drops the `data_editor` widget states so the editors
re-initialize from the new frames.

## Functions & methodology (`flow_core.py`, all pure)

- Node types: `question` (diamond), `action` (rounded rect), `end`
  (stadium). Colors: indigo / emerald / red.
- `validate_flow(nodes, edges)` — empty IDs, duplicate IDs, bad types,
  unknown edge endpoints, missing start node (no incoming edges).
- `layout(nodes, edges, direction="LR", gap_x=GAP_X, gap_y=GAP_Y)` —
  longest-path depth from roots via BFS (cycle guard; unreachable nodes
  appended last); "LR" → columns by depth, "TB" → rows by depth, each
  layer centered. Returns `{id: (x, y)}, svg_w, svg_h`. Node 190×64.
  Unknown direction strings fall back to "LR".
- `render_viewer_html(title, nodes, edges, direction="LR", gap_x=GAP_X,
  gap_y=GAP_Y, info_heading=None, info_text=None)` — single
  self-contained file: SVG diagram + detail panel + vanilla JS.
  Edges render dashed slate by default; clicking a node highlights its
  ancestor path with solid glowing indigo edges (indigo arrowheads) and
  dims the rest. Nodes are draggable — connected Bezier edges and their
  labels redraw live; "Reset positions" restores the layout. Click
  background / "Reset view" clears the selection and restores the
  default info panel (`DEFAULT_INFO_HEADING` / `DEFAULT_INFO_TEXT`,
  overridable). Node groups carry `data-x`/`data-y` so JS never depends
  on Python-side geometry. JSON payloads escape `</` as `<\/`; labels
  are HTML-escaped. `#path:empty` hides the breadcrumb card when empty.
- `to_mermaid(nodes, edges)` — `flowchart LR` with `{"diamond"}`,
  `["rect"]`, `(["stadium"])` shapes and `-->|"label"|` edges.
- `to_svg(nodes, edges, title, direction="LR", gap_x=GAP_X, gap_y=GAP_Y)`
  — static export for PowerPoint.
- `wrap_sharepoint_html(raw, title)` — wraps a partial HTML snippet in a
  UTF-8, responsive HTML5 shell (no horizontal scrollbars, fluid media,
  system font stack) for SharePoint iframe embedding; complete documents
  (containing `<html`) are returned unchanged.

## App-specific conventions

- Edges with empty source/target are ignored (lets the data_editor keep a
  blank trailing row).
- Mermaid node IDs are sanitized to `\w+`; labels keep `|`-joined wrapped
  lines with `"` → `'`.
- The viewer has zero dependencies — it must stay that way (end-users open
  it without Python).

## Testing

`python3 tests/run_tests.py` covers: validation (6 cases), layout layering
+ longest-path depth + TB direction + custom gaps + bad-direction
fallback, viewer HTML structure/escaping/`</script>` safety,
dashed-default vs. solid-lit edge styling, drag handlers +
reset-positions button + `data-x`/`data-y`, default/custom info panel,
Mermaid shapes/edge labels, SVG structure (+TB), both starter templates
validating and rendering, SharePoint wrapper (fragment wrapped, full doc
untouched, title escaped, empty safe). `AppTest` boot + template-button
click verified (no `StreamlitWidgetAlreadyInstantiatedError`, title and
tables update). The exported HTML was additionally QA'd in a real
Chromium (render, click-to-trace with lit path, node drag with live
edge redraw, reset positions restoring exact geometry, reset view).

## Future work

- Persist drag-repositioned node coordinates back into the node table
  (currently drag state is viewer-session only).
- Sub-flow / swimlane grouping.
- PNG export of the diagram (needs a headless renderer — out of scope).
