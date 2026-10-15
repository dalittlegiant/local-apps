"""App 8 — Interactive Flowchart Studio.

1. Node & edge table editor (st.data_editor + quick-add) with 2 starter
   templates.
2. Live interactive preview — click nodes to trace the path and read step
   details (client-side JS, no round-trip).
3. Standalone interactive HTML export (double-clickable, zero deps),
   plus Mermaid and SVG export for PowerPoint.

Pure logic lives in flow_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

P = "fc8_"
NODE_COLS = ["id", "label", "type", "desc"]
EDGE_COLS = ["source", "target", "label"]


def _nodes() -> pd.DataFrame:
    return st.session_state.setdefault(
        P + "nodes",
        pd.DataFrame([{"id": "start", "label": "Start here", "type": "action",
                       "desc": "Describe this step…"}]))


def _edges() -> pd.DataFrame:
    return st.session_state.setdefault(
        P + "edges",
        pd.DataFrame([{"source": "", "target": "", "label": ""}]))


def _as_records(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    df = df.copy()
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df = df[[c for c in cols]].fillna("")
    df = df[(df[cols[0]].astype(str).str.strip() != "")]
    return [{c: str(v).strip() for c, v in row.items()}
            for _, row in df.iterrows()]


st.title("🔀 Interactive Flowchart Studio")
st.caption("Build decision trees, SOPs, and business-logic flows — preview "
           "them live, then export a standalone interactive HTML file anyone "
           "can open.")

st.text_input("Flowchart title", value="My Flowchart", key=P + "title")

tab_edit, tab_preview, tab_export = st.tabs(
    ["📝 Node & Edge Editor", "👁️ Live Preview", "📦 Export"])

# ========================================================== TAB 1 ===
with tab_edit:
    st.subheader("Starter templates")
    t1, t2 = st.columns(2)
    for col, key in zip((t1, t2), ("report_access", "kpi_troubleshooting")):
        with col:
            tpl = core.starter_templates()[key]
            if st.button(f"📥 Load: {tpl['name']}", key=P + f"tpl_{key}",
                         use_container_width=True):
                st.session_state[P + "nodes"] = pd.DataFrame(tpl["nodes"])
                st.session_state[P + "edges"] = pd.DataFrame(tpl["edges"])
                st.session_state[P + "title"] = tpl["name"]
                st.rerun()

    st.subheader("Nodes")
    st.caption("Node_Type: question = decision diamond, action = step, "
               "end = end-state.")
    nodes_df = st.data_editor(
        _nodes(), num_rows="dynamic", use_container_width=True,
        key=P + "nodes_ed",
        column_config={
            "id": st.column_config.TextColumn("Node_ID", required=True),
            "label": st.column_config.TextColumn("Label", required=True),
            "type": st.column_config.SelectboxColumn(
                "Node_Type", options=list(core.NODE_TYPES), required=True),
            "desc": st.column_config.TextColumn("Detailed_Description",
                                                width="large"),
        })
    st.session_state[P + "nodes"] = nodes_df

    st.subheader("Edges")
    edges_df = st.data_editor(
        _edges(), num_rows="dynamic", use_container_width=True,
        key=P + "edges_ed",
        column_config={
            "source": st.column_config.TextColumn("Source_ID"),
            "target": st.column_config.TextColumn("Target_ID"),
            "label": st.column_config.TextColumn("Condition_Label",
                                                 help="e.g. Yes / No / Case A"),
        })
    st.session_state[P + "edges"] = edges_df

    st.subheader("Quick-add edge")
    node_ids = [str(i).strip() for i in nodes_df["id"].tolist()
                if str(i).strip()]
    if node_ids:
        q1, q2, q3, q4 = st.columns([2, 2, 2, 1])
        with q1:
            qs = st.selectbox("From", node_ids, key=P + "qe_s")
        with q2:
            qt = st.selectbox("To", node_ids, key=P + "qe_t")
        with q3:
            ql = st.text_input("Condition", key=P + "qe_l",
                               placeholder="Yes / No / …")
        with q4:
            st.write("")
            if st.button("➕ Add", key=P + "qe_add"):
                new = pd.DataFrame([{"source": qs, "target": qt,
                                     "label": ql}])
                st.session_state[P + "edges"] = pd.concat(
                    [edges_df, new], ignore_index=True)
                st.rerun()
    else:
        st.info("Add nodes first.")

    nodes = _as_records(nodes_df, NODE_COLS)
    edges = [e for e in _as_records(edges_df, EDGE_COLS)
             if e["source"] and e["target"]]
    for err in core.validate_flow(nodes, edges):
        st.error("⚠️ " + err)
    if not core.validate_flow(nodes, edges):
        st.success(f"✅ Valid — {len(nodes)} node(s), {len(edges)} edge(s).")

# ========================================================== TAB 2 ===
with tab_preview:
    st.subheader("Interactive preview")
    st.caption("Click any node to highlight its path from the start and read "
               "its detailed description. Click the background to reset.")
    nodes = _as_records(st.session_state[P + "nodes"], NODE_COLS)
    edges = [e for e in _as_records(st.session_state[P + "edges"], EDGE_COLS)
             if e["source"] and e["target"]]
    errors = core.validate_flow(nodes, edges)
    if errors:
        for err in errors:
            st.error("⚠️ " + err)
    elif not nodes:
        st.info("Add nodes in the editor first.")
    else:
        title = st.session_state.get(P + "title", "Flowchart")
        html_doc = core.render_viewer_html(title, nodes, edges)
        _, sw, sh = core.layout(nodes, edges)
        components.html(html_doc, height=min(720, sh + 220), scrolling=True)

# ========================================================== TAB 3 ===
with tab_export:
    st.subheader("Export")
    nodes = _as_records(st.session_state[P + "nodes"], NODE_COLS)
    edges = [e for e in _as_records(st.session_state[P + "edges"], EDGE_COLS)
             if e["source"] and e["target"]]
    errors = core.validate_flow(nodes, edges)
    if errors:
        for err in errors:
            st.error("⚠️ Fix validation errors before exporting: " + err)
    elif not nodes:
        st.info("Nothing to export yet.")
    else:
        title = st.session_state.get(P + "title", "Flowchart")
        stem = "".join(c if c.isalnum() else "_" for c in title).strip("_") \
            or "flowchart"
        c1, c2, c3 = st.columns(3)
        with c1:
            st.download_button(
                "🌐 Interactive HTML", core.render_viewer_html(
                    title, nodes, edges),
                f"{stem}.html", "text/html", key=P + "dl_html",
                help="Self-contained — double-click in Chrome/Edge, no Python needed.")
        with c2:
            st.download_button("🧜 Mermaid (.mmd)",
                               core.to_mermaid(nodes, edges),
                               f"{stem}.mmd", "text/plain", key=P + "dl_mmd")
        with c3:
            st.download_button("🖼️ SVG (for PowerPoint)",
                               core.to_svg(nodes, edges, title),
                               f"{stem}.svg", "image/svg+xml",
                               key=P + "dl_svg")
        st.caption("PowerPoint: Insert → Pictures → this SVG (ungroup to edit "
                   "shapes), or paste the Mermaid code into a Mermaid renderer.")
