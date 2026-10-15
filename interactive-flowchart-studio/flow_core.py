"""Core logic for the Interactive Flowchart Studio. Pure — no ``st.*`` calls.

Covers: flow validation, layered auto-layout (LR/TB, tight bounding box),
the standalone interactive HTML viewer (pill nodes, orthogonal stepped
edges, bento info panel, Dark/Light/Custom themes, 5-way panel position,
resizable SharePoint-friendly shell — HTML/CSS/vanilla JS, zero
dependencies), Mermaid export, and static SVG export.
"""

import html
import json
import re

NODE_W, NODE_H = 190, 64
GAP_X, GAP_Y = 110, 36
PAD = 48

NODE_TYPES = ("question", "action", "end")
TYPE_LABEL = {"question": "Question / Decision", "action": "Action / Step",
              "end": "End-State"}

# ------------------------------------------------------------ themes
# Every theme carries the full Minimalist Pill-Node & Bento-Panel palette:
# canvas/panel/card surfaces, borders, node fills, text, edges, plus one
# accent color per node type (legend dots, type dots, category badge).
THEMES = {
    "dark": {
        "label": "Dark Obsidian",
        "bg_canvas": "#0e1015", "bg_panel": "#0e1015", "bg_card": "#161920",
        "border": "#262a34",
        "node_bg": "#15181f", "node_border": "#383e4c",
        "node_active_bg": "#1c2846", "node_active_border": "#5c8df6",
        "text": "#f3f4f6", "text_muted": "#9ca3af",
        "edge": "#6b7280", "edge_active": "#93c5fd",
        "accents": {"question": "#5c8df6", "action": "#34d399",
                    "end": "#f87171"},
    },
    "light": {
        "label": "Clean White",
        "bg_canvas": "#ffffff", "bg_panel": "#ffffff", "bg_card": "#f8fafc",
        "border": "#e2e8f0",
        "node_bg": "#f8fafc", "node_border": "#cbd5e1",
        "node_active_bg": "#eff6ff", "node_active_border": "#2563eb",
        "text": "#0f172a", "text_muted": "#64748b",
        "edge": "#94a3b8", "edge_active": "#2563eb",
        "accents": {"question": "#2563eb", "action": "#059669",
                    "end": "#dc2626"},
    },
}
THEMES["custom"] = dict(THEMES["dark"], label="Custom",
                        accents=dict(THEMES["dark"]["accents"]))

# st.color_picker keys (app.py) -> theme dict keys
CUSTOM_KEY_MAP = {"canvas_bg": "bg_canvas", "panel_bg": "bg_panel",
                  "node_bg": "node_bg", "node_border": "node_border",
                  "active_node_bg": "node_active_bg",
                  "active_node_border": "node_active_border",
                  "primary_text": "text", "subtitle_text": "text_muted",
                  "edge_color": "edge"}


def resolve_theme(theme: str = "dark",
                  custom_colors: dict | None = None) -> dict:
    """Return the concrete palette dict for a theme name.

    ``theme``: "dark" | "light" | "custom" (unknown -> "dark").
    ``custom_colors`` maps the CUSTOM_KEY_MAP keys to hex colors and is
    applied on top of the dark base when theme == "custom".
    """
    key = str(theme or "dark").lower()
    if key not in THEMES:
        key = "dark"
    t = dict(THEMES[key])
    t["accents"] = dict(THEMES[key]["accents"])
    if key == "custom" and custom_colors:
        for k, v in custom_colors.items():
            if k in CUSTOM_KEY_MAP and isinstance(v, str) and v.strip():
                t[CUSTOM_KEY_MAP[k]] = v.strip()
    return t


def theme_css_vars(t: dict) -> str:
    """Inline-style CSS variable block for .widget-shell."""
    return ("--bg-canvas:{bg_canvas};--bg-panel:{bg_panel};"
            "--bg-card:{bg_card};--border-box:{border};"
            "--node-bg:{node_bg};--node-border:{node_border};"
            "--node-active-bg:{node_active_bg};"
            "--node-active-border:{node_active_border};"
            "--text:{text};--text-muted:{text_muted};"
            "--edge:{edge};--edge-color:{edge};"
            "--edge-active:{edge_active};").format(**t)


def node_title_sub(node: dict) -> tuple[str, str]:
    """(title, subtitle) for a node.

    An explicit ``subtitle`` field wins; otherwise a ``Title | Subtitle``
    label is auto-split on the first ``|``.
    """
    label = str(node.get("label", "") or "")
    sub = str(node.get("subtitle", "") or "").strip()
    if not sub and "|" in label:
        title, _, rest = label.partition("|")
        return (title.strip() or label.strip(), rest.strip())
    return label.strip(), sub


def type_accent(ntype: str, t: dict) -> str:
    return t["accents"].get(str(ntype).strip() or "action",
                            t["accents"]["action"])


# ------------------------------------------------------------ text measure
def _is_wide(ch: str) -> bool:
    """CJK / wide characters count 1.8x an ASCII character."""
    return ("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf"
            or "\uf900" <= ch <= "\ufaff" or "\u3040" <= ch <= "\u30ff"
            or "\uac00" <= ch <= "\ud7af" or "\u3000" <= ch <= "\u303f"
            or "\uff00" <= ch <= "\uffef")


def _text_px(text: str, font_size: float) -> float:
    """Estimated visual pixel width of a string at a font size."""
    unit = 0.55 * font_size  # avg ASCII advance in Segoe UI
    return sum(1.8 * unit if _is_wide(ch) else unit for ch in text)


def _fit_lines(text: str, font_size: float, max_w: float) -> list[str]:
    """Word-wrap (CJK-safe: hard-splits overlong words) into lines that fit
    the node text budget (max_w minus 48px horizontal padding)."""
    budget = max_w - 48
    words, lines, cur = str(text or "").split(), [], ""
    for wd in words:
        trial = (cur + " " + wd).strip()
        if _text_px(trial, font_size) <= budget or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    out: list[str] = []
    for ln in lines:
        while _text_px(ln, font_size) > budget and len(ln) > 1:
            k = len(ln)
            while k > 1 and _text_px(ln[:k], font_size) > budget:
                k -= 1
            out.append(ln[:k])
            ln = ln[k:]
        out.append(ln)
    return out or [""]


def node_box(node: dict, title_fs: float = 13.5, subtitle_fs: float = 11.5,
             min_w: float = 180, max_w: float = 380) -> dict:
    """Auto-fit pill box for a node: width expands (min_w..max_w) to enclose
    the text; overlong text wraps to multiple lines and the height grows
    proportionally. Returns {"w","h","tl","sl"} (title/subtitle lines)."""
    title, subtitle = node_title_sub(node)
    tl = _fit_lines(title, title_fs, max_w)
    sl = _fit_lines(subtitle, subtitle_fs, max_w) if subtitle else []
    widest = max([_text_px(l, title_fs) for l in tl]
                 + [_text_px(l, subtitle_fs) for l in sl] + [0])
    w = min(max(widest + 48, min_w), max_w)
    lh_t, lh_s = title_fs * 1.35, subtitle_fs * 1.35
    block = len(tl) * lh_t + len(sl) * lh_s
    h = max(64, block + 28)
    return {"w": int(round(w)), "h": int(round(h)), "tl": tl, "sl": sl}


def node_boxes(nodes: list[dict], title_fs: float = 13.5,
               subtitle_fs: float = 11.5, min_w: float = 180,
               max_w: float = 380) -> dict[str, dict]:
    """{node_id: node_box(...)} for every node with a non-blank id."""
    out = {}
    for n in nodes:
        nid = str(n.get("id", "")).strip()
        if nid:
            out[nid] = node_box(n, title_fs, subtitle_fs, min_w, max_w)
    return out


