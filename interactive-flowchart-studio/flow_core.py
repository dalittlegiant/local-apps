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
def layout(nodes: list[dict], edges: list[dict], direction: str = "LR",
           gap_x: int = GAP_X, gap_y: int = GAP_Y
           ) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Layered layout. ``direction``: "LR" (depth -> columns, left to right)
    or "TB" (depth -> rows, top to bottom). ``gap_x``/``gap_y`` are the
    horizontal/vertical spacing between node blocks. Returns
    ({id: (x, y)}, svg_w, svg_h)."""
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
        n_rows = max(layers, default=0) + 1
        max_cols = max((len(c) for c in layers.values()), default=1)
        total_w = max_cols * NODE_W + (max_cols - 1) * gap_x
        for d, row in layers.items():
            y = PAD + d * (NODE_H + gap_y)
            row_w = len(row) * NODE_W + (len(row) - 1) * gap_x
            x0 = PAD + (total_w - row_w) // 2
            for c, nid in enumerate(row):
                pos[nid] = (x0 + c * (NODE_W + gap_x), y)
        svg_w = PAD * 2 + total_w
        svg_h = PAD * 2 + n_rows * NODE_H + (n_rows - 1) * gap_y
    else:
        n_cols = max(layers, default=0) + 1
        max_rows = max((len(c) for c in layers.values()), default=1)
        for d, col in layers.items():
            x = PAD + d * (NODE_W + gap_x)
            col_h = len(col) * NODE_H + (len(col) - 1) * gap_y
            total_h = max_rows * NODE_H + (max_rows - 1) * gap_y
            y0 = PAD + (total_h - col_h) // 2
            for r, nid in enumerate(col):
                pos[nid] = (x, y0 + r * (NODE_H + gap_y))
        svg_w = PAD * 2 + n_cols * NODE_W + (n_cols - 1) * gap_x
        svg_h = PAD * 2 + max_rows * NODE_H + (max_rows - 1) * gap_y
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
    shadow = ' filter="url(#nodeShadow)"'
    if ntype == "question":
        pts = f"{cx},{y} {x + NODE_W},{cy} {cx},{y + NODE_H} {x},{cy}"
        shape = (f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="2.5" stroke-linejoin="round"{shadow}/>')
    elif ntype == "end":
        shape = (f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" '
                 f'rx="32" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="2.5"{shadow}/>')
    else:
        shape = (f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" '
                 f'rx="12" fill="{fill}" stroke="{stroke}" '
                 f'stroke-width="2.5"{shadow}/>')
    tip = html.escape(str(node.get("desc", ""))[:200])
    return (f'<g class="node" data-nid="{html.escape(nid)}" '
            f'data-x="{x}" data-y="{y}">'
            f"<title>{tip}</title>{shape}{texts}</g>")


def _svg_edge(edge: dict, pos: dict[str, tuple[int, int]],
              direction: str = "LR") -> str:
    s, t = str(edge.get("source", "")).strip(), str(edge.get("target", "")).strip()
    if s not in pos or t not in pos:
        return ""
    if direction == "TB":
        x1, y1 = pos[s][0] + NODE_W / 2, pos[s][1] + NODE_H
        x2, y2 = pos[t][0] + NODE_W / 2, pos[t][1]
        my = (y1 + y2) / 2
        d = f"M{x1},{y1} C{x1},{my} {x2},{my} {x2},{y2}"
        lx, ly = (x1 + x2) / 2 + 8, my
    else:
        x1, y1 = pos[s][0] + NODE_W, pos[s][1] + NODE_H / 2
        x2, y2 = pos[t][0], pos[t][1] + NODE_H / 2
        mx = (x1 + x2) / 2
        d = f"M{x1},{y1} C{mx},{y1} {mx},{y2} {x2},{y2}"
        lx, ly = mx, (y1 + y2) / 2 - 7
    label = html.escape(str(edge.get("label", "") or ""))
    lab = (f'<text class="edge-label" x="{lx}" y="{ly}" text-anchor="middle" '
           f'paint-order="stroke" stroke="#ffffff" stroke-width="4">'
           f'{label}</text>' if label else "")
    return (f'<g class="edge" data-source="{html.escape(s)}" '
            f'data-target="{html.escape(t)}">'
            f'<path d="{d}" marker-end="url(#arrow)"/>{lab}</g>')


def _svg_defs() -> str:
    return ('<defs>'
            '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#94A3B8"/></marker>'
            '<marker id="arrowLit" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="8" markerHeight="8" orient="auto-start-reverse">'
            '<path d="M0,0 L10,5 L0,10 z" fill="#4F46E5"/></marker>'
            '<filter id="glow" x="-40%" y="-40%" width="180%" height="180%">'
            '<feDropShadow dx="0" dy="0" stdDeviation="7" '
            'flood-color="#4F46E5" flood-opacity="0.65"/></filter>'
            '<filter id="nodeShadow" x="-20%" y="-20%" width="140%" height="140%">'
            '<feDropShadow dx="0" dy="3" stdDeviation="5" '
            'flood-color="#0F172A" flood-opacity="0.10"/></filter>'
            '</defs>')


def _svg_inner(nodes: list[dict], edges: list[dict],
               pos: dict[str, tuple[int, int]], direction: str = "LR") -> str:
    by_id = _node_by_id(nodes)
    parts = [_svg_defs()]
    parts += [_svg_edge(e, pos, direction) for e in edges]
    for nid, (x, y) in pos.items():
        parts.append(_svg_node(nid, by_id.get(nid, {}), x, y))
    return "".join(parts)


def _svg_body(nodes: list[dict], edges: list[dict],
              pos: dict[str, tuple[int, int]], svg_w: int, svg_h: int,
              for_export: bool = False, direction: str = "LR") -> str:
    cls = ' class="diagram"' if not for_export else ""
    return (f'<svg{cls} width="{svg_w}" height="{svg_h}" '
            f'viewBox="0 0 {svg_w} {svg_h}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f"{_svg_inner(nodes, edges, pos, direction)}</svg>")


# ------------------------------------------------------------ html viewer
_VIEWER_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',-apple-system,'Helvetica Neue',Arial,sans-serif;background:#F8FAFC;color:#1f2937}
.wrap{display:flex;min-height:100%}
.diagram-pane{flex:1;overflow:auto;padding:20px;min-width:0;background:#FFFFFF;
 background-image:radial-gradient(#E8EDF3 1px,transparent 1px);background-size:22px 22px}
.side{width:330px;flex:none;background:#F8FAFC;border-left:1px solid #E2E8F0;padding:20px;overflow:auto}
.side h2{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:#94A3B8;margin:0 0 10px;font-weight:700}
#detailTitle{font-size:18px;font-weight:700;margin:0 0 6px;letter-spacing:-.01em}
#detailType{display:inline-block;font-size:11px;font-weight:700;padding:4px 12px;border-radius:999px;margin-bottom:12px;
 box-shadow:0 1px 2px rgba(15,23,42,.06)}
#detailDesc{font-size:13.5px;line-height:1.6;white-space:pre-wrap;color:#475569}
#path{margin-top:16px;font-size:12.5px;color:#64748B;background:#fff;border:1px solid #E2E8F0;border-radius:10px;padding:10px 12px}
#path:empty{display:none}
#path b{color:#4F46E5}
.toolbar{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}
button{border:1px solid #E2E8F0;background:#fff;border-radius:10px;padding:8px 14px;font-size:13px;font-weight:600;
 cursor:pointer;color:#334155;box-shadow:0 1px 2px rgba(15,23,42,.05);transition:background .15s,transform .1s}
button:hover{background:#F8FAFC}
button:active{transform:translateY(1px)}
.hint{font-size:12.5px;color:#94A3B8}
h1.viewer-title{font-size:20px;margin:0 0 14px;letter-spacing:-.01em}
svg.diagram{user-select:none;-webkit-user-select:none;display:block}
.node{cursor:grab;transition:opacity .18s ease}
.node:active{cursor:grabbing}
.edge{transition:opacity .18s ease}
.edge path{fill:none;stroke:#94A3B8;stroke-width:2;stroke-dasharray:6 4;
 transition:stroke .18s ease,stroke-width .18s ease,opacity .18s ease}
.edge-label{font-size:11.5px;font-weight:700;fill:#64748B;font-family:'Segoe UI',Arial,sans-serif;
 transition:fill .18s ease}
.edge.lit path{stroke:#4F46E5;stroke-width:3.2;stroke-dasharray:none;filter:url(#glow)}
.edge.lit .edge-label{fill:#4F46E5}
svg.dim .node{opacity:.3}
svg.dim .node.lit{opacity:1}
svg.dim .edge{opacity:.15}
svg.dim .edge.lit{opacity:1}
.node.lit{filter:url(#glow)}
"""

