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
check("svg shapes", "<polygon" in svg and "<rect" in svg)
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
check("edges dashed by default", "stroke-dasharray:6 4" in doc)
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

# --- sharepoint wrapper ---------------------------------------------------------
frag = core.wrap_sharepoint_html("<div class='ai-widget'>hi</div>", "My Widget")
check("fragment wrapped", frag.startswith("<!DOCTYPE html>")
      and "My Widget" in frag and "overflow-x:hidden" in frag)
check("wrapper responsive", "max-width:100%" in frag)
full = "<!DOCTYPE html><html><head></head><body>x</body></html>"
check("full doc untouched", core.wrap_sharepoint_html(full) == full)
check("wrapper title escaped",
      "&lt;b&gt;" in core.wrap_sharepoint_html("<p>x</p>", "<b>evil</b>"))
check("wrapper empty safe", "<!DOCTYPE html>" in core.wrap_sharepoint_html(""))

print(f"\nAll {passed} checks passed.")