def _box_wh(nid: str, sizes: dict | None) -> tuple[float, float]:
    """(width, height) for a node id; falls back to NODE_W/NODE_H."""
    if sizes and nid in sizes:
        s = sizes[nid]
        if isinstance(s, dict):
            return s.get("w", NODE_W), s.get("h", NODE_H)
        return s[0], s[1]
    return NODE_W, NODE_H


# ------------------------------------------------------------ templates
def starter_templates() -> dict:
    return {
        "report_access": {
            "name": "Report Access Request Flow",
            "nodes": [
                {"id": "start", "label": "User requests report access",
                 "type": "action",
                 "desc": "Stakeholder submits an access request via the intake form or email."},
                {"id": "q_manager", "label": "Manager approved?",
                 "type": "question",
                 "desc": "The requester's direct manager must approve data access for their team."},
                {"id": "q_sensitive", "label": "Contains sensitive data?",
                 "type": "question",
                 "desc": "Check whether the report exposes PII, salaries, or commercially sensitive metrics."},
                {"id": "a_grant", "label": "Grant viewer access",
                 "type": "action",
                 "desc": "Add the user to the report's viewer group in the workspace."},
                {"id": "a_governance", "label": "Route to governance review",
                 "type": "action",
                 "desc": "Sensitive reports need a second approval from the governance team before granting."},
                {"id": "end_done", "label": "Access granted",
                 "type": "end",
                 "desc": "User notified; access logged in the audit register."},
                {"id": "end_rejected", "label": "Request rejected",
                 "type": "end",
                 "desc": "Notify the requester with the reason; no access granted."},
            ],
            "edges": [
                {"source": "start", "target": "q_manager", "label": ""},
                {"source": "q_manager", "target": "q_sensitive", "label": "Yes"},
                {"source": "q_manager", "target": "end_rejected", "label": "No"},
                {"source": "q_sensitive", "target": "a_governance", "label": "Yes"},
                {"source": "q_sensitive", "target": "a_grant", "label": "No"},
                {"source": "a_grant", "target": "end_done", "label": ""},
                {"source": "a_governance", "target": "end_done", "label": "Approved"},
                {"source": "a_governance", "target": "end_rejected", "label": "Denied"},
            ],
        },
        "kpi_troubleshooting": {
            "name": "KPI Troubleshooting Decision Tree",
            "nodes": [
                {"id": "start", "label": "KPI looks wrong",
                 "type": "action",
                 "desc": "A stakeholder reports a KPI value that looks incorrect on the dashboard."},
                {"id": "q_refresh", "label": "Data refreshed today?",
                 "type": "question",
                 "desc": "Check the dataset refresh history — stale data is the most common cause."},
                {"id": "a_wait", "label": "Wait for refresh / trigger manual refresh",
                 "type": "action",
                 "desc": "Trigger a manual refresh and re-check the KPI after it completes."},
                {"id": "q_filter", "label": "Filters / slicers as expected?",
                 "type": "question",
                 "desc": "Check for stuck slicers, cross-filtering, or a bookmark applying hidden filters."},
                {"id": "a_fixfilter", "label": "Reset filters and re-check",
                 "type": "action",
                 "desc": "Clear all slicers, reset the page, and compare against the source system."},
                {"id": "q_dax", "label": "DAX logic changed recently?",
                 "type": "question",
                 "desc": "Review measure definitions and recent model changes for logic drift."},
                {"id": "a_fixdax", "label": "Fix measure and redeploy",
                 "type": "action",
                 "desc": "Correct the DAX, validate against source data, redeploy the dataset."},
                {"id": "a_escalate", "label": "Escalate to data engineering",
                 "type": "action",
                 "desc": "If source data itself is wrong, raise a ticket with the pipeline owners."},
                {"id": "end_ok", "label": "KPI verified correct",
                 "type": "end",
                 "desc": "KPI reconciles with the source. Document the finding and close the loop with the stakeholder."},
            ],
            "edges": [
                {"source": "start", "target": "q_refresh", "label": ""},
                {"source": "q_refresh", "target": "a_wait", "label": "No"},
                {"source": "q_refresh", "target": "q_filter", "label": "Yes"},
                {"source": "a_wait", "target": "end_ok", "label": "Fixed"},
                {"source": "q_filter", "target": "a_fixfilter", "label": "No"},
                {"source": "q_filter", "target": "q_dax", "label": "Yes"},
                {"source": "a_fixfilter", "target": "end_ok", "label": "Fixed"},
                {"source": "q_dax", "target": "a_fixdax", "label": "Yes"},
                {"source": "q_dax", "target": "a_escalate", "label": "No"},
                {"source": "a_fixdax", "target": "end_ok", "label": ""},
            ],
        },
    }


# ------------------------------------------------------------ validation
def validate_flow(nodes: list[dict], edges: list[dict]) -> list[str]:
    errors: list[str] = []
    ids = [str(n.get("id", "")).strip() for n in nodes]
    if any(not i for i in ids):
        errors.append("Every node needs a Node_ID.")
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        errors.append("Duplicate Node_IDs: " + ", ".join(sorted(dupes)))
    bad_type = [i for n, i in zip(nodes, ids)
                if str(n.get("type", "")).strip() not in NODE_TYPES]
    if bad_type:
        errors.append("Invalid Node_Type on: " + ", ".join(bad_type)
                      + f" (use {', '.join(NODE_TYPES)}).")
    idset = set(ids)
    for e in edges:
        for side in ("source", "target"):
            v = str(e.get(side, "")).strip()
            if v and v not in idset:
                errors.append(f"Edge references unknown node '{v}'.")
    if nodes and not any(not _incoming(str(n.get("id", "")), edges)
                         for n in nodes):
        errors.append("No start node found (a node with no incoming edges).")
    return errors


def _incoming(nid: str, edges: list[dict]) -> list[dict]:
    return [e for e in edges if str(e.get("target", "")).strip() == nid]