_VIEWER_JS = """
const NODES=__NODES__, EDGES=__EDGES__;
const DIR=__DIR__, NW=__NW__, NH=__NH__;
const INFO_H=__INFO_H__, INFO_C=__INFO_C__;
const incoming={}; EDGES.forEach(e=>{(incoming[e.target]=incoming[e.target]||[]).push(e.source);});
const svg=document.querySelector('svg.diagram');
const pos={};
svg.querySelectorAll('.node').forEach(g=>{
  pos[g.dataset.nid]={bx:parseFloat(g.dataset.x),by:parseFloat(g.dataset.y),dx:0,dy:0};
});
const ex=nid=>pos[nid].bx+pos[nid].dx, ey=nid=>pos[nid].by+pos[nid].dy;
function edgeGeom(s,t){
  if(DIR==='TB'){
    const x1=ex(s)+NW/2,y1=ey(s)+NH,x2=ex(t)+NW/2,y2=ey(t),my=(y1+y2)/2;
    return {d:'M'+x1+','+y1+' C'+x1+','+my+' '+x2+','+my+' '+x2+','+y2,
            lx:(x1+x2)/2+8,ly:my};
  }
  const x1=ex(s)+NW,y1=ey(s)+NH/2,x2=ex(t),y2=ey(t)+NH/2,mx=(x1+x2)/2;
  return {d:'M'+x1+','+y1+' C'+mx+','+y1+' '+mx+','+y2+' '+x2+','+y2,
          lx:mx,ly:(y1+y2)/2-7};
}
function redrawEdge(eg){
  const g=edgeGeom(eg.dataset.source,eg.dataset.target);
  eg.querySelector('path').setAttribute('d',g.d);
  const lab=eg.querySelector('.edge-label');
  if(lab){lab.setAttribute('x',g.lx);lab.setAttribute('y',g.ly);}
}
function redrawAllEdges(){svg.querySelectorAll('.edge').forEach(redrawEdge);}
function ancestors(nid){const seen=new Set([nid]),q=[nid];
  while(q.length){const c=q.pop();(incoming[c]||[]).forEach(p=>{if(!seen.has(p)){seen.add(p);q.push(p);}});}
  return seen;}
function setLit(eg,lit){
  eg.classList.toggle('lit',lit);
  eg.querySelector('path').setAttribute('marker-end',lit?'url(#arrowLit)':'url(#arrow)');
}
function reset(){
  svg.classList.remove('dim');
  svg.querySelectorAll('.lit').forEach(el=>el.classList.remove('lit'));
  svg.querySelectorAll('.edge path').forEach(p=>p.setAttribute('marker-end','url(#arrow)'));
  document.getElementById('detailTitle').textContent=INFO_H;
  document.getElementById('detailType').style.display='none';
  document.getElementById('detailDesc').textContent=INFO_C;
  document.getElementById('path').innerHTML='';
}
function select(nid){
  const node=NODES[nid];if(!node||!pos[nid])return;reset();
  const set=ancestors(nid);svg.classList.add('dim');
  svg.querySelectorAll('.node').forEach(g=>{if(set.has(g.dataset.nid))g.classList.add('lit');});
  svg.querySelectorAll('.edge').forEach(eg=>{
    setLit(eg,set.has(eg.dataset.source)&&set.has(eg.dataset.target));});
  const t=document.getElementById('detailType');
  t.style.display='inline-block';t.textContent=node.typeLabel;
  t.style.background=node.fill;t.style.color=node.stroke;t.style.border='1px solid '+node.stroke;
  document.getElementById('detailTitle').textContent=node.label;
  document.getElementById('detailDesc').textContent=node.desc||'(No detailed description)';
  const chain=[];let cur=nid,guard=0;
  while(cur&&guard++<500){chain.unshift(cur);const prev=(incoming[cur]||[])[0];cur=prev;}
  document.getElementById('path').innerHTML='<b>Path:</b> '+chain.map(id=>'<b>'+escapeHtml(NODES[id].label)+'</b>').join(' \\u2192 ');
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
let drag=null;
svg.querySelectorAll('.node').forEach(g=>{
  g.addEventListener('click',ev=>ev.stopPropagation());
  g.addEventListener('mousedown',ev=>{
    ev.stopPropagation();ev.preventDefault();
    const p=pos[g.dataset.nid];
    drag={nid:g.dataset.nid,el:g,sx:ev.clientX,sy:ev.clientY,ox:p.dx,oy:p.dy,moved:false};
  });
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
});
window.addEventListener('mouseup',()=>{
  if(!drag)return;
  const d=drag;drag=null;
  if(!d.moved)select(d.nid);
});
document.querySelector('.diagram-pane').addEventListener('click',reset);
document.getElementById('resetBtn').addEventListener('click',ev=>{ev.stopPropagation();reset();});
document.getElementById('resetPosBtn').addEventListener('click',ev=>{
  ev.stopPropagation();
  for(const nid in pos){pos[nid].dx=0;pos[nid].dy=0;}
  svg.querySelectorAll('.node').forEach(g=>g.removeAttribute('transform'));
  redrawAllEdges();
});
"""


