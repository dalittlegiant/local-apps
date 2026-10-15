# Developer Guidelines — Interactive Flowchart Studio

> Shared repo conventions (layout, testing, encoding, git) live in
> [`../DEVELOPER_GUIDE.md`](../DEVELOPER_GUIDE.md). This file is only about
> this app's schema, functions, and methodology.

## Purpose

Build interactive business-logic flowcharts, SOPs, and decision trees to
share with end-users or embed in playbooks — 100% local. Four tabs:

1. **Node & Edge Editor** — `st.data_editor` tables (Node_ID, Label,
   Subtitle, Node_Type, Detailed_Description / Source_ID, Target_ID,
   Condition_Label), quick-add edge form, 2 starter templates.
   `Label` supports `Main Title | Subtitle` auto-split; the Subtitle
   column overrides it when set.
2. **Live Preview** — the same viewer as the export, embedded; viewer
   style & layout controls (direction, gaps, theme, panel position,
   shell size, default panel text, custom palette pickers).
3. **Export** — standalone interactive HTML, Mermaid, SVG (carries the
   preview's layout/spacing/theme/panel settings).
4. **AI HTML Studio** — paste/upload AI-generated HTML, smart SharePoint
   iframe wrapper, live preview, prompt helper, one-click download.

## Layout

```
interactive-flowchart-studio/
├── app.py                  # Streamlit UI only (4 tabs)
├── flow_core.py            # pure logic — no st.*
├── tests/run_tests.py      # 76 checks, no Streamlit needed
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

- Node types: `question` / `action` / `end` (TYPE_LABEL for display).
  `node_title_sub(node)` → `(title, subtitle)`: explicit Subtitle column
  wins, else `Title | Subtitle` auto-split on the first `|`.
- Themes (`THEMES`, `resolve_theme(theme, custom_colors)`,
  `theme_css_vars(t)`): "dark" (Dark Obsidian, default), "light" (Clean
  White), "custom" (dark base + `CUSTOM_KEY_MAP` overrides from the 9
  Streamlit color pickers). Every theme carries canvas/panel/card/border,
  node + active-node fills/borders, text/muted, edge/edge-active, and one
  accent per node type (legend dots, node dots, bento badge). Unknown
  theme names fall back to dark. Palettes are injected as CSS variables
  (`--bg-canvas`, `--node-bg`, …) on `.widget-shell`.
- `validate_flow(nodes, edges)` — empty IDs, duplicate IDs, bad types,
  unknown edge endpoints, missing start node (no incoming edges).
- `layout(nodes, edges, direction="LR", gap_x=GAP_X, gap_y=GAP_Y)` —
  longest-path depth from roots via BFS (cycle guard; unreachable nodes
  appended last); "LR" → columns by depth, "TB" → rows by depth, each
  layer centered. Returns `{id: (x, y)}, svg_w, svg_h` where the box is
  tight: `_tight_box()` → `(x0, y0, w, h)` hugging actual node coords
  (12px margin top/left/right, 25px bottom — zero extra bottom
  whitespace). The viewer's `tightViewBox()` mirrors the formula, so
  dragging + "Reset positions" restores the exact frame. Unknown
  direction strings fall back to "LR".
- `render_viewer_html(title, nodes, edges, direction="LR", gap_x=GAP_X,
  gap_y=GAP_Y, info_heading=None, info_text=None, theme="dark",
  panel="bottom", custom_colors=None, shell_w=1100, shell_h=640)` —
  single self-contained file: resizable `.widget-shell`
  (`resize: both; overflow: auto`) → diagram card + bento panel.
  Pill nodes (rx=26) with two-line text (13.5px bold title, 11.5px italic
  muted subtitle) and a type accent dot. Orthogonal stepped edges with
  rounded Q-corners: inactive = dashed `3,4`, opacity 0.45; active path =
  solid, width 2, opacity 1, accent arrowheads. Click node → ancestors
  lit, selected pill gets accented fill + 2.2 border, rest dimmed to
  0.38. Nodes draggable — stepped paths + labels + viewBox recalc live;
  "Reset positions" restores exactly. Legend bar (8px dots per type
  present) under a dashed rule at the canvas bottom. Bento panel: header
  (bold title + pill category badge), 2-col sub-card grid parsed from
  `Detailed_Description` (`Key: value` lines → cards; first two
  side-by-side, rest full-width). Panel position via `data-panel`
  (bottom/top/left/right/hidden) — Streamlit selector + toolbar mini
  toggle in the export. First root node auto-selected on load;
  `info_heading`/`info_text` (`DEFAULT_INFO_*`) shown when cleared.
  Node groups carry `data-x`/`data-y` so JS never depends on
  Python-side geometry. JSON payloads escape `</` as `<\/`; labels are
  HTML-escaped.
- `to_mermaid(nodes, edges)` — `flowchart LR` with `{"diamond"}`,
  `["rect"]`, `(["stadium"])` shapes and `-->|"label"|` edges.
- `to_svg(nodes, edges, title, direction="LR", gap_x=GAP_X, gap_y=GAP_Y,
  theme="dark")` — static export for PowerPoint; theme colors baked as
  literal attributes (self-contained).
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

`python3 tests/run_tests.py` covers: validation (6 cases), subtitle
auto-split/explicit-wins, layout layering + longest-path depth + TB
direction + custom gaps + bad-direction fallback + tight viewBox size/attr,
viewer HTML structure/escaping/`</script>` safety, pill nodes + two-line
text + type dots, stepped Q-curve edges, dashed-default (3,4) vs.
solid-lit edge styling, legend bar, bento panel + badge + position toggle
+ root auto-select, drag handlers + tightViewBox + reset-positions button
+ `data-x`/`data-y`, dark/light/custom themes (+ unknown fallback),
5 panel positions (+ bad fallback), resizable shell + shell size params,
default/custom info panel, Mermaid shapes/edge labels, SVG structure,
both starter templates validating and rendering, SharePoint wrapper
(fragment wrapped, full doc untouched, title escaped, empty safe).
`AppTest` boot + template-button click verified (no
`StreamlitWidgetAlreadyInstantiatedError`, title/tables/subtitle column
update; theme/panel selectors settable). The exported HTML was
additionally QA'd in a real Chromium (dark + light render, root
auto-select, click-to-trace with bento cards + badge, stepped-edge live
redraw on drag, viewBox recalc + exact restore, panel position toggle
incl. hidden).

## Future work

- Persist drag-repositioned node coordinates back into the node table
  (currently drag state is viewer-session only).
- Optional user-defined node categories beyond the three types (legend +
  badge currently key off node type).
- Sub-flow / swimlane grouping.
- PNG export of the diagram (needs a headless renderer — out of scope).
