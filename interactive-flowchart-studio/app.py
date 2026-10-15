"""App 8 — Interactive Flowchart Studio.

1. Node & edge table editor (st.data_editor + quick-add) with 2 starter
   templates.
2. Live interactive preview — click nodes to trace the path and read step
   details, drag nodes to rearrange (client-side JS, no round-trip).
3. Standalone interactive HTML export (double-clickable, zero deps),
   plus Mermaid and SVG export for PowerPoint.
4. Custom AI HTML Studio — wrap AI-generated HTML snippets in a
   SharePoint-iframe-friendly shell, preview live, download.

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

try:
    st.set_page_config(page_title="Interactive Flowchart Studio", page_icon="🔀", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "fc8_"
NODE_COLS = ["id", "label", "subtitle", "type", "desc"]
EDGE_COLS = ["source", "target", "label"]


def _nodes() -> pd.DataFrame:
    return st.session_state.setdefault(
        P + "nodes",
        pd.DataFrame([{"id": "start", "label": "Start here", "subtitle": "",
                       "type": "action", "desc": "Describe this step…"}]))


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


def _load_template(key: str):
    """on_click callback for the starter-template buttons.

    Callbacks run BEFORE the script body, so assigning widget-bound keys
    (fc8_title) here is legal — doing it inline after the text_input was
    rendered raised StreamlitWidgetAlreadyInstantiatedError and aborted
    the run (the second button never rendered). The data_editor widget
    states are dropped so the editors re-initialize from the new frames.
    """
    tpl = core.starter_templates()[key]
    nodes = pd.DataFrame(tpl["nodes"])
    for c in NODE_COLS:  # templates predate the Subtitle column
        if c not in nodes.columns:
            nodes[c] = ""
    edges = pd.DataFrame(tpl["edges"])
    for c in EDGE_COLS:
        if c not in edges.columns:
            edges[c] = ""
    st.session_state[P + "nodes"] = nodes[NODE_COLS]
    st.session_state[P + "edges"] = edges[EDGE_COLS]
    st.session_state[P + "title"] = tpl["name"]
    for k in (P + "nodes_ed", P + "edges_ed"):
        st.session_state.pop(k, None)


THEME_LABELS = ("Dark Obsidian", "Clean White", "Custom")
THEME_KEYS = {"Dark Obsidian": "dark", "Clean White": "light",
              "Custom": "custom"}
CUSTOM_PICKERS = [
    ("canvas_bg", "Canvas BG", "#0e1015"),
    ("panel_bg", "Panel BG", "#0e1015"),
    ("node_bg", "Node BG", "#15181f"),
    ("node_border", "Node Border", "#383e4c"),
    ("active_node_bg", "Active Node BG", "#1c2846"),
    ("active_node_border", "Active Node Border", "#5c8df6"),
    ("primary_text", "Primary Text", "#f3f4f6"),
    ("subtitle_text", "Subtitle Text", "#9ca3af"),
    ("edge_color", "Edge Color", "#6b7280"),
]
PANEL_LABELS = ("Bottom", "Top", "Left", "Right", "Hidden")


def _viewer_opts() -> dict:
    """Style/layout/info-panel options shared by preview and export."""
    direction = ("TB" if st.session_state.get(P + "dir",
                                              "Left-to-Right") == "Top-to-Bottom"
                 else "LR")
    theme_key = THEME_KEYS.get(st.session_state.get(P + "theme",
                                                    "Dark Obsidian"), "dark")
    custom = {}
    if theme_key == "custom":
        for key, _label, default in CUSTOM_PICKERS:
            custom[key] = st.session_state.get(P + "cc_" + key, default)
    title_fs = float(st.session_state.get(P + "fs_title", 13.5))
    subtitle_fs = float(st.session_state.get(P + "fs_sub", 11.5))
    return {
        "direction": direction,
        "gap_x": int(st.session_state.get(P + "gapx", core.GAP_X)),
        "gap_y": int(st.session_state.get(P + "gapy", core.GAP_Y)),
        "info_heading": st.session_state.get(P + "info_h",
                                             core.DEFAULT_INFO_HEADING),
        "info_text": st.session_state.get(P + "info_c",
                                          core.DEFAULT_INFO_TEXT),
        "theme": theme_key,
        "panel": st.session_state.get(P + "panel", "Bottom").lower(),
        "custom_colors": custom or None,
        "shell_w": int(st.session_state.get(P + "shell_w", 1100)),
        "shell_h": int(st.session_state.get(P + "shell_h", 640)),
        "title_fs": title_fs,
        "subtitle_fs": subtitle_fs,
        "edge_fs": float(st.session_state.get(P + "fs_edge", 11.0)),
        "panel_fs": float(st.session_state.get(P + "fs_panel", 13.0)),
        "hint_text": st.session_state.get(P + "hint", ""),
        "show_legend": bool(st.session_state.get(P + "legend", True)),
    }


def _node_sizes(nodes: list[dict], opts: dict) -> dict:
    """Auto-fit boxes shared by layout and viewer so both agree."""
    return core.node_boxes(nodes, opts["title_fs"], opts["subtitle_fs"])


def _render_audit_card(audit: dict) -> None:
    """Security gatekeeper card: green self-contained badge, or a detailed
    warning listing the exact lines/URLs detected."""
    if audit["passed"]:
        st.success("✅ Security Check Passed: 100% Self-Contained "
                   "(Zero External Network Calls)")
        return
    n = len(audit["findings"])
    st.error(f"⚠️ Security Check: {n} issue{'s' if n != 1 else ''} found — "
             "review or strip the flagged code before sharing this file.")
    for f in audit["findings"]:
        st.markdown(f"- **{f['kind']}** — line {f['line']}: `{f['detail']}`")


st.title("🔀 Interactive Flowchart Studio")
st.caption("Build decision trees, SOPs, and business-logic flows — preview "
           "them live, then export a standalone interactive HTML file anyone "
           "can open.")

st.text_input("Flowchart title", value="My Flowchart", key=P + "title")

tab_edit, tab_preview, tab_export, tab_ai = st.tabs(
    ["📝 Node & Edge Editor", "👁️ Live Preview", "📦 Export",
     "🎨 AI HTML Studio"])

# ========================================================== TAB 1 ===
with tab_edit:
    st.subheader("Starter templates")
    with st.container(border=True):
        t1, t2 = st.columns(2)
        for col, key in zip((t1, t2), ("report_access", "kpi_troubleshooting")):
            with col:
                tpl = core.starter_templates()[key]
                st.button(f"📥 Load: {tpl['name']}", key=P + f"tpl_{key}",
                          use_container_width=True,
                          on_click=_load_template, args=(key,))

    st.subheader("Nodes")
    with st.container(border=True):
        st.caption("Node_Type: question = decision diamond, action = step, "
                   "end = end-state.")
        nodes_df = st.data_editor(
            _nodes(), num_rows="dynamic", use_container_width=True,
            key=P + "nodes_ed",
            column_config={
                "id": st.column_config.TextColumn("Node_ID", required=True),
                "label": st.column_config.TextColumn(
                    "Label", required=True,
                    help="Tip: 'Main Title | Subtitle' auto-splits into "
                         "two-line pill text."),
                "subtitle": st.column_config.TextColumn(
                    "Subtitle",
                    help="Optional second line (italic, muted). Overrides "
                         "the '| Subtitle' part of Label when set."),
                "type": st.column_config.SelectboxColumn(
                    "Node_Type", options=list(core.NODE_TYPES), required=True),
                "desc": st.column_config.TextColumn("Detailed_Description",
                                                    width="large"),
            })
        st.session_state[P + "nodes"] = nodes_df

    st.subheader("Edges")
    with st.container(border=True):
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
    with st.container(border=True):
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
            st.subheader("📭 No nodes yet")
            st.markdown("Add rows to the **Nodes** table above first, "
                        "then connect them with edges here.")

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
    with st.container(border=True):
        st.subheader("🎛️ Viewer style & layout")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.radio("Layout direction", ("Left-to-Right", "Top-to-Bottom"),
                     horizontal=True, key=P + "dir")
            st.selectbox("Theme", THEME_LABELS, key=P + "theme")
        with c2:
            st.slider("Horizontal gap (px)", 40, 260, core.GAP_X, key=P + "gapx")
            st.selectbox("Info panel position", PANEL_LABELS, key=P + "panel",
                         help="Baked into the exported HTML (read-only "
                              "viewer has no toolbar).")
        with c3:
            st.slider("Vertical gap (px)", 16, 140, core.GAP_Y, key=P + "gapy")
            st.slider("Initial width (px)", 600, 1600, 1100, key=P + "shell_w",
                      help="SharePoint embed starting size — the shell stays "
                           "user-resizable in the browser.")
            st.slider("Initial height (px)", 400, 1000, 640, key=P + "shell_h")
        st.subheader("🔤 Font sizes")
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            st.slider("Node title (px)", 10.0, 18.0, 13.5, 0.5, key=P + "fs_title")
        with f2:
            st.slider("Node subtitle (px)", 9.0, 15.0, 11.5, 0.5, key=P + "fs_sub")
        with f3:
            st.slider("Edge label (px)", 9.0, 14.0, 11.0, 0.5, key=P + "fs_edge")
        with f4:
            st.slider("Info panel body (px)", 11.0, 16.0, 13.0, 0.5,
                      key=P + "fs_panel")
        st.caption("📐 Node pills auto-fit their text (180–380px); overlong "
                   "text wraps and the pill grows taller. CJK characters "
                   "count 1.8× ASCII width.")
        if st.session_state.get(P + "theme", "Dark Obsidian") == "Custom":
            st.caption("🎨 Custom palette")
            cols = st.columns(3)
            for i, (key, label, default) in enumerate(CUSTOM_PICKERS):
                with cols[i % 3]:
                    st.color_picker(label, default, key=P + "cc_" + key)
        st.text_input("Default Panel Title",
                      value=core.DEFAULT_INFO_HEADING, key=P + "info_h",
                      help="Bento panel header when no node is selected. The "
                           "first root node is auto-selected on load.")
        st.text_area("Default Panel Content",
                     value=core.DEFAULT_INFO_TEXT, key=P + "info_c", height=80,
                     help="Shown in the bento panel whenever the selection is "
                          "cleared.")
        st.subheader("📤 End-user export options")
        e1, e2, e3 = st.columns(3)
        with e1:
            st.checkbox("Show bottom legend bar", value=True, key=P + "legend")
        with e2:
            st.checkbox("Allow node dragging in exported HTML", value=False,
                        key=P + "allow_drag",
                        help="Off = read-only SharePoint view: nodes only "
                             "respond to clicks.")
        with e3:
            st.text_input("Viewer hint text (optional)", value="",
                          key=P + "hint",
                          help="Empty renders nothing above the canvas in "
                               "the export.")
    with st.container(border=True):
        st.caption("Click any node to highlight its path and read its bento "
                   "detail cards. Drag nodes to rearrange them. "
                   "Click the background to reset.")
        nodes = _as_records(st.session_state[P + "nodes"], NODE_COLS)
        edges = [e for e in _as_records(st.session_state[P + "edges"], EDGE_COLS)
                 if e["source"] and e["target"]]
        errors = core.validate_flow(nodes, edges)
        if errors:
            for err in errors:
                st.error("⚠️ " + err)
        elif not nodes:
            st.subheader("📭 Nothing to preview yet")
            st.markdown("1. Add **nodes** in the **📝 Node & Edge Editor** tab.\n"
                        "2. Connect them with **edges**.\n"
                        "3. The live interactive diagram appears here.")
        else:
            title = st.session_state.get(P + "title", "Flowchart")
            opts = _viewer_opts()
            sizes = _node_sizes(nodes, opts)
            html_doc = core.render_viewer_html(title, nodes, edges,
                                              sizes=sizes, **opts)
            _, sw, sh = core.layout(nodes, edges, opts["direction"],
                                    opts["gap_x"], opts["gap_y"], sizes=sizes)
            components.html(html_doc, height=min(900, sh + 300), scrolling=True)

# ========================================================== TAB 3 ===
with tab_export:
    st.subheader("Export")
    nodes = _as_records(st.session_state[P + "nodes"], NODE_COLS)
    edges = [e for e in _as_records(st.session_state[P + "edges"], EDGE_COLS)
             if e["source"] and e["target"]]
    errors = core.validate_flow(nodes, edges)
    if errors:
        with st.container(border=True):
            for err in errors:
                st.error("⚠️ Fix validation errors before exporting: " + err)
    elif not nodes:
        with st.container(border=True):
            st.subheader("📭 Nothing to export yet")
            st.markdown("1. Build your flow in the **📝 Node & Edge Editor** tab.\n"
                        "2. Fix any validation errors.\n"
                        "3. Download the **Interactive HTML**, **Mermaid**, or **SVG** here.")
    else:
        with st.container(border=True):
            title = st.session_state.get(P + "title", "Flowchart")
            stem = "".join(c if c.isalnum() else "_" for c in title).strip("_") \
                or "flowchart"
            opts = _viewer_opts()
            sizes = _node_sizes(nodes, opts)
            # Read-only end-user deliverable: no authoring toolbar, dragging
            # locked unless the author explicitly allows it.
            export_opts = dict(opts, sizes=sizes, show_toolbar=False,
                               allow_drag=bool(
                                   st.session_state.get(P + "allow_drag",
                                                        False)))
            raw_html = core.render_viewer_html(title, nodes, edges,
                                               **export_opts)
            _render_audit_card(core.audit_html_security(raw_html))
            use_csp = st.checkbox(
                "🔒 Inject Zero-Exfiltration CSP Header",
                value=True, key=P + "csp",
                help="Injects a Content-Security-Policy meta tag: blocks "
                     "outbound data leaks (connect-src 'none') and external "
                     "third-party scripts, while allowing inline "
                     "styles/scripts and local/same-origin images.")
            safe_html = core.sanitize_export(raw_html, use_csp=use_csp)
            st.caption("The .html and .aspx carry the exact same "
                       "sanitization and CSP protection.")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.download_button(
                    "🌐 Interactive HTML", safe_html,
                    f"{stem}.html", "text/html", key=P + "dl_html",
                    help="Self-contained read-only viewer for SharePoint — "
                         "no Python needed. Theme, panel position and legend "
                         "are baked in from your settings above.")
            with c2:
                st.download_button(
                    "📄 Interactive ASPX", safe_html,
                    f"{stem}.aspx", "text/html", key=P + "dl_aspx",
                    help="Byte-identical to the .html — for legacy "
                         "enterprise portals, IIS and classic server pages.")
            with c3:
                st.download_button("🧜 Mermaid (.mmd)",
                                   core.to_mermaid(nodes, edges),
                                   f"{stem}.mmd", "text/plain", key=P + "dl_mmd")
            with c4:
                st.download_button("🖼️ SVG (for PowerPoint)",
                                   core.to_svg(nodes, edges, title,
                                               opts["direction"], opts["gap_x"],
                                               opts["gap_y"],
                                               theme=opts["theme"],
                                               sizes=sizes,
                                               title_fs=opts["title_fs"],
                                               subtitle_fs=opts["subtitle_fs"],
                                               edge_fs=opts["edge_fs"]),
                                   f"{stem}.svg", "image/svg+xml",
                                   key=P + "dl_svg")
            st.caption("PowerPoint: Insert → Pictures → this SVG (ungroup to edit "
                       "shapes), or paste the Mermaid code into a Mermaid renderer.")

# ========================================================== TAB 4 ===
AI_PROMPT = """You are a front-end developer. Generate a single, self-contained HTML5 snippet (a FRAGMENT — do NOT include <html>, <head> or <body> tags) with inline CSS and vanilla JavaScript only.