DEFAULT_INFO_HEADING = "Overview / Instructions"
DEFAULT_INFO_TEXT = ("Click any node in the diagram above to inspect its step "
                     "details and trace the decision path.")


def _js_str(s: str) -> str:
    """Encode a Python string as a JS string literal (</script>-safe)."""
    return json.dumps(s).replace("</", "<\\/")


def render_viewer_html(title: str, nodes: list[dict], edges: list[dict],
                       direction: str = "LR", gap_x: int = GAP_X,
                       gap_y: int = GAP_Y, info_heading: str | None = None,
                       info_text: str | None = None) -> str:
    """Self-contained interactive viewer — double-clickable in any browser.

    direction: "LR" (left-to-right) or "TB" (top-to-bottom); gap_x/gap_y
    adjust node spacing in px. info_heading/info_text customize the side
    panel's default content (shown until a node is clicked and whenever
    the selection is cleared).
    """
    direction = "TB" if str(direction).upper() == "TB" else "LR"
    pos, sw, sh = layout(nodes, edges, direction, gap_x, gap_y)
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
    heading = DEFAULT_INFO_HEADING if info_heading is None else info_heading
    body_text = DEFAULT_INFO_TEXT if info_text is None else info_text
    js = (_VIEWER_JS.replace("__NODES__", payload_nodes)
          .replace("__EDGES__", payload_edges)
          .replace("__DIR__", json.dumps(direction))
          .replace("__NW__", str(NODE_W))
          .replace("__NH__", str(NODE_H))
          .replace("__INFO_H__", _js_str(heading))
          .replace("__INFO_C__", _js_str(body_text)))
    body = _svg_body(nodes, edges, pos, sw, sh, direction=direction)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>{_VIEWER_CSS}</style></head>
