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
2. **Live Preview** — the same viewer as the export, embedded; a
   collapsible **⚙️ Settings** panel (viewer style & layout controls:
   direction, gaps, theme, panel position, shell size, default panel
   text, custom palette pickers, font sizes, legend/drag toggles, hint
   text); drag nodes on the canvas, then **📌 Capture canvas positions**
   to persist the dragged layout for export (✖ Clear positions reverts
   to auto-layout).
3. **Export** — standalone interactive HTML, Mermaid, SVG (carries the
   preview's layout/spacing/theme/panel settings; captured drag
   positions are baked in so the file opens on the author's layout).
4. **AI HTML Studio** — paste/upload AI-generated HTML, smart SharePoint
   iframe wrapper, live preview, prompt helper, one-click download.

## Layout

```
interactive-flowchart-studio/
├── app.py                  # Streamlit UI only (4 tabs)
├── flow_core.py            # pure logic — no st.*
├── tests/run_tests.py      # 134 checks, no Streamlit needed
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
  layer centered. Optional `positions={id: (x, y)}` overrides auto-layout
  per node (captured drag coordinates); unknown ids and malformed values
  are ignored. Returns `{id: (x, y)}, svg_w, svg_h` where the box is
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
solid-lit edge styling, legend bar (+ on/off toggle), bento panel + badge
+ position toggle + root auto-select + empty-card filter, drag handlers +
tightViewBox + reset-positions button + `data-x`/`data-y`, dark/light/custom
themes (+ unknown fallback), 5 panel positions (+ bad fallback), resizable
shell + shell size params, default/custom info panel, auto-fit node boxes
(min width, widen, wrap+grow, CJK 1.8x, blank-id skip, wide-layer spacing),
font-size attributes (title/edge/panel), edge-label halo rect, marker CSS
sync (`var(--edge-color)`/`var(--edge-active)`), export toolbar removal,
drag-lock baking, hint empty/set, JS SIZES payload, static SVG font sizes,
Mermaid shapes/edge labels, SVG structure, both starter templates validating
and rendering, SharePoint wrapper (fragment wrapped, full doc untouched,
title escaped, empty safe), drag-position persistence (layout override,
export embeds custom `data-x`/`data-y`, parse validation/clamping, sync JS
present, audit still clean, SVG honors positions). `AppTest` boot + template-button click verified
(no `StreamlitWidgetAlreadyInstantiatedError`, title/tables/subtitle column
update; theme/panel selectors settable; font sliders, drag/legend
checkboxes, hint input present). The exported HTML was additionally QA'd in
a real Chromium (dark + light render, root auto-select, click-to-trace with
bento cards + badge, stepped-edge live redraw on drag, viewBox recalc +
exact restore, panel position toggle incl. hidden, read-only export with no
toolbar/hint and locked dragging vs. draggable authoring preview).
### Author vs. end-user separation (read-only export)

The Streamlit preview is the **authoring** view: draggable nodes, Reset
view / Reset positions toolbar, panel switcher, hint line. The downloaded
`.html` is the **read-only end-user deliverable**: `show_toolbar=False`
removes the whole toolbar (theme, colors, panel position are baked in from
the Streamlit settings), `hint_text=""` renders nothing above the canvas
by default, and `allow_drag=False` (default) skips the mousedown binding
and switches nodes to `cursor:pointer` — clicks still trace paths and
update the bento panel, but the layout can't be disturbed. Set "Allow node
dragging in exported HTML" only when end-users should rearrange.

### Auto-fit node sizing

`node_box()`/`node_boxes()` estimate text width (ASCII 0.55×font-size,
CJK 1.8× that, +48px padding), clamp width to 180–380px, word-wrap
overlong text (CJK-safe hard split) and grow height (base 64px + line
height per extra line). `layout(..., sizes=...)` offsets layers by each
layer's max node width so same-rank neighbours never overlap. Font sizes
are literal SVG attributes (static export stays self-contained); the
viewer CSS carries no font-size rules for node/edge text.

### Export security (AI Studio + flowchart exporter)

`audit_html_security()` scans export HTML for external scripts/
stylesheets (`src`/`href`/`@import` with http(s):// or `//` URLs),
outbound network calls (`fetch(`, `XMLHttpRequest`,
`navigator.sendBeacon`, `WebSocket`) and unsafe sinks (`eval(`,
`new Function(`), returning `{"passed", "findings"}` with exact line
numbers + URLs/snippets. The app renders a green
"✅ Security Check Passed: 100% Self-Contained (Zero External Network
Calls)" card, or a red card listing every finding for review/stripping.
`sanitize_export()` applies the reverse-tabnabbing fix (all
`<a target="_blank">` get `rel="noopener noreferrer"`, merged into any
existing rel) and optionally injects `DEFAULT_CSP` — the
zero-exfiltration policy (`connect-src 'none'`, `script-src
'unsafe-inline'` only) — as a `<meta>` in `<head>` (existing CSP metas
are replaced, never duplicated). Both the `.html` and `.aspx` downloads
are byte-identical and receive the same sanitization + CSP. The
interactive viewer was QA'd in Chromium with the CSP injected:
click-to-trace, bento cards and selection all work; `fetch()` is blocked
(`connect-src 'none'`) as intended.

### Drag-position persistence (2026-10-16)

Drag state used to be viewer-session only — any rerun rebuilt the
iframe from auto-layout and exports always reset to it. Now the viewer
JS publishes live coordinates after every drag (`syncPosToParent()`,
best-effort: `window.parent.history.replaceState` with the `fc8_pos`
query param, silently skipped in sandboxed/cross-origin iframes) and
`app.py` offers **📌 Capture canvas positions**, which reads
`st.query_params["fc8_pos"]`, validates it with
`core.parse_positions_param()` (never raises; drops unknown ids,
non-numeric/NaN/out-of-range values, clamps to ±10000px), keeps only ids
still in the flow, and stores `{id: (x, y)}` in `fc8_positions` session
state. `render_viewer_html(..., positions=...)` / `to_svg(...,
positions=...)` pass it to `layout()`, so the preview survives reruns
and the exported `.html`/`.aspx`/`.svg` open exactly on the dragged
layout — the custom coordinates are baked into the SVG `data-x`/`data-y`
attributes, which is also what the viewer's "Reset positions" restores
(auto-layout never runs for those nodes). Loading a starter template
clears captured positions. The sync JS adds no network calls and stays
inside the zero-exfiltration CSP + `audit_html_security` contract
(verified by test: the audit still passes on viewer output containing
the sync code).

## Future work

- Optional user-defined node categories beyond the three types (legend +
  badge currently key off node type).
- Sub-flow / swimlane grouping.
- PNG export of the diagram (needs a headless renderer — out of scope).

### Export security hardening (2026-10-15)

`audit_html_security()` also flags external `<img>`/`<iframe>`/`<video>`/`<audio>`/
`<source>`/`<embed>` `src` URLs (`external-media` kind) — local `./`, `/`, and
`data:` media pass. The injected `DEFAULT_CSP` was tightened to
`img-src 'self' data: blob:` (no `https:`) so tracking pixels are blocked at runtime
while local/same-origin SharePoint images keep working.