# ------------------------------------------------------------ layout
def layout(nodes: list[dict], edges: list[dict], direction: str = "LR",
           gap_x: int = GAP_X, gap_y: int = GAP_Y,
           sizes: dict | None = None
           ) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Layered layout. ``direction``: "LR" (depth -> columns, left to right)
    or "TB" (depth -> rows, top to bottom). ``gap_x``/``gap_y`` are the
    horizontal/vertical spacing between node blocks. ``sizes`` optionally
    maps node id -> (w, h) (see ``node_boxes()``); wider nodes push the
    following layers out so same-rank neighbours never overlap. With
    ``sizes=None`` every node is NODE_W x NODE_H. Returns
    ({id: (x, y)}, svg_w, svg_h) with a tight bounding box (see
    ``_tight_box``)."""
    direction = "TB" if str(direction).upper() == "TB" else "LR"
    gap_x, gap_y = int(gap_x), int(gap_y)
    ids = [str(n.get("id", "")).strip() for n in nodes]
    # longest-path depth from roots (BFS with cycle guard)
    depth: dict[str, int] = {}
    roots = [i for i in ids if not _incoming(i, edges)]
    queue = [(r, 0) for r in roots]
    seen: set[tuple[str, int]] = set()
    while queue:
        nid, d = queue.pop(0)
        if (nid, d) in seen:
            continue
        seen.add((nid, d))
        depth[nid] = max(depth.get(nid, 0), d)
        for e in edges:
            if str(e.get("source", "")).strip() == nid:
                t = str(e.get("target", "")).strip()
                if t in ids:
                    queue.append((t, d + 1))
    max_d = max(depth.values(), default=0)
    for i in ids:  # unreachable / cyclic leftovers go last
        depth.setdefault(i, max_d + 1)
    layers: dict[int, list[str]] = {}
    for i in ids:
        layers.setdefault(depth[i], []).append(i)
    pos: dict[str, tuple[int, int]] = {}
    if direction == "TB":
        row_h = {d: max(_box_wh(n, sizes)[1] for n in row)
                 for d, row in layers.items()}
        ys, acc = {}, PAD
        for d in sorted(layers):
            ys[d] = acc
            acc += row_h[d] + gap_y
        rows_w = {d: sum(_box_wh(n, sizes)[0] for n in row)
                  + (len(row) - 1) * gap_x for d, row in layers.items()}
        total_w = max(rows_w.values(), default=NODE_W)
        for d, row in layers.items():
            x = PAD + (total_w - rows_w[d]) // 2
            for nid in row:
                pos[nid] = (x, ys[d])
                x += _box_wh(nid, sizes)[0] + gap_x
    else:
        layer_w = {d: max(_box_wh(n, sizes)[0] for n in col)
                   for d, col in layers.items()}
        xs, acc = {}, PAD
        for d in sorted(layers):
            xs[d] = acc
            acc += layer_w[d] + gap_x
        col_h = {d: sum(_box_wh(n, sizes)[1] for n in col)
                 + (len(col) - 1) * gap_y for d, col in layers.items()}
        total_h = max(col_h.values(), default=NODE_H)
        for d, col in layers.items():
            y = PAD + (total_h - col_h[d]) // 2
            for nid in col:
                pos[nid] = (xs[d], y)
                y += _box_wh(nid, sizes)[1] + gap_y
    return pos, *_tight_box(pos, sizes)[2:]


def _tight_box(pos: dict[str, tuple[int, int]],
               sizes: dict | None = None) -> tuple[float, float, float, float]:
    """Tight SVG bounding box from actual node coordinates: (x0, y0, w, h).

    The frame hugs the diagram with a 12px margin on the top/left/right and
    25px at the bottom — zero extra bottom whitespace. The same formula is
    mirrored in the viewer's ``tightViewBox()`` so dragging nodes and
    pressing "Reset positions" restores the exact same frame.
    """
    if not pos:
        return 0, 0, 2 * PAD + NODE_W, 2 * PAD + NODE_H
    l = min(x for x, _ in pos.values())
    t = min(y for _, y in pos.values())
    r = max(x + _box_wh(nid, sizes)[0] for nid, (x, _) in pos.items())
    b = max(y + _box_wh(nid, sizes)[1] for nid, (_, y) in pos.items())
    return l - 12, t - 12, r - l + 24, b - t + 37


def _wrap(text: str, width: int = 20) -> list[str]:
    words, lines, cur = str(text or "").split(), [], ""
    for w in words:
        if len((cur + " " + w).strip()) > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines[:4] or [""]


def _node_by_id(nodes: list[dict]) -> dict[str, dict]:
    return {str(n.get("id", "")).strip(): n for n in nodes}


# ------------------------------------------------------------ svg pieces
def _svg_node(nid: str, node: dict, x: int, y: int, t: dict,
              box: dict | None = None, title_fs: float = 13.5,
              subtitle_fs: float = 11.5) -> str:
    """Pill-shaped node (rx=26) with two-line text: bold primary title +
    italic muted subtitle, plus a type accent dot.

    ``box`` (from ``node_box()``) carries the auto-fit width/height and
    pre-wrapped lines; without it the node is NODE_W x NODE_H. Font sizes
    are baked as literal attributes so the static SVG export stays
    self-contained. Base colors are literal too; the interactive viewer
    overrides the active state via CSS variables.
    """
    ntype = str(node.get("type", "action")).strip() or "action"
    accent = type_accent(ntype, t)
    if box is None:
        title, subtitle = node_title_sub(node)
        tl, sl = _wrap(title or nid), [subtitle] if subtitle else []
        w, h = NODE_W, NODE_H
    else:
        w, h, tl, sl = box["w"], box["h"], box["tl"], box["sl"]
    cx, cy = x + w / 2, y + h / 2
    lh_t, lh_s = title_fs * 1.35, subtitle_fs * 1.35
    y0 = cy - (len(tl) * lh_t + len(sl) * lh_s) / 2
    texts = "".join(
        f'<text class="node-title" x="{cx:.1f}" '
        f'y="{y0 + lh_t * 0.82 + i * lh_t:.1f}" '
        f'text-anchor="middle" font-size="{title_fs}" fill="{t["text"]}">'
        f'{html.escape(ln)}</text>'
        for i, ln in enumerate(tl))
    texts += "".join(
        f'<text class="node-sub" x="{cx:.1f}" '
        f'y="{y0 + len(tl) * lh_t + lh_s * 0.82 + j * lh_s:.1f}" '
        f'text-anchor="middle" font-size="{subtitle_fs}" '
        f'fill="{t["text_muted"]}">{html.escape(ln)}</text>'
        for j, ln in enumerate(sl))
    tip = html.escape(str(node.get("desc", ""))[:200])
    return (
        f'<g class="node" data-nid="{html.escape(nid)}" '
        f'data-x="{x}" data-y="{y}">'
        f"<title>{tip}</title>"
        f'<rect class="pill" x="{x}" y="{y}" width="{w}" '
        f'height="{h}" rx="26" ry="26" fill="{t["node_bg"]}" '
        f'stroke="{t["node_border"]}" stroke-width="1.6" '
        f'filter="url(#nodeShadow)"/>'
        f'<circle class="node-dot" cx="{x + 18}" cy="{cy:.1f}" r="5" '
        f'fill="{accent}"/>{texts}</g>')


def _label_halo(lx: float, ly: float, label: str, edge_fs: float,
                t: dict) -> str:
    """Rounded rect behind an edge label so connector lines never cut
    through characters. Literal fill (self-contained static export) with
    a var(--bg-canvas) CSS override in the viewer."""
    w = _text_px(label, edge_fs) + 14
    h = edge_fs * 1.6
    return (f'<rect class="edge-halo" x="{lx - w / 2:.1f}" '
            f'y="{ly - h / 2 - edge_fs * 0.15:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="4" fill="{t["bg_canvas"]}"/>')


def _stepped_path(x1: float, y1: float, x2: float, y2: float,
                  horizontal: bool = True, r: float = 12) -> str:
    """Orthogonal stepped connector with rounded corners (Q curves at each
    90-degree turn). ``horizontal``: primary axis x (LR); else y (TB)."""
    dx, dy = x2 - x1, y2 - y1
    if horizontal:
        if abs(dy) < 1.5:
            return f"M{x1},{y1} L{x2},{y2}"
        rr = min(r, abs(dx) / 2 - 1, abs(dy) / 2 - 1)
        mx = x1 + dx / 2
        if rr < 2:
            return f"M{x1},{y1} L{mx},{y1} L{mx},{y2} L{x2},{y2}"
        sy = 1 if dy > 0 else -1
        return (f"M{x1},{y1} L{mx - rr},{y1} "
                f"Q{mx},{y1} {mx},{y1 + sy * rr} "
                f"L{mx},{y2 - sy * rr} "
                f"Q{mx},{y2} {mx + rr},{y2} L{x2},{y2}")
    if abs(dx) < 1.5:
        return f"M{x1},{y1} L{x2},{y2}"
    rr = min(r, abs(dx) / 2 - 1, abs(dy) / 2 - 1)
    my = y1 + dy / 2
    if rr < 2:
        return f"M{x1},{y1} L{x1},{my} L{x2},{my} L{x2},{y2}"
    sx = 1 if dx > 0 else -1
    return (f"M{x1},{y1} L{x1},{my - rr} "
            f"Q{x1},{my} {x1 + sx * rr},{my} "
            f"L{x2 - sx * rr},{my} "
            f"Q{x2},{my} {x2},{my + rr} L{x2},{y2}")


def _svg_edge(edge: dict, pos: dict[str, tuple[int, int]], t: dict,
              direction: str = "LR", sizes: dict | None = None,
              edge_fs: float = 11.0) -> str:
    s, t_ = str(edge.get("source", "")).strip(), str(edge.get("target", "")).strip()
    if s not in pos or t_ not in pos:
        return ""
    sw_, sh_ = _box_wh(s, sizes)
    tw_, th_ = _box_wh(t_, sizes)
    if direction == "TB":
        x1, y1 = pos[s][0] + sw_ / 2, pos[s][1] + sh_
        x2, y2 = pos[t_][0] + tw_ / 2, pos[t_][1]
        d = _stepped_path(x1, y1, x2, y2, horizontal=False)
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 8
    else:
        x1, y1 = pos[s][0] + sw_, pos[s][1] + sh_ / 2
        x2, y2 = pos[t_][0], pos[t_][1] + th_ / 2
        d = _stepped_path(x1, y1, x2, y2, horizontal=True)
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 8
    raw_label = str(edge.get("label", "") or "")
    label = html.escape(raw_label)
    halo = _label_halo(lx, ly, raw_label, edge_fs, t) if label else ""
    lab = (f'<text class="edge-label" x="{lx:.1f}" y="{ly:.1f}" '
           f'text-anchor="middle" font-size="{edge_fs}" '
           f'fill="{t["text_muted"]}">{label}</text>' if label else "")
    return (f'<g class="edge" data-source="{html.escape(s)}" '
            f'data-target="{html.escape(t_)}">'
            f'<path d="{d}" fill="none" stroke="{t["edge"]}" '
            f'stroke-width="1.6" stroke-dasharray="3 4" opacity="0.45" '
            f'marker-end="url(#arrIn)"/>{halo}{lab}</g>')


def _svg_defs(t: dict) -> str:
    return ('<defs>'
            '<marker id="arrIn" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{t["edge"]}"/></marker>'
            '<marker id="arrAct" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{t["edge_active"]}"/></marker>'
            '<filter id="nodeShadow" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="3" stdDeviation="5" '
            'flood-color="#0F172A" flood-opacity="0.10"/></filter>'
            '</defs>')


def _svg_inner(nodes: list[dict], edges: list[dict],
               pos: dict[str, tuple[int, int]], t: dict,
               direction: str = "LR", sizes: dict | None = None,
               boxes: dict | None = None, title_fs: float = 13.5,
               subtitle_fs: float = 11.5, edge_fs: float = 11.0) -> str:
    by_id = _node_by_id(nodes)
    parts = [_svg_defs(t)]
    parts += [_svg_edge(e, pos, t, direction, sizes, edge_fs) for e in edges]
    for nid, (x, y) in pos.items():
        parts.append(_svg_node(nid, by_id.get(nid, {}), x, y, t,
                               boxes.get(nid) if boxes else None,
                               title_fs, subtitle_fs))
    return "".join(parts)


def _svg_body(nodes: list[dict], edges: list[dict],
              pos: dict[str, tuple[int, int]], svg_w: int, svg_h: int, t: dict,
              for_export: bool = False, direction: str = "LR",
              sizes: dict | None = None, boxes: dict | None = None,
              title_fs: float = 13.5, subtitle_fs: float = 11.5,
              edge_fs: float = 11.0) -> str:
    cls = ' class="diagram"' if not for_export else ""
    x0, y0, _, _ = _tight_box(pos, sizes)
    return (f'<svg{cls} width="{svg_w}" height="{svg_h}" '
            f'viewBox="{x0} {y0} {svg_w} {svg_h}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f"{_svg_inner(nodes, edges, pos, t, direction, sizes, boxes, title_fs, subtitle_fs, edge_fs)}</svg>")


def _legend_bar(nodes: list[dict], t: dict) -> str:
    """Bottom legend bar: an 8px colored dot + label per node type present,
    separated from the canvas by a dashed rule."""
    present = []
    for ntype in NODE_TYPES:
        if any(str(n.get("type", "action")).strip() == ntype for n in nodes):
            present.append(ntype)
    items = "".join(
        f'<span class="legend-item"><span class="legend-dot" '
        f'style="background:{type_accent(nt, t)}"></span>'
        f'{html.escape(TYPE_LABEL[nt])}</span>'
        for nt in present)
    return f'<div class="legend-bar">{items}</div>' if items else ""


# ------------------------------------------------------------ html viewer
# ------------------------------------------------------------ html viewer
_VIEWER_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',-apple-system,'Helvetica Neue',Arial,sans-serif;background:__BBG__;color:__BTX__}
html,body{margin:0;padding:0;overflow-x:hidden}
.widget-shell{resize:both;overflow:auto;border-radius:16px;min-width:340px;min-height:340px;
 background:var(--bg-canvas);color:var(--text);padding:14px}
.layout{display:flex;gap:14px;align-items:stretch;min-height:100%}
.layout[data-panel="bottom"],.layout[data-panel="top"]{flex-direction:column}
.layout[data-panel="left"],.layout[data-panel="right"]{flex-direction:row}
.layout[data-panel="top"] .panel-card{order:-1}
.layout[data-panel="left"] .panel-card{order:-1}
.layout[data-panel="left"] .panel-card,.layout[data-panel="right"] .panel-card{flex:none;width:340px}
.layout[data-panel="bottom"] .panel-card,.layout[data-panel="top"] .panel-card{width:100%}
.layout[data-panel="hidden"] .panel-card{display:none}
.diagram-card{flex:1;min-width:0;background:var(--bg-canvas);border:1px solid var(--border-box);
 border-radius:14px;padding:16px;display:flex;flex-direction:column}
.panel-card{background:var(--bg-panel);border:1px solid var(--border-box);border-radius:14px;
 padding:16px;min-width:0;align-self:flex-start}
.layout[data-panel="bottom"] .panel-card,.layout[data-panel="top"] .panel-card{align-self:stretch}
.toolbar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
button,.toolbar select{border:1px solid var(--border-box);background:var(--bg-card);border-radius:10px;
 padding:8px 14px;font-size:13px;font-weight:600;cursor:pointer;color:var(--text)}
button:hover,.toolbar select:hover{filter:brightness(1.1)}
.hint{font-size:12px;color:var(--text-muted)}
h1.viewer-title{font-size:19px;margin:0 0 12px;letter-spacing:-.01em;color:var(--text)}
.svg-scroll{flex:1;overflow:auto;min-height:220px}
svg.diagram{user-select:none;-webkit-user-select:none;display:block;max-width:none}
.node{cursor:grab;transition:opacity .18s ease}
.node:active{cursor:grabbing}
.widget-shell[data-drag="0"] .node{cursor:pointer}
.node-title{font-weight:700;font-family:'Segoe UI',Arial,sans-serif}
.node-sub{font-style:italic;font-family:'Segoe UI',Arial,sans-serif}
.node.active .pill{fill:var(--node-active-bg);stroke:var(--node-active-border);stroke-width:2.2}
.edge path{fill:none;stroke:var(--edge);stroke-width:1.6;stroke-dasharray:3 4;opacity:.45;
 transition:stroke .18s ease,stroke-width .18s ease,opacity .18s ease}
.edge-label{font-weight:600;font-family:'Segoe UI',Arial,sans-serif;
 fill:var(--text-muted);paint-order:stroke;stroke:var(--bg-canvas);stroke-width:4}
.edge-halo{fill:var(--bg-canvas)}
#arrIn path{fill:var(--edge-color)}
#arrAct path{fill:var(--edge-active)}
.edge.lit path{stroke:var(--edge-active);stroke-width:2;stroke-dasharray:none;opacity:1}
.edge.lit .edge-label{fill:var(--edge-active)}
svg.dim .node{opacity:.38}
svg.dim .node.lit{opacity:1}
svg.dim .edge{opacity:.12}
svg.dim .edge.lit{opacity:1}
.legend-bar{display:flex;gap:18px;flex-wrap:wrap;align-items:center;margin-top:12px;
 padding-top:10px;border-top:1px dashed var(--border-box);font-size:12.5px;color:var(--text-muted)}
.legend-item{display:inline-flex;align-items:center;white-space:nowrap}
.legend-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:7px;flex:none}
.bento-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:12px}
.bento-title{font-size:17px;font-weight:700;letter-spacing:-.01em;color:var(--text)}
.bento-badge{font-size:10.5px;font-weight:800;letter-spacing:.08em;padding:4px 12px;
 border-radius:999px;border:1px solid;white-space:nowrap}
.bento-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.bento-card{background:var(--bg-card);border:1px solid var(--border-box);border-radius:8px;
 padding:10px 12px;min-width:0}
.bento-card.span2{grid-column:span 2}
.bento-card h4{margin:0 0 6px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted)}
.bento-card p{margin:0;font-size:1em;line-height:1.55;white-space:pre-wrap;color:var(--text)}
"""
_VIEWER_JS = """
const NODES=__NODES__, EDGES=__EDGES__;
const DIR=__DIR__;
const SIZES=__SIZES__;
const ALLOW_DRAG=__ALLOW_DRAG__, EDGE_FS=__EDGE_FS__;
const INFO_H=__INFO_H__, INFO_C=__INFO_C__;
const ROOT=__ROOT__;
const incoming={}; EDGES.forEach(e=>{(incoming[e.target]=incoming[e.target]||[]).push(e.source);});
const svg=document.querySelector('svg.diagram');
const layoutEl=document.getElementById('layout');
const pos={};
svg.querySelectorAll('.node').forEach(g=>{pos[g.dataset.nid]={bx:parseFloat(g.dataset.x),by:parseFloat(g.dataset.y),dx:0,dy:0};});
const ex=nid=>pos[nid].bx+pos[nid].dx, ey=nid=>pos[nid].by+pos[nid].dy;
const _w=nid=>(SIZES[nid]||[190,64])[0], _h=nid=>(SIZES[nid]||[190,64])[1];
function stepped(x1,y1,x2,y2,horiz){
  const R=12;
  if(horiz){
    const dx=x2-x1,dy=y2-y1;
    if(Math.abs(dy)<1.5)return 'M'+x1+','+y1+' L'+x2+','+y2;
    const rr=Math.min(R,Math.abs(dx)/2-1,Math.abs(dy)/2-1),mx=x1+dx/2;
    if(rr<2)return 'M'+x1+','+y1+' L'+mx+','+y1+' L'+mx+','+y2+' L'+x2+','+y2;
    const sy=dy>0?1:-1;
    return 'M'+x1+','+y1+' L'+(mx-rr)+','+y1+' Q'+mx+','+y1+' '+mx+','+(y1+sy*rr)+
           ' L'+mx+','+(y2-sy*rr)+' Q'+mx+','+y2+' '+(mx+rr)+','+y2+' L'+x2+','+y2;
  }
  const dx=x2-x1,dy=y2-y1;
  if(Math.abs(dx)<1.5)return 'M'+x1+','+y1+' L'+x2+','+y2;
  const rr=Math.min(R,Math.abs(dx)/2-1,Math.abs(dy)/2-1),my=y1+dy/2;
  if(rr<2)return 'M'+x1+','+y1+' L'+x1+','+my+' L'+x2+','+my+' L'+x2+','+y2;
  const sx=dx>0?1:-1;
  return 'M'+x1+','+y1+' L'+x1+','+(my-rr)+' Q'+x1+','+my+' '+(x1+sx*rr)+','+my+
         ' L'+(x2-sx*rr)+','+my+' Q'+x2+','+my+' '+x2+','+(my+rr)+' L'+x2+','+y2;
}
function edgeGeom(s,t){
  if(DIR==='TB'){
    const x1=ex(s)+_w(s)/2,y1=ey(s)+_h(s),x2=ex(t)+_w(t)/2,y2=ey(t);
    return {d:stepped(x1,y1,x2,y2,false),lx:(x1+x2)/2,ly:(y1+y2)/2-8};
  }
  const x1=ex(s)+_w(s),y1=ey(s)+_h(s)/2,x2=ex(t),y2=ey(t)+_h(t)/2;
  return {d:stepped(x1,y1,x2,y2,true),lx:(x1+x2)/2,ly:(y1+y2)/2-8};
}
function redrawEdge(eg){
  const g=edgeGeom(eg.dataset.source,eg.dataset.target);
  eg.querySelector('path').setAttribute('d',g.d);
  const lab=eg.querySelector('.edge-label');
  if(lab){
    lab.setAttribute('x',g.lx);lab.setAttribute('y',g.ly);
    const halo=eg.querySelector('.edge-halo');
    if(halo){
      const w=lab.getComputedTextLength()+14,h=EDGE_FS*1.6;
      halo.setAttribute('x',g.lx-w/2);
      halo.setAttribute('y',g.ly-h/2-EDGE_FS*0.15);
      halo.setAttribute('width',w);halo.setAttribute('height',h);
    }
  }
}
function tightViewBox(){
  let l=0,t=0,r=0,b=0,first=true;
  for(const nid in pos){
    const x0=ex(nid),y0=ey(nid),x1=x0+_w(nid),y1=y0+_h(nid);
    if(first){l=x0;t=y0;r=x1;b=y1;first=false;}
    else{l=Math.min(l,x0);t=Math.min(t,y0);r=Math.max(r,x1);b=Math.max(b,y1);}
  }
  if(first)return;
  svg.setAttribute('viewBox',(l-12)+' '+(t-12)+' '+(r-l+24)+' '+(b-t+37));
}
function ancestors(nid){const seen=new Set([nid]),q=[nid];
  while(q.length){const c=q.pop();(incoming[c]||[]).forEach(p=>{if(!seen.has(p)){seen.add(p);q.push(p);}});}
  return seen;}
function setLit(eg,lit){
  eg.classList.toggle('lit',lit);
  eg.querySelector('path').setAttribute('marker-end',lit?'url(#arrAct)':'url(#arrIn)');
}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function titleCase(s){return String(s).replace(/\\w\\S*/g,w=>w.charAt(0).toUpperCase()+w.slice(1).toLowerCase());}
function parseDescCards(desc){
  const cards=[];let buf=[];
  const flush=t=>{const b=buf.join('\\n').trim();if(b)cards.push({title:t,body:b});buf=[];};
  String(desc||'').split('\\n').forEach(line=>{
    const m=line.match(/^\\s*([A-Za-z][\\w \\/-]{1,28}?)\\s*:\\s*(\\S[\\s\\S]*)$/);
    if(m){flush(cards.length?'Notes':'Description');cards.push({title:titleCase(m[1].trim()),body:m[2].trim()});}
    else buf.push(line);
  });
  flush(cards.length?'Notes':'Description');
  return cards.length?cards:[{title:'Description',body:'(No detailed description)'}];
}
function renderDefaultPanel(){
  document.getElementById('bentoTitle').textContent=INFO_H;
  document.getElementById('bentoBadge').style.display='none';
  document.getElementById('bentoGrid').innerHTML=
    '<div class="bento-card span2"><h4>Guide</h4><p>'+esc(INFO_C)+'</p></div>';
}
function renderPanel(nid){
  const n=NODES[nid];if(!n)return;
  document.getElementById('bentoTitle').textContent=n.title;
  const b=document.getElementById('bentoBadge');
  b.style.display='inline-block';b.textContent=n.typeLabel.toUpperCase();
  b.style.color=n.accent;b.style.borderColor=n.accent;b.style.background=n.accent+'1f';
  const cards=parseDescCards(n.desc).filter(c=>c.body&&c.body.trim());
  const list=cards.length?cards:[{title:'Description',body:'(No detailed description)'}];
  document.getElementById('bentoGrid').innerHTML=list.map((c,i)=>
    '<div class="bento-card'+(i<2&&list.length>1?'':' span2')+'"><h4>'+esc(c.title)+
    '</h4><p>'+esc(c.body)+'</p></div>').join('');
}
function reset(){
  svg.classList.remove('dim');
  svg.querySelectorAll('.lit').forEach(el=>el.classList.remove('lit'));
  svg.querySelectorAll('.node.active').forEach(el=>el.classList.remove('active'));
  svg.querySelectorAll('.edge path').forEach(p=>p.setAttribute('marker-end','url(#arrIn)'));
  renderDefaultPanel();
}
function select(nid){
  const n=NODES[nid];if(!n||!pos[nid])return;reset();
  const set=ancestors(nid);svg.classList.add('dim');
  svg.querySelectorAll('.node').forEach(g=>{if(set.has(g.dataset.nid))g.classList.add('lit');});
  const me=svg.querySelector('.node[data-nid="'+nid+'"]');
  if(me)me.classList.add('active');
  svg.querySelectorAll('.edge').forEach(eg=>{
    setLit(eg,set.has(eg.dataset.source)&&set.has(eg.dataset.target));});
  renderPanel(nid);
}
let drag=null,suppressClick=false;
svg.querySelectorAll('.node').forEach(g=>{
  g.addEventListener('click',ev=>{ev.stopPropagation();select(g.dataset.nid);});
  if(ALLOW_DRAG){
    g.addEventListener('mousedown',ev=>{
      ev.stopPropagation();ev.preventDefault();
      const p=pos[g.dataset.nid];
      drag={nid:g.dataset.nid,el:g,sx:ev.clientX,sy:ev.clientY,ox:p.dx,oy:p.dy,moved:false};
    });
  }
});
window.addEventListener('mousemove',ev=>{
  if(!drag)return;
  const rect=svg.getBoundingClientRect();
  const kx=svg.viewBox.baseVal.width/Math.max(1,rect.width);
  const ky=svg.viewBox.baseVal.height/Math.max(1,rect.height);
  const p=pos[drag.nid];
  if(Math.abs(ev.clientX-drag.sx)+Math.abs(ev.clientY-drag.sy)>4)drag.moved=true;
  p.dx=drag.ox+(ev.clientX-drag.sx)*kx;
  p.dy=drag.oy+(ev.clientY-drag.sy)*ky;
  drag.el.setAttribute('transform','translate('+p.dx+','+p.dy+')');
  svg.querySelectorAll('.edge').forEach(eg=>{
    if(eg.dataset.source===drag.nid||eg.dataset.target===drag.nid)redrawEdge(eg);
  });
  tightViewBox();
});
window.addEventListener('mouseup',()=>{
  if(!drag)return;
  const d=drag;drag=null;
  if(d.moved)suppressClick=true;else select(d.nid);
});
document.querySelector('.diagram-card').addEventListener('click',ev=>{
  if(suppressClick){suppressClick=false;return;}
  if(ev.target.closest('.node')||ev.target.closest('button')||ev.target.closest('select'))return;
  reset();
});
const rb=document.getElementById('resetBtn');
if(rb){rb.addEventListener('click',ev=>{ev.stopPropagation();reset();});}
const rpb=document.getElementById('resetPosBtn');
if(rpb){rpb.addEventListener('click',ev=>{
  ev.stopPropagation();
  for(const nid in pos){pos[nid].dx=0;pos[nid].dy=0;}
  svg.querySelectorAll('.node').forEach(g=>g.removeAttribute('transform'));
  svg.querySelectorAll('.edge').forEach(redrawEdge);
  tightViewBox();
});}
const pSel=document.getElementById('panelPosSel');
if(pSel){pSel.value=__PANEL__;pSel.addEventListener('change',()=>{layoutEl.dataset.panel=pSel.value;});}
renderDefaultPanel();
if(ROOT&&NODES[ROOT])select(ROOT);
"""


