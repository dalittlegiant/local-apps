"""Core logic for the Interactive Flowchart Studio. Pure — no ``st.*`` calls.

Covers: flow validation, layered auto-layout, the standalone interactive
HTML viewer (HTML/CSS/vanilla JS, zero dependencies), Mermaid export,
and static SVG export.
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
FILL = {"question": "#EEF2FF", "action": "#ECFDF5", "end": "#FEF2F2"}
STROKE = {"question": "#4F46E5", "action": "#059669", "end": "#DC2626"}


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
def layout(nodes: list[dict], edges: list[dict]
           ) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Layered left-to-right layout. Returns ({id: (x, y)}, svg_w, svg_h)."""
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
    columns: dict[int, list[str]] = {}
    for i in ids:
        columns.setdefault(depth[i], []).append(i)
    n_cols = max(columns, default=0) + 1
    max_rows = max((len(c) for c in columns.values()), default=1)
    pos: dict[str, tuple[int, int]] = {}
    for d, col in columns.items():
        x = PAD + d * (NODE_W + GAP_X)
        col_h = len(col) * NODE_H + (len(col) - 1) * GAP_Y
        total_h = max_rows * NODE_H + (max_rows - 1) * GAP_Y
        y0 = PAD + (total_h - col_h) // 2
        for r, nid in enumerate(col):
            pos[nid] = (x, y0 + r * (NODE_H + GAP_Y))
    svg_w = PAD * 2 + n_cols * NODE_W + (n_cols - 1) * GAP_X
    svg_h = PAD * 2 + max_rows * NODE_H + (max_rows - 1) * GAP_Y
    return pos, svg_w, svg_h


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
def _svg_node(nid: str, node: dict, x: int, y: int) -> str:
    ntype = str(node.get("type", "action")).strip() or "action"
    fill, stroke = FILL.get(ntype, "#fff"), STROKE.get(ntype, "#333")
    lines = _wrap(node.get("label", nid))
    cx, cy = x + NODE_W / 2, y + NODE_H / 2
    texts = "".join(
        f'<text x="{cx}" y="{cy - (len(lines) - 1) * 8 + i * 16}" '
        f'text-anchor="middle" font-size="12.5" font-weight="600" '
        f'fill="#1f2937" font-family="Segoe UI, Arial, sans-serif">{html.escape(ln)}</text>'
        for i, ln in enumerate(lines))
    if ntype == "question":
        pts = f"{cx},{y} {x + NODE_W},{cy} {cx},{y + NODE_H} {x},{cy}"
        shape = (f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="2.5"/>')
    elif ntype == "end":
        shape = (f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" '
                 f'rx="32" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>')
    else:
        shape = (f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" '
                 f'rx="10" fill="{fill}" stroke="{stroke}" stroke-width="2.5"/>')
    tip = html.escape(str(node.get("desc", ""))[:200])
    return (f'<g class="node" data-nid="{html.escape(nid)}" cursor="pointer">'
            f"<title>{tip}</title>{shape}{texts}</g>")


def _svg_edge(edge: dict, pos: dict[str, tuple[int, int]]) -> str:
    s, t = str(edge.get("source", "")).strip(), str(edge.get("target", "")).strip()
    if s not in pos or t not in pos:
        return ""
    x1, y1 = pos[s][0] + NODE_W, pos[s][1] + NODE_H / 2
    x2, y2 = pos[t][0], pos[t][1] + NODE_H / 2
    mx = (x1 + x2) / 2
    label = html.escape(str(edge.get("label", "") or ""))
    lab = (f'<text x="{mx}" y="{(y1 + y2) / 2 - 7}" text-anchor="middle" '
           f'font-size="11.5" font-weight="700" fill="#4F46E5" '
           f'font-family="Segoe UI, Arial, sans-serif" '
           f'paint-order="stroke" stroke="#ffffff" stroke-width="4">{label}</text>'
           if label else "")
    return (f'<g class="edge" data-source="{html.escape(s)}" '
            f'data-target="{html.escape(t)}">'
            f'<path d="M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}" '
            f'fill="none" stroke="#9CA3AF" stroke-width="2" '
            f'marker-end="url(#arrow)"/>{lab}</g>')


def _svg_defs() -> str:
    return ('<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#9CA3AF"/></marker>'
            '<filter id="glow" x="-40%" y="-40%" width="180%" height="180%">'
            '<feDropShadow dx="0" dy="0" stdDeviation="7" '
            'flood-color="#4F46E5" flood-opacity="0.65"/></filter></defs>')


def _svg_inner(nodes: list[dict], edges: list[dict],
               pos: dict[str, tuple[int, int]]) -> str:
    by_id = _node_by_id(nodes)
    parts = [_svg_defs()]
    parts += [_svg_edge(e, pos) for e in edges]
    for nid, (x, y) in pos.items():
        parts.append(_svg_node(nid, by_id.get(nid, {}), x, y))
    return "".join(parts)


def _svg_body(nodes: list[dict], edges: list[dict],
              pos: dict[str, tuple[int, int]], svg_w: int, svg_h: int,
              for_export: bool = False) -> str:
    cls = ' class="diagram"' if not for_export else ""
    return (f'<svg{cls} width="{svg_w}" height="{svg_h}" '
            f'viewBox="0 0 {svg_w} {svg_h}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f"{_svg_inner(nodes, edges, pos)}</svg>")


# ------------------------------------------------------------ html viewer
_VIEWER_CSS = """
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',Arial,sans-serif;background:#F8FAFC;color:#1f2937}
.wrap{display:flex;min-height:100%;gap:0}
.diagram-pane{flex:1;overflow:auto;padding:18px;min-width:0;background:#fff}
.side{width:320px;flex:none;background:#F1F5F9;border-left:1px solid #E2E8F0;padding:18px;overflow:auto}
.side h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:#64748B;margin:0 0 8px}
#detailTitle{font-size:17px;font-weight:700;margin:0 0 4px}
#detailType{display:inline-block;font-size:11.5px;font-weight:700;padding:3px 10px;border-radius:999px;margin-bottom:10px}
#detailDesc{font-size:13.5px;line-height:1.55;white-space:pre-wrap;color:#334155}
#path{margin-top:14px;font-size:12.5px;color:#475569}
#path b{color:#4F46E5}
.toolbar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
button{border:1px solid #CBD5E1;background:#fff;border-radius:8px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;color:#334155}
button:hover{background:#F1F5F9}
.node{transition:opacity .18s}
svg.dim .node{opacity:.32}svg.dim .node.lit{opacity:1}
svg.dim .edge{opacity:.18}svg.dim .edge.lit{opacity:1}
.node.lit{filter:url(#glow)}
.hint{font-size:12.5px;color:#64748B;margin-top:10px}
"""

_VIEWER_JS = """
const NODES=__NODES__, EDGES=__EDGES__;
const incoming={}; EDGES.forEach(e=>{(incoming[e.target]=incoming[e.target]||[]).push(e.source);});
const svg=document.querySelector('svg.diagram');
function ancestors(nid){const seen=new Set([nid]),q=[nid];while(q.length){const c=q.pop();(incoming[c]||[]).forEach(p=>{if(!seen.has(p)){seen.add(p);q.push(p);}});}return seen;}
function edgeOnPath(set){return EDGES.filter(e=>set.has(e.source)&&set.has(e.target));}
function reset(){svg.classList.remove('dim');svg.querySelectorAll('.lit').forEach(el=>el.classList.remove('lit'));
 document.getElementById('detailTitle').textContent='Click any node';
 document.getElementById('detailType').style.display='none';
 document.getElementById('detailDesc').textContent='Select a step to highlight its full path from the start and read the detailed description.';
 document.getElementById('path').innerHTML='';}
function select(nid){const node=NODES[nid];if(!node)return;reset();const set=ancestors(nid);
 svg.classList.add('dim');
 svg.querySelectorAll('.node').forEach(g=>{if(set.has(g.dataset.nid))g.classList.add('lit');});
 const onSet=new Set(edgeOnPath(set).map(e=>e.source+'\\u0001'+e.target));
 svg.querySelectorAll('.edge').forEach(g=>{if(onSet.has(g.dataset.source+'\\u0001'+g.dataset.target))g.classList.add('lit');});
 const t=document.getElementById('detailType');t.style.display='inline-block';t.textContent=node.typeLabel;
 t.style.background=node.fill;t.style.color=node.stroke;t.style.border='1px solid '+node.stroke;
 document.getElementById('detailTitle').textContent=node.label;
 document.getElementById('detailDesc').textContent=node.desc||'(No detailed description)';
 const chain=[];let cur=nid,guard=0;
 while(cur&&guard++<500){chain.unshift(cur);const prev=(incoming[cur]||[])[0];cur=prev;}
 document.getElementById('path').innerHTML='<b>Path:</b> '+chain.map(id=>'<b>'+escapeHtml(NODES[id].label)+'</b>').join(' → ');}
function escapeHtml(s){return s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
svg.querySelectorAll('.node').forEach(g=>{g.addEventListener('click',ev=>{ev.stopPropagation();select(g.dataset.nid);});});
document.querySelector('.diagram-pane').addEventListener('click',reset);
document.getElementById('resetBtn').addEventListener('click',ev=>{ev.stopPropagation();reset();});
"""


def render_viewer_html(title: str, nodes: list[dict], edges: list[dict]) -> str:
    """Self-contained interactive viewer — double-clickable in any browser."""
    pos, sw, sh = layout(nodes, edges)
    by_id = _node_by_id(nodes)
    js_nodes = {
        nid: {"label": str(by_id.get(nid, {}).get("label", nid)),
              "desc": str(by_id.get(nid, {}).get("desc", "") or ""),
              "typeLabel": TYPE_LABEL.get(
                  str(by_id.get(nid, {}).get("type", "action")).strip(), "Step"),
              "fill": FILL.get(str(by_id.get(nid, {}).get("type", "action")).strip(), "#fff"),
              "stroke": STROKE.get(str(by_id.get(nid, {}).get("type", "action")).strip(), "#333")}
        for nid in pos}
    js_edges = [{"source": str(e.get("source", "")).strip(),
                 "target": str(e.get("target", "")).strip()}
                for e in edges
                if str(e.get("source", "")).strip() in pos
                and str(e.get("target", "")).strip() in pos]
    payload_nodes = json.dumps(js_nodes).replace("</", "<\\/")
    payload_edges = json.dumps(js_edges).replace("</", "<\\/")
    js = _VIEWER_JS.replace("__NODES__", payload_nodes).replace("__EDGES__", payload_edges)
    body = _svg_body(nodes, edges, pos, sw, sh)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{_VIEWER_CSS}</style></head>
<body><div class="wrap">
<div class="diagram-pane">
<div class="toolbar"><button id="resetBtn">↺ Reset view</button>
<span class="hint">Tip: click any node to trace its path &amp; read details.</span></div>
<h1 style="font-size:20px;margin:0 0 12px">{html.escape(title)}</h1>
{body}</div>
<aside class="side"><h2>Step details</h2>
<div id="detailType" style="display:none"></div>
<p id="detailTitle">Click any node</p>
<p id="detailDesc">Select a step to highlight its full path from the start and read the detailed description.</p>
<div id="path"></div></aside>
</div><script>{js}</script></body></html>"""


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


def to_svg(nodes: list[dict], edges: list[dict], title: str = "") -> str:
    """Static SVG export (for PowerPoint / docs)."""
    pos, sw, sh = layout(nodes, edges)
    top = 44 if title else 0
    title_el = (f'<text x="{PAD}" y="30" font-size="20" font-weight="700" '
                f'fill="#1f2937" font-family="Segoe UI, Arial, sans-serif">'
                f"{html.escape(title)}</text>" if title else "")
    return (f'<svg width="{sw}" height="{sh + top}" '
            f'viewBox="0 0 {sw} {sh + top}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<g transform="translate(0,{top})">'
            f"{_svg_inner(nodes, edges, pos)}</g>{title_el}</svg>")