<body><div class="wrap">
<div class="diagram-pane">
<div class="toolbar"><button id="resetBtn">\u21ba Reset view</button>
<button id="resetPosBtn" title="Undo all node dragging">\u2316 Reset positions</button>
<span class="hint">Tip: click a node to trace its path &middot; drag nodes to rearrange.</span></div>
<h1 class="viewer-title">{html.escape(title)}</h1>
{body}</div>
<aside class="side"><h2>Step details</h2>
<div id="detailType" style="display:none"></div>
<p id="detailTitle">{html.escape(heading)}</p>
<p id="detailDesc">{html.escape(body_text)}</p>
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


def to_svg(nodes: list[dict], edges: list[dict], title: str = "",
           direction: str = "LR", gap_x: int = GAP_X, gap_y: int = GAP_Y) -> str:
    """Static SVG export (for PowerPoint / docs)."""
    direction = "TB" if str(direction).upper() == "TB" else "LR"
    pos, sw, sh = layout(nodes, edges, direction, gap_x, gap_y)
    top = 44 if title else 0
    title_el = (f'<text x="{PAD}" y="30" font-size="20" font-weight="700" '
                f'fill="#1f2937" font-family="Segoe UI, Arial, sans-serif">'
                f"{html.escape(title)}</text>" if title else "")
    return (f'<svg width="{sw}" height="{sh + top}" '
            f'viewBox="0 0 {sw} {sh + top}" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<g transform="translate(0,{top})">'
            f"{_svg_inner(nodes, edges, pos, direction)}</g>{title_el}</svg>")


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