DEFAULT_INFO_HEADING = "Overview / Instructions"
DEFAULT_INFO_TEXT = ("Click any node in the diagram above to inspect its step "
                     "details and trace the decision path.")


def _js_str(s: str) -> str:
    """Encode a Python string as a JS string literal (</script>-safe)."""
    return json.dumps(s).replace("</", "<\\/")


PANEL_POSITIONS = ("bottom", "top", "left", "right", "hidden")


PANEL_POSITIONS = ("bottom", "top", "left", "right", "hidden")


def render_viewer_html(title: str, nodes: list[dict], edges: list[dict],
                       direction: str = "LR", gap_x: int = GAP_X,
                       gap_y: int = GAP_Y, info_heading: str | None = None,
                       info_text: str | None = None, theme: str = "dark",
                       panel: str = "bottom",
                       custom_colors: dict | None = None,
                       shell_w: int = 1100, shell_h: int = 640,
                       title_fs: float = 13.5, subtitle_fs: float = 11.5,
                       edge_fs: float = 11.0, panel_fs: float = 13.0,
                       sizes: dict | None = None,
                       show_toolbar: bool = True, allow_drag: bool = True,
                       hint_text: str = "", show_legend: bool = True) -> str:
    """Self-contained interactive viewer — double-clickable in any browser.

    direction: "LR" (left-to-right) or "TB" (top-to-bottom); gap_x/gap_y
    adjust node spacing in px. info_heading/info_text customize the bento
    panel's default content (shown when the selection is cleared).
    theme: "dark" (Dark Obsidian) | "light" (Clean White) | "custom"
    (custom_colors overrides). panel: "bottom" | "top" | "left" |
    "right" | "hidden". shell_w/shell_h: initial .widget-shell size in px
    (the shell is user-resizable via CSS ``resize: both``).
    title_fs/subtitle_fs/edge_fs/panel_fs: font-size sliders (px).
    sizes: optional {node_id: (w, h) or {"w","h","tl","sl"}} auto-fit boxes
    from ``node_boxes()`` (nodes widen/wrap instead of clipping text).
    show_toolbar: include the author toolbar (Reset view / Reset
    positions / panel switcher). allow_drag: nodes draggable in the
    viewer (locked read-only view when False). hint_text: optional
    instructional line (empty renders nothing). show_legend: bottom
    legend bar toggle.
    """
    direction = "TB" if str(direction).upper() == "TB" else "LR"
    panel = str(panel or "bottom").lower()
    if panel not in PANEL_POSITIONS:
        panel = "bottom"
    t = resolve_theme(theme, custom_colors)
    boxes = None
    if sizes:
        boxes = {nid: (s if isinstance(s, dict) and "tl" in s
                       else {"w": s[0], "h": s[1], "tl": _wrap(
                           node_title_sub(
                               _node_by_id(nodes).get(nid, {}))[0] or nid),
                             "sl": []})
                 for nid, s in sizes.items()}
    pos, sw, sh = layout(nodes, edges, direction, gap_x, gap_y, sizes)
    by_id = _node_by_id(nodes)
    js_nodes = {}
    for nid in pos:
        n = by_id.get(nid, {})
        ntype = str(n.get("type", "action")).strip() or "action"
        if boxes and nid in boxes:
            title_txt = " ".join(boxes[nid]["tl"]) or nid
        else:
            title_txt, _ = node_title_sub(n)
            title_txt = title_txt or nid
        js_nodes[nid] = {
            "title": title_txt,
            "desc": str(n.get("desc", "") or ""),
            "typeLabel": TYPE_LABEL.get(ntype, "Step"),
            "accent": type_accent(ntype, t),
        }
    js_edges = [{"source": str(e.get("source", "")).strip(),
                 "target": str(e.get("target", "")).strip()}
                for e in edges
                if str(e.get("source", "")).strip() in pos
                and str(e.get("target", "")).strip() in pos]
    ids = [str(n.get("id", "")).strip() for n in nodes]
    root = next((i for i in ids if i in pos and not _incoming(i, edges)), "")
    payload_nodes = json.dumps(js_nodes).replace("</", "<\\/")
    payload_edges = json.dumps(js_edges).replace("</", "<\\/")
    payload_sizes = json.dumps(
        {nid: [_box_wh(nid, sizes)[0], _box_wh(nid, sizes)[1]]
         for nid in pos}).replace("</", "<\\/")
    heading = DEFAULT_INFO_HEADING if info_heading is None else info_heading
    body_text = DEFAULT_INFO_TEXT if info_text is None else info_text
    css = (_VIEWER_CSS.replace("__BBG__", t["bg_canvas"])
                      .replace("__BTX__", t["text"]))
    js = (_VIEWER_JS.replace("__NODES__", payload_nodes)
          .replace("__EDGES__", payload_edges)
          .replace("__DIR__", json.dumps(direction))
          .replace("__SIZES__", payload_sizes)
          .replace("__ALLOW_DRAG__", "true" if allow_drag else "false")
          .replace("__EDGE_FS__", str(edge_fs))
          .replace("__INFO_H__", _js_str(heading))
          .replace("__INFO_C__", _js_str(body_text))
          .replace("__ROOT__", _js_str(root))
          .replace("__PANEL__", json.dumps(panel)))
    body = _svg_body(nodes, edges, pos, sw, sh, t, direction=direction,
                     sizes=sizes, boxes=boxes, title_fs=title_fs,
                     subtitle_fs=subtitle_fs, edge_fs=edge_fs)
    panel_opts = "".join(
        f'<option value="{p}">{p.capitalize()}</option>'
        for p in PANEL_POSITIONS)
    if show_toolbar:
        toolbar = (
            f'<div class="toolbar"><button id="resetBtn">\u21ba Reset view</button>'
            f'<button id="resetPosBtn" title="Undo all node dragging">'
            f'\u2316 Reset positions</button>'
            f'<select id="panelPosSel" title="Info panel position">'
            f'{panel_opts}</select>'
            + (f'<span class="hint">{html.escape(hint_text)}</span>'
               if hint_text.strip() else "")
            + f'</div>')
    else:
        toolbar = ""
    legend = _legend_bar(nodes, t) if show_legend else ""
    shell = (
        f'<div class="widget-shell" data-drag="{"1" if allow_drag else "0"}" '
        f'style="width:{int(shell_w)}px;'
        f'height:{int(shell_h)}px;{theme_css_vars(t)}">'
        f'<div class="layout" id="layout" data-panel="{panel}">'
        f'<section class="diagram-card">'
        f'{toolbar}'
        f'<h1 class="viewer-title">{html.escape(title)}</h1>'
        f'<div class="svg-scroll">{body}</div>'
        f'{legend}'
        f'</section>'
        f'<aside class="panel-card">'
        f'<div class="bento-head">'
        f'<div class="bento-title" id="bentoTitle">{html.escape(heading)}</div>'
        f'<span class="bento-badge" id="bentoBadge" style="display:none">'
        f'</span></div>'
        f'<div class="bento-grid" id="bentoGrid" '
        f'style="font-size:{panel_fs}px"></div>'
        f'</aside>'
        f'</div></div>')
    return ("<!DOCTYPE html>\n<html lang=\"en\"><head>"
            "<meta charset=\"utf-8\"/>\n"
            "<meta name=\"viewport\" content=\"width=device-width, "
            "initial-scale=1\"/>\n"
            f"<title>{html.escape(title)}</title>\n"
            f"<style>{css}</style></head>\n"
            f"<body>{shell}<script>{js}</script></body></html>")


