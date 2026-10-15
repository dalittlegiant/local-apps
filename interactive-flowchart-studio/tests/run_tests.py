"""Tests for interactive-flowchart-studio/flow_core.py. No Streamlit needed.

Run:  python3 tests/run_tests.py   (from the app directory)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flow_core as core  # noqa: E402

passed = 0


def check(name, cond, detail=""):
    global passed
    if not cond:
        print(f"FAIL: {name} {detail}")
        sys.exit(1)
    passed += 1
    print(f"ok: {name}")


def flow():
    nodes = [
        {"id": "a", "label": "Start process", "type": "action", "desc": "d1"},
        {"id": "b", "label": "Approved?", "type": "question", "desc": "d2"},
        {"id": "c", "label": "Do the thing", "type": "action", "desc": "d3"},
        {"id": "d", "label": "Done", "type": "end", "desc": "d4"},
    ]
    edges = [
        {"source": "a", "target": "b", "label": ""},
        {"source": "b", "target": "c", "label": "Yes"},
        {"source": "b", "target": "d", "label": "No"},
        {"source": "c", "target": "d", "label": ""},
    ]
    return nodes, edges


nodes, edges = flow()

# --- validation ---------------------------------------------------------
check("valid flow", core.validate_flow(nodes, edges) == [])
n2 = [dict(n, id="a") for n in nodes]
check("dupe ids", any("Duplicate" in e for e in core.validate_flow(n2, edges)))
n3 = [dict(nodes[0], type="bogus")] + nodes[1:]
check("bad type", any("Node_Type" in e for e in core.validate_flow(n3, edges)))
check("unknown edge ref",
      any("unknown node" in e for e in core.validate_flow(
          nodes, edges + [{"source": "a", "target": "zz", "label": ""}])))
cyc = [{"id": "x", "label": "x", "type": "action", "desc": ""},
       {"id": "y", "label": "y", "type": "action", "desc": ""}]
check("no start detected",
      any("start node" in e for e in core.validate_flow(
          cyc, [{"source": "x", "target": "y", "label": ""},
                {"source": "y", "target": "x", "label": ""}])))
check("empty id flagged",
      any("Node_ID" in e for e in core.validate_flow(
          [dict(nodes[0], id=" ")] + nodes[1:], edges)))

# --- layout ---------------------------------------------------------------
pos, sw, sh = core.layout(nodes, edges)
check("layers left-to-right",
      pos["a"][0] < pos["b"][0] < pos["c"][0] < pos["d"][0])
check("longest-path depth",
      pos["d"][0] == pos["c"][0] + core.NODE_W + core.GAP_X)
check("svg sized", sw > 0 and sh > 0)

# --- viewer html ------------------------------------------------------------
doc = core.render_viewer_html("My Flow", nodes, edges)
check("doctype", doc.startswith("<!DOCTYPE html>"))
check("labels embedded", "Start process" in doc and "Approved?" in doc)
check("edge label embedded", ">Yes<" in doc)
check("desc in js payload", '"d2"' in doc)
check("no external deps",
      "http" not in doc.replace("http://www.w3.org", ""))

tricky = [dict(nodes[0], label='X </script> <b>bold</b> & "q"')]
doc2 = core.render_viewer_html("T", tricky, [])
check("script-break escaped", "<\\/script>" in doc2)
check("html escaped in svg", "&lt;b&gt;bold&lt;/b&gt;" in doc2
      and "&amp;" in doc2)

# --- mermaid ------------------------------------------------------------------
mm = core.to_mermaid(nodes, edges)
check("mermaid header", mm.startswith("flowchart LR"))
check("mermaid diamond", '{"' in mm)
check("mermaid stadium", '(["' in mm)
check("mermaid edge label", '-->|"Yes"|' in mm)

# --- svg -----------------------------------------------------------------------
svg = core.to_svg(nodes, edges, "My Flow")
check("svg wrapper", svg.startswith("<svg") and "</svg>" in svg)
check("svg shapes", 'rx="26"' in svg and "<circle" in svg)  # pill nodes + type dots
check("svg title", "My Flow" in svg)

# --- templates ------------------------------------------------------------------
for key, tpl in core.starter_templates().items():
    errs = core.validate_flow(tpl["nodes"], tpl["edges"])
    check(f"template {key} valid", errs == [], str(errs))
    d = core.render_viewer_html(tpl["name"], tpl["nodes"], tpl["edges"])
    check(f"template {key} renders", "<svg" in d and tpl["name"] in d)

# --- layout direction + gaps -------------------------------------------------
pos_tb, sw_tb, sh_tb = core.layout(nodes, edges, direction="TB")
check("TB layers top-to-bottom",
      pos_tb["a"][1] < pos_tb["b"][1] < pos_tb["c"][1] < pos_tb["d"][1])
check("TB row spacing",
      pos_tb["d"][1] - pos_tb["c"][1] == core.NODE_H + core.GAP_Y)
same_row_nodes = [
    {"id": "s", "label": "S", "type": "action", "desc": ""},
    {"id": "x", "label": "X", "type": "action", "desc": ""},
    {"id": "y", "label": "Y", "type": "action", "desc": ""},
]
same_row_edges = [{"source": "s", "target": "x", "label": ""},
                  {"source": "s", "target": "y", "label": ""}]
pos_sr, _, _ = core.layout(same_row_nodes, same_row_edges, direction="TB")
check("TB same-depth side by side",
      pos_sr["x"][1] == pos_sr["y"][1]
      and pos_sr["y"][0] - pos_sr["x"][0] == core.NODE_W + core.GAP_X)
pos_gx, _, _ = core.layout(nodes, edges, gap_x=200)
check("custom horizontal gap",
      pos_gx["b"][0] - pos_gx["a"][0] == core.NODE_W + 200)
pos_gy, _, _ = core.layout(same_row_nodes, same_row_edges, gap_y=99)
check("custom vertical gap",
      pos_gy["y"][1] - pos_gy["x"][1] == core.NODE_H + 99)
check("bad direction falls back to LR",
      core.layout(nodes, edges, direction="XX")[0]["a"][0]
      == core.layout(nodes, edges)[0]["a"][0])

# --- viewer: dashed edges, drag, info panel ----------------------------------
doc = core.render_viewer_html("My Flow", nodes, edges)
check("edges dashed by default", "stroke-dasharray:3 4" in doc)
check("lit edge style", ".edge.lit path" in doc and "stroke-dasharray:none" in doc)
check("drag handlers", "mousedown" in doc and "redrawEdge" in doc)
check("reset positions button", 'id="resetPosBtn"' in doc)
check("node position data attrs", 'data-x="' in doc)
check("default info panel",
      core.DEFAULT_INFO_HEADING in doc and core.DEFAULT_INFO_TEXT in doc)
doc_tb = core.render_viewer_html("T", nodes, edges, direction="TB")
check("TB viewer direction", 'const DIR="TB"' in doc_tb)
doc_info = core.render_viewer_html("T", nodes, edges,
                                   info_heading="My Guide",
                                   info_text="Follow the money.")
check("custom info panel", "My Guide" in doc_info and "Follow the money." in doc_info)
check("no external deps",
      "http" not in doc.replace("http://www.w3.org", ""))
svg_tb = core.to_svg(nodes, edges, "T", direction="TB")
check("svg TB renders", svg_tb.startswith("<svg") and "</svg>" in svg_tb)

# --- pill nodes / subtitles ---------------------------------------------------
t1, s1 = core.node_title_sub({"label": "Main Title | Sub Title"})
check("label auto-split", (t1, s1) == ("Main Title", "Sub Title"))
t2, s2 = core.node_title_sub({"label": "A | B", "subtitle": "Explicit"})
check("explicit subtitle wins", (t2, s2) == ("A | B", "Explicit"))
t3, s3 = core.node_title_sub({"label": "Plain"})
check("no subtitle", (t3, s3) == ("Plain", ""))
doc_sub = core.render_viewer_html(
    "T", [dict(nodes[0], label="Main Title | Sub Title")], [])
check("pill node", 'rx="26"' in doc_sub and 'class="pill"' in doc_sub)
check("two-line text", 'class="node-title"' in doc_sub
      and 'class="node-sub"' in doc_sub and "Sub Title" in doc_sub)
check("type dot", 'class="node-dot"' in doc_sub)

# --- orthogonal stepped edges -------------------------------------------------
doc_e = core.render_viewer_html("T", nodes, edges)
check("stepped path Q curves", " Q" in doc_e)
check("legend bar", 'class="legend-bar"' in doc_e
      and 'class="legend-dot"' in doc_e and "Question / Decision" in doc_e)
check("inactive edge opacity", 'opacity="0.45"' in doc_e)
check("bento panel", 'class="bento-grid"' in doc_e
      and 'id="bentoTitle"' in doc_e and 'class="bento-badge"' in doc_e)
check("panel position toggle", 'id="panelPosSel"' in doc_e)
check("root auto-select", 'if(ROOT&&NODES[ROOT])select(ROOT);' in doc_e)

# --- themes ----------------------------------------------------------------------
doc_dark = core.render_viewer_html("T", nodes, edges)  # default
check("dark obsidian default", "--bg-canvas:#0e1015" in doc_dark
      and "--node-active-border:#5c8df6" in doc_dark)
doc_light = core.render_viewer_html("T", nodes, edges, theme="light")
check("clean white theme", "--bg-canvas:#ffffff" in doc_light
      and "--edge-active:#2563eb" in doc_light)
doc_custom = core.render_viewer_html(
    "T", nodes, edges, theme="custom",
    custom_colors={"canvas_bg": "#123456", "edge_color": "#abcdef"})
check("custom palette", "--bg-canvas:#123456" in doc_custom
      and "--edge:#abcdef" in doc_custom)
check("custom falls back sanely",
      "--bg-canvas:#0e1015" in core.render_viewer_html(
          "T", nodes, edges, theme="bogus"))
check("resolve_theme unknown", core.resolve_theme("nope")["bg_canvas"] == "#0e1015")

# --- panel positions ---------------------------------------------------------------
for p in ("bottom", "top", "left", "right", "hidden"):
    d = core.render_viewer_html("T", nodes, edges, panel=p)
    check(f"panel {p}", f'data-panel="{p}"' in d)
check("bad panel falls back",
      'data-panel="bottom"' in core.render_viewer_html(
          "T", nodes, edges, panel="sideways"))

# --- tight bounding box / resizable shell --------------------------------------------
pos_t, sw_t, sh_t = core.layout(nodes, edges)
_l = min(x for x, _ in pos_t.values())
_t = min(y for _, y in pos_t.values())
_r = max(x + core.NODE_W for x, _ in pos_t.values())
_b = max(y + core.NODE_H for _, y in pos_t.values())
check("tight viewBox size", (sw_t, sh_t) == (_r - _l + 24, _b - _t + 37))
doc_t = core.render_viewer_html("T", nodes, edges)
check("tight viewBox attr",
      f'viewBox="{_l - 12} {_t - 12} {sw_t} {sh_t}"' in doc_t)
check("resizable shell", "resize:both" in doc_dark and "overflow:auto" in doc_dark)
doc_size = core.render_viewer_html("T", nodes, edges, shell_w=900, shell_h=500)
check("shell size params", "width:900px" in doc_size and "height:500px" in doc_size)
check("tight viewBox recalc on drag", "tightViewBox()" in doc_dark)

# --- sharepoint wrapper (unchanged contracts) ------------------------------------------
frag = core.wrap_sharepoint_html("<div class='ai-widget'>hi</div>", "My Widget")
check("fragment wrapped", frag.startswith("<!DOCTYPE html>")
      and "My Widget" in frag and "overflow-x:hidden" in frag)
check("wrapper responsive", "max-width:100%" in frag)
full = "<!DOCTYPE html><html><head></head><body>x</body></html>"
check("full doc untouched", core.wrap_sharepoint_html(full) == full)
check("wrapper title escaped",
      "&lt;b&gt;" in core.wrap_sharepoint_html("<p>x</p>", "<b>evil</b>"))
check("wrapper empty safe", "<!DOCTYPE html>" in core.wrap_sharepoint_html(""))

# --- auto-fit node boxes ---------------------------------------------------------------
box_short = core.node_box({"id": "a", "label": "OK"})
check("box min width", box_short["w"] == 180 and box_short["h"] == 64)
box_long = core.node_box({"id": "b", "label": "This is a deliberately long node title that should widen the pill"})
check("box widens", 180 < box_long["w"] <= 380)
box_huge = core.node_box({"id": "c", "label": "Supercalifragilisticexpialidocious " * 6})
check("box wraps + grows", len(box_huge["tl"]) > 1 and box_huge["h"] > 64
      and box_huge["w"] <= 380)
box_ascii = core.node_box({"id": "d", "label": "aaaaaaaaaa"})
box_cjk = core.node_box({"id": "e", "label": "\u4e2d" * 10})
check("CJK 1.8x width", box_cjk["w"] > box_ascii["w"])
boxes = core.node_boxes([{"id": "a", "label": "OK"},
                         {"id": "e", "label": "\u4e2d" * 10}])
check("node_boxes map", set(boxes) == {"a", "e"} and "tl" in boxes["e"])
check("node_boxes skips blank id",
      core.node_boxes([{"id": ""}, {"id": "  "}]) == {})

# variable-width layout: same-rank neighbours never overlap
wn = [{"id": "r", "label": "Root"},
      {"id": "x", "label": "A very long label that forces the pill wide"},
      {"id": "y", "label": "Y"}]
we = [{"source": "r", "target": "x"}, {"source": "r", "target": "y"}]
wsizes = core.node_boxes(wn)
pos_w, _, _ = core.layout(wn, we, "LR", sizes=wsizes)
check("wide layer pushes next out",
      pos_w["x"][0] >= pos_w["r"][0] + wsizes["r"]["w"] + core.GAP_X
      or pos_w["y"][0] >= pos_w["r"][0] + wsizes["r"]["w"] + core.GAP_X)

# --- font-size params ------------------------------------------------------------------
doc_fs = core.render_viewer_html("T", nodes, edges, title_fs=16, edge_fs=14,
                                 show_toolbar=False, allow_drag=False,
                                 sizes=core.node_boxes(nodes))
check("title font-size attr", 'font-size="16"' in doc_fs)
check("edge font-size attr", 'font-size="14"' in doc_fs)
check("panel body font-size",
      'id="bentoGrid" style="font-size:15px"' in core.render_viewer_html(
          "T", nodes, edges, panel_fs=15))
check("edge halo rect", 'class="edge-halo"' in doc_fs)
check("marker css sync", "var(--edge-active)" in doc_fs
      and "var(--edge-color)" in doc_fs)

# --- read-only export separation -------------------------------------------------------
check("export no toolbar", 'id="resetBtn"' not in doc_fs
      and 'id="panelPosSel"' not in doc_fs)
check("export toolbar present by default", 'id="resetBtn"' in doc_dark)
check("locked drag baked", "const ALLOW_DRAG=false" in doc_fs
      and 'data-drag="0"' in doc_fs)
check("drag allowed by default", "const ALLOW_DRAG=true" in doc_dark)
check("hint empty renders nothing",
      'class="hint"' not in core.render_viewer_html("T", nodes, edges))
check("hint renders when set",
      'class="hint">hello</span>' in core.render_viewer_html(
          "T", nodes, edges, hint_text="hello"))
check("legend toggle off", 'class="legend-bar"' not in core.render_viewer_html(
    "T", nodes, edges, show_legend=False))
check("legend on by default", 'class="legend-bar"' in doc_dark)
check("zero scrollbars css", "overflow-x:hidden" in doc_fs)
check("sizes in JS payload", "const SIZES=" in doc_fs
      and '"a": [' in doc_fs)

# static SVG keeps font-size attributes
svg_fs = core.to_svg(nodes, edges, "T", sizes=core.node_boxes(nodes),
                     title_fs=16)
check("static svg font size", 'font-size="16"' in svg_fs)

# --- security sanitizer / CSP / dual-format ----------------------------------------------
check("csp policy text", core.DEFAULT_CSP == "default-src 'none'; "
      "img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline'; "
      "script-src 'unsafe-inline'; font-src 'self' data:; connect-src 'none'; "
      "frame-ancestors 'self' *;")
audit_clean = core.audit_html_security(
    core.render_viewer_html("T", nodes, edges))
check("audit clean viewer", audit_clean["passed"]
      and not audit_clean["findings"])
audit_wrap = core.audit_html_security(
    core.wrap_sharepoint_html("<div class='ai-widget'>x</div>", "t"))
check("audit clean wrapper", audit_wrap["passed"])
evil = ('<html><head></head><body>\n'
        '<script src="https://cdn.example.com/lib.js"></script>\n'
        '<link rel="stylesheet" href="http://cdn.example.com/x.css">\n'
        '<style>@import url("https://cdn.example.com/i.css");</style>\n'
        '<script>fetch("https://evil.com");eval("x");'
        'var f=new Function("a");var x=new XMLHttpRequest();'
        'navigator.sendBeacon("/l");var w=new WebSocket("ws://e");</script>\n'
        '<a href="https://x.com" target="_blank">hi</a>\n'
        '</body></html>')
audit_evil = core.audit_html_security(evil)
check("audit flags evil", not audit_evil["passed"])
kinds = {f["kind"] for f in audit_evil["findings"]}
check("audit kinds", kinds == {"external-script", "external-stylesheet",
                               "network-call", "unsafe-sink"})
check("audit line + url",
      any(f["line"] == 2 and "cdn.example.com/lib.js" in f["detail"]
          for f in audit_evil["findings"]))
check("audit import flagged",
      any(f["kind"] == "external-stylesheet" and "i.css" in f["detail"]
          for f in audit_evil["findings"]))
check("audit empty passes", core.audit_html_security("")["passed"])
csp_doc = core.inject_csp("<html><head><title>t</title></head>"
                          "<body>x</body></html>")
check("csp injected in head",
      '<meta http-equiv="Content-Security-Policy"' in csp_doc
      and "connect-src 'none'" in csp_doc
      and csp_doc.index("Content-Security-Policy") > csp_doc.index("<head>"))
check("csp exact policy", f'content="{core.DEFAULT_CSP}"' in csp_doc)
check("csp replaced not duplicated",
      core.inject_csp(csp_doc).count(
          'http-equiv="Content-Security-Policy"') == 1)
check("csp no-head fallback",
      "Content-Security-Policy" in core.inject_csp("<p>hi</p>"))
link_doc = core.sanitize_target_blank(
    '<a href="https://x.com" target="_blank">hi</a>')
check("tabnabbing fixed", 'rel="noopener noreferrer"' in link_doc)
check("tabnabbing untouched",
      "rel=" not in core.sanitize_target_blank(
          '<a href="/" target="_self">x</a>'))
check("tabnabbing merges",
      'rel="noopener noreferrer"' in core.sanitize_target_blank(
          '<a href="https://x.com" target="_blank" rel="noopener">x</a>'))
safe = core.sanitize_export(evil, use_csp=True)
check("sanitize_export", "Content-Security-Policy" in safe
      and 'rel="noopener noreferrer"' in safe)
safe_nc = core.sanitize_export(evil, use_csp=False)
check("sanitize_export no csp", "Content-Security-Policy" not in safe_nc
      and 'rel="noopener noreferrer"' in safe_nc)

print(f"\nAll {passed} checks passed.")