Hard requirements:
- No external libraries, fonts, images, or network calls — everything inline.
- Responsive: fluid widths (max-width: 100%), no fixed pixel widths above 900px, no horizontal scrollbars.
- Clean system font stack: 'Segoe UI', -apple-system, 'Helvetica Neue', Arial, sans-serif.
- Wrap the whole snippet in one container: <div class="ai-widget">…</div>.
- All JavaScript at the end of the snippet inside ONE <script> tag; guard every DOM lookup with null checks so there are no console errors.
- Accessible: color contrast 4.5:1+, readable font sizes (14px+), visible focus states.

Now build the following. Keep it polished but compact:

<DESCRIBE WHAT YOU WANT HERE>
"""

with tab_ai:
    st.subheader("🎨 Custom AI HTML Studio — SharePoint Embed Wrapper")
    st.caption("Paste any AI-generated HTML/CSS/JS snippet, preview it live, "
               "and export a standalone `.html` file ready to upload into a "
               "SharePoint Embed web part (iframe).")

    with st.container(border=True):
        st.subheader("① Paste or upload HTML")
        up = st.file_uploader("Upload an .html file (optional)",
                              type=["html", "htm"], key=P + "ai_up")
        if up is not None and st.session_state.get(P + "ai_up_name") != up.name:
            # Seed the editor from the upload (before the text_area below is
            # instantiated, so assigning its key is legal).
            st.session_state[P + "ai_up_name"] = up.name
            try:
                st.session_state[P + "ai_code"] = up.getvalue().decode(
                    "utf-8", errors="replace")
            except Exception:
                st.session_state[P + "ai_code"] = ""
        code = st.text_area("HTML / CSS / JS snippet", height=320,
                            key=P + "ai_code",
                            placeholder="Paste your AI-generated snippet here…",
                            help="A fragment (no <html> needed) or a complete "
                                 "HTML document — both work.")

    with st.container(border=True):
        st.subheader("② Wrap & preview")
        c1, c2 = st.columns([3, 2])
        with c1:
            auto_wrap = st.checkbox(
                "Smart auto-wrap partial snippets",
                value=True, key=P + "ai_wrap",
                help="Fragments are wrapped in a clean UTF-8, responsive "
                     "HTML5 shell (no horizontal scrollbars, system fonts) "
                     "optimized for SharePoint iframes. Complete documents "
                     "are kept as-is.")
        with c2:
            wrap_title = st.text_input("Wrapper title", value="Embedded content",
                                       key=P + "ai_title")
        wrapped = (core.wrap_sharepoint_html(code, wrap_title)
                   if auto_wrap else (code or ""))
        is_full = bool(code) and code != wrapped
        if is_full:
            st.caption("ℹ️ Complete HTML document detected — kept as-is.")
        audit = core.audit_html_security(wrapped)
        use_csp = st.checkbox(
            "🔒 Inject Zero-Exfiltration CSP Header",
            value=True, key=P + "ai_csp",
            help="Injects a Content-Security-Policy meta tag: blocks "
                 "outbound data leaks (connect-src 'none') and external "
                 "third-party scripts, while allowing inline styles/scripts "
                 "and local/same-origin images on any host.")
        safe = core.sanitize_export(wrapped, use_csp=use_csp)
        _render_audit_card(audit)
        preview_h = st.slider("Preview height (px)", 300, 1200, 600,
                              key=P + "ai_h")
        if safe.strip():
            components.html(safe, height=preview_h, scrolling=True)
        else:
            st.info("Paste a snippet above to see the live preview here.")

    with st.container(border=True):
        st.subheader("③ Export")
        stem = "".join(c if c.isalnum() else "_" for c in wrap_title
                       ).strip("_") or "sharepoint_embed"
        payload = safe if wrapped.strip() else "<!-- empty -->"
        st.caption("Both files carry the exact same sanitization "
                   "(reverse-tabnabbing fix) and CSP protection.")
        c1, c2 = st.columns(2)
        with c1:
            st.download_button("⬇️ Download .html for SharePoint",
                               payload,
                               f"{stem}.html", "text/html", key=P + "ai_dl",
                               help="Upload this file to SharePoint, then point an "
                                    "Embed web part at it (or paste via iframe).")
        with c2:
            st.download_button("⬇️ Download .aspx (legacy portals / IIS)",
                               payload,
                               f"{stem}.aspx", "text/html",
                               key=P + "ai_dl_aspx",
                               help="Byte-identical to the .html — for legacy "
                                    "enterprise portals, IIS and classic "
                                    "server pages.")

    with st.expander("🤖 AI prompt helper — copy & paste to any AI"):
        st.caption("Give this prompt to ChatGPT / Claude / Copilot so the "
                   "generated code is ready to paste into ① above.")
        st.code(AI_PROMPT, language="text")