# ------------------------------------------------------------ mermaid/svg
def to_mermaid(nodes: list[dict], edges: list[dict]) -> str:
    def mid(raw: str) -> str:
        return re.sub(r"\W+", "_", raw).strip("_") or "n"
    lines = ["flowchart LR"]
    for n in nodes:
        nid, label = mid(str(n.get("id", ""))), " | ".join(_wrap(n.get("label", ""), 18))
        label = label.replace('"', "'")
        t = str(n.get("type", "action")).strip()
        if t == "question":
            lines.append(f'    {nid}{{"{label}"}}')
        elif t == "end":
            lines.append(f'    {nid}(["{label}"])')
        else:
            lines.append(f'    {nid}["{label}"]')
    for e in edges:
        s, t = mid(str(e.get("source", ""))), mid(str(e.get("target", "")))
        lab = str(e.get("label", "") or "").replace('"', "'").strip()
        arrow = f'-->|"{lab}"|' if lab else "-->"
        lines.append(f"    {s} {arrow} {t}")
    return "\n".join(lines) + "\n"


def to_svg(nodes: list[dict], edges: list[dict], title: str = "",
           direction: str = "LR", gap_x: int = GAP_X, gap_y: int = GAP_Y,
           theme: str = "dark", sizes: dict | None = None,
           title_fs: float = 13.5, subtitle_fs: float = 11.5,
           edge_fs: float = 11.0) -> str:
    """Static SVG export (for PowerPoint / docs). Theme colors and font
    sizes are baked in as literal attributes so the file is
    self-contained."""
    direction = "TB" if str(direction).upper() == "TB" else "LR"
    t = resolve_theme(theme)
    boxes = None
    if sizes:
        boxes = {nid: (s if isinstance(s, dict) and "tl" in s
                       else {"w": s[0], "h": s[1], "tl": [""], "sl": []})
                 for nid, s in sizes.items()}
    pos, sw, sh = layout(nodes, edges, direction, gap_x, gap_y, sizes)
    top = 44 if title else 0
    title_el = (f'<text x="{PAD}" y="30" font-size="20" font-weight="700" '
                f'fill="{t["text"]}" font-family="Segoe UI, Arial, sans-serif">'
                f"{html.escape(title)}</text>" if title else "")
    return (f'<svg width="{sw}" height="{sh + top}" '
            f'viewBox="0 0 {sw} {sh + top}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<rect width="{sw}" height="{sh + top}" fill="{t["bg_canvas"]}"/>'
            f'<g transform="translate(0,{top})">'
            f"{_svg_inner(nodes, edges, pos, t, direction, sizes, boxes, title_fs, subtitle_fs, edge_fs)}</g>{title_el}</svg>")


