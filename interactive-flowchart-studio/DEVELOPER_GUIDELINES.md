# Developer Guidelines — Interactive Flowchart Studio

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Build interactive business-logic flowcharts, SOPs, and decision trees to
share with end-users or embed in playbooks — 100% local. Three tabs:

1. **Node & Edge Editor** — `st.data_editor` tables (Node_ID, Label,
   Node_Type, Detailed_Description / Source_ID, Target_ID, Condition_Label),
   quick-add edge form, 2 starter templates.
2. **Live Preview** — the same viewer as the export, embedded.
3. **Export** — standalone interactive HTML, Mermaid, SVG.

## Layout

```
interactive-flowchart-studio/
├── app.py                  # Streamlit UI only
├── flow_core.py            # pure logic — no st.*
├── tests/run_tests.py      # 27 checks, no Streamlit needed
└── requirements.txt        # streamlit + pandas only (viewer is vanilla JS)
```

`app.py` inserts its own directory into `sys.path`; session keys use the
`fc8_` prefix; no `st.set_page_config` (suite launcher owns it).

## Functions & methodology (`flow_core.py`, all pure)

- Node types: `question` (diamond), `action` (rounded rect), `end`
  (stadium). Colors: indigo / emerald / red.
- `validate_flow(nodes, edges)` — empty IDs, duplicate IDs, bad types,
  unknown edge endpoints, missing start node (no incoming edges).
- `layout(nodes, edges)` — longest-path depth from roots via BFS (cycle
  guard; unreachable nodes appended last); columns per depth, vertically
  centered. Returns `{id: (x, y)}, svg_w, svg_h`. Node 190×64, gaps
  110×36.
- `render_viewer_html(title, nodes, edges)` — single self-contained file:
  SVG diagram + detail panel + vanilla JS. Click node → ancestors
  highlighted (glow filter, rest dimmed), detail panel shows type badge,
  description, and a start→node path breadcrumb; click background / Reset
  to clear. JSON payloads escape `</` as `<\/`; labels are HTML-escaped.
- `to_mermaid(nodes, edges)` — `flowchart LR` with `{"diamond"}`,
  `["rect"]`, `(["stadium"])` shapes and `-->|"label"|` edges.
- `to_svg(nodes, edges, title)` — static export for PowerPoint.

## App-specific conventions

- Edges with empty source/target are ignored (lets the data_editor keep a
  blank trailing row).
- Mermaid node IDs are sanitized to `\w+`; labels keep `|`-joined wrapped
  lines with `"` → `'`.
- The viewer has zero dependencies — it must stay that way (end-users open
  it without Python).

## Testing

`python3 tests/run_tests.py` covers: validation (6 cases), layout layering
+ longest-path depth, viewer HTML structure/escaping/`</script>` safety,
  Mermaid shapes/edge labels, SVG structure, both starter templates
  validating and rendering. `AppTest` boot verified for `app.py`. The
  exported HTML was additionally QA'd in a real Chromium (render,
  click-to-trace, detail panel, reset).

## Future work

- Drag-to-reposition nodes in the editor (needs a custom component).
- Sub-flow / swimlane grouping.
- PNG export of the diagram (needs a headless renderer — out of scope).