# ------------------------------------------------------------ sharepoint wrap
_SP_SHELL_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;padding:0;overflow-x:hidden}
body{font-family:'Segoe UI',-apple-system,'Helvetica Neue',Arial,sans-serif;
color:#1f2937;background:#ffffff;line-height:1.5}
img,svg,video,iframe,table{max-width:100%;height:auto}
table{border-collapse:collapse}
.sp-wrap{width:100%;max-width:100%;margin:0 auto;padding:16px;overflow-x:hidden}
</style>
</head>
<body><div class="sp-wrap">
"""

_SP_SHELL_TAIL = """
</div></body>
</html>
"""


def wrap_sharepoint_html(raw: str, title: str = "Embedded content") -> str:
    """Wrap a partial HTML snippet in a SharePoint-iframe-friendly shell.

    The shell is UTF-8, responsive (no horizontal scrollbars, fluid media,
    clean system font stack). A complete ``<!DOCTYPE html>`` document
    (anything containing an ``<html`` tag) is returned unchanged.
    """
    raw = raw or ""
    if re.search(r"<html[\s>]", raw, re.IGNORECASE):
        return raw
    safe_title = html.escape(title or "Embedded content")
    return (_SP_SHELL_HEAD.replace("{title}", safe_title) + raw
            + _SP_SHELL_TAIL)


# ------------------------------------------------------------ security
DEFAULT_CSP = ("default-src 'none'; img-src 'self' data: blob:; "
               "style-src 'self' 'unsafe-inline'; script-src 'unsafe-inline'; "
               "font-src 'self' data:; connect-src 'none'; "
               "frame-ancestors 'self' *;")
"""Zero-exfiltration Content-Security-Policy: no outbound data leaks
(connect-src 'none'), no external scripts (script-src 'unsafe-inline'
only), and no external images (img-src 'self' data: blob: blocks
tracking pixels) — while inline styles/scripts and local/same-origin
images (./banner.jpg, /sites/...) keep working on any hosting platform."""

_EXTERNAL_URL = re.compile(r"^(?:https?:)?//", re.IGNORECASE)
_CSP_META = re.compile(
    r"<meta\b[^>]*http-equiv\s*=\s*[\"']?content-security-policy[\"']?[^>]*>",
    re.IGNORECASE)


def _line_no(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _line_snippet(text: str, pos: int, width: int = 110) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    if end == -1:
        end = len(text)
    line = text[start:end].strip()
    return line if len(line) <= width else line[:width - 3] + "..."


def audit_html_security(html_text: str) -> dict:
    """Scan HTML/CSS/JS for security risks before export.

    Flags external scripts/stylesheets/media (``src``/``href``/``@import``
    with http(s):// or protocol-relative URLs — scripts, styles, images,
    iframes, video/audio), outbound network calls
    (``fetch(``, ``XMLHttpRequest``, ``navigator.sendBeacon``,
    ``WebSocket``), and unsafe execution sinks (``eval(``,
    ``new Function(``). Returns ``{"passed": bool, "findings": [...]}``
    where each finding is ``{"kind", "line", "detail"}`` with the exact
    line number and URL/code snippet so the author can review or strip
    it. An empty document passes (nothing to leak).
    """
    doc = html_text or ""
    findings: list[dict] = []

    for m in re.finditer(r"<script\b[^>]*>", doc, re.IGNORECASE):
        sm = re.search(r"""\bsrc\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""",
                       m.group(0), re.IGNORECASE)
        if sm:
            url = sm.group(1).strip("\"'")
            if _EXTERNAL_URL.match(url):
                findings.append({"kind": "external-script",
                                 "line": _line_no(doc, m.start()),
                                 "detail": url})

    for m in re.finditer(r"<link\b[^>]*>", doc, re.IGNORECASE):
        tag = m.group(0)
        hm = re.search(r"""\bhref\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""",
                       tag, re.IGNORECASE)
        rm = re.search(r"""\brel\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""",
                       tag, re.IGNORECASE)
        rel = rm.group(1).strip("\"'").lower() if rm else ""
        if hm and ("stylesheet" in rel or not rel):
            url = hm.group(1).strip("\"'")
            if _EXTERNAL_URL.match(url):
                findings.append({"kind": "external-stylesheet",
                                 "line": _line_no(doc, m.start()),
                                 "detail": url})
    for m in re.finditer(r"@import\s+(?:url\(\s*)?[\"']([^\"']+)[\"']",
                         doc, re.IGNORECASE):
        url = m.group(1)
        if _EXTERNAL_URL.match(url):
            findings.append({"kind": "external-stylesheet",
                             "line": _line_no(doc, m.start()),
                             "detail": url})

    # External media/frames: tracking pixels and beacons hide here. The
    # tightened CSP (img-src 'self' data: blob:) blocks these at runtime;
    # the audit surfaces them so the author can strip the tag entirely.
    for m in re.finditer(
            r"<(?:img|iframe|video|audio|source|embed|track)\b[^>]*"
            r"\bsrc\s*=\s*(\"[^\"]*\"|'[^']*'|[^\\s>]+)",
            doc, re.IGNORECASE):
        url = m.group(1).strip("\"'")
        if _EXTERNAL_URL.match(url):
            findings.append({"kind": "external-media",
                             "line": _line_no(doc, m.start()),
                             "detail": url})

    for pat, label in ((r"\bfetch\s*\(", "fetch("),
                       (r"\bXMLHttpRequest\b", "XMLHttpRequest"),
                       (r"\bnavigator\.sendBeacon\b", "navigator.sendBeacon"),
                       (r"\bWebSocket\s*\(", "WebSocket(")):
        for m in re.finditer(pat, doc):
            findings.append({"kind": "network-call",
                             "line": _line_no(doc, m.start()),
                             "detail": f"{label} — "
                                       f"{_line_snippet(doc, m.start())}"})

    for pat, label in ((r"\beval\s*\(", "eval("),
                       (r"\bnew\s+Function\s*\(", "new Function(")):
        for m in re.finditer(pat, doc):
            findings.append({"kind": "unsafe-sink",
                             "line": _line_no(doc, m.start()),
                             "detail": f"{label} — "
                                       f"{_line_snippet(doc, m.start())}"})

    seen, uniq = set(), []
    for f in findings:
        key = (f["kind"], f["line"], f["detail"])
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return {"passed": not uniq, "findings": uniq}


def inject_csp(html_text: str, csp: str = DEFAULT_CSP) -> str:
    """Inject the zero-exfiltration CSP ``<meta>`` tag into ``<head>``.

    An existing CSP meta tag is replaced (deterministic policy); without
    a ``<head>`` a minimal one is created after ``<html>``, else the tag
    is prepended. Platform-agnostic — works on SharePoint, IIS, or any
    static host.
    """
    doc = html_text or ""
    tag = (f'<meta http-equiv="Content-Security-Policy" '
           f'content="{csp}">')
    if _CSP_META.search(doc):
        return _CSP_META.sub(tag, doc, count=1)
    m = re.search(r"<head\b[^>]*>", doc, re.IGNORECASE)
    if m:
        i = m.end()
        return doc[:i] + "\n" + tag + doc[i:]
    m = re.search(r"<html\b[^>]*>", doc, re.IGNORECASE)
    if m:
        i = m.end()
        return doc[:i] + f"\n<head>\n{tag}\n</head>" + doc[i:]
    return tag + "\n" + doc


_A_TAG = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_TARGET_BLANK = re.compile(r"""\btarget\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""",
                           re.IGNORECASE)
_REL_ATTR = re.compile(r"""\brel\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""",
                       re.IGNORECASE)


def sanitize_target_blank(html_text: str) -> str:
    """Reverse-tabnabbing protection: every ``<a target="_blank">`` gets
    ``rel="noopener noreferrer"`` (merged into an existing rel value
    when present). Other links are untouched."""
    def fix(m: re.Match) -> str:
        tag = m.group(0)
        tm = _TARGET_BLANK.search(tag)
        if not tm or tm.group(1).strip("\"'").lower() != "_blank":
            return tag
        rm = _REL_ATTR.search(tag)
        if rm:
            raw = rm.group(1)
            q = "\"" if raw.startswith("\"") else ("'" if raw.startswith("'")
                                                   else "")
            toks = raw.strip("\"'").split()
            lowered = [t.lower() for t in toks]
            for need in ("noopener", "noreferrer"):
                if need not in lowered:
                    toks.append(need)
            new_rel = f"rel={q}{' '.join(toks)}{q}" if q \
                else f"rel={' '.join(toks)}"
            return tag[:rm.start()] + new_rel + tag[rm.end():]
        return tag[:-1].rstrip() + ' rel="noopener noreferrer">'

    return _A_TAG.sub(fix, html_text or "")


def sanitize_export(html_text: str, use_csp: bool = True,
                    csp: str = DEFAULT_CSP) -> str:
    """Export hardening: reverse-tabnabbing link fix plus optional
    zero-exfiltration CSP injection. Byte-identical output feeds both
    the .html and .aspx downloads."""
    doc = sanitize_target_blank(html_text or "")
    return inject_csp(doc, csp) if use_csp else doc
