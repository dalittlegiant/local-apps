"""Dav Data Studio — unified launcher.

Shell for the monorepo's local productivity OS. `st.navigation` with five
pillars; every tool is a self-contained script:

- suite pages live in `pages/` (no `st.set_page_config` — owned here),
- standalone suite apps live in `../<app>/app.py` (same rule; each app's
  `app.py` bootstraps its own directory onto `sys.path` so local imports
  work both standalone and through this launcher).

Run with:  streamlit run launcher.py
Requires:   streamlit>=1.36  (for st.navigation / st.Page)
"""

import streamlit as st

st.set_page_config(
    page_title="Dav Data Studio",
    page_icon="🧰",
    layout="wide",
)

st.markdown(
    """
<style>
/* ---------- Global suite polish ---------- */
.block-container {
    padding-top: 1.8rem !important;
}

/* ---------- Dav Data Studio sidebar theme ---------- */
section[data-testid="stSidebar"] {
    background: #FAFAFC;
}
/* Per-pillar accent colors (order matches the section dict below) */
ul[data-testid="stSidebarNavItems"] > div:nth-of-type(1) {
    --acc: #2563EB; --acc-soft: rgba(37, 99, 235, 0.10);
}
ul[data-testid="stSidebarNavItems"] > div:nth-of-type(2) {
    --acc: #059669; --acc-soft: rgba(5, 150, 105, 0.10);
}
ul[data-testid="stSidebarNavItems"] > div:nth-of-type(3) {
    --acc: #9333EA; --acc-soft: rgba(147, 51, 234, 0.10);
}
ul[data-testid="stSidebarNavItems"] > div:nth-of-type(4) {
    --acc: #EA580C; --acc-soft: rgba(234, 88, 12, 0.10);
}
ul[data-testid="stSidebarNavItems"] > div:nth-of-type(5) {
    --acc: #DB2777; --acc-soft: rgba(219, 39, 119, 0.10);
}
/* Pillar headers: small-caps, muted — emojis live here only */
header[data-testid="stNavSectionHeader"] p {
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
    color: #8A8A93 !important;
    font-weight: 700 !important;
}
/* Sub-items: colored dot + transparent accent underline */
a[data-testid="stSidebarNavLink"] {
    border-radius: 10px !important;
    margin-top: 2px !important;
    margin-bottom: 2px !important;
    border-bottom: 2px solid transparent !important;
}
a[data-testid="stSidebarNavLink"]::before {
    content: "" !important;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--acc, #5B5BF0);
    flex: none;
    margin-right: 2px;
}
/* Hover: soft accent tint + accent underline */
a[data-testid="stSidebarNavLink"]:hover:not([aria-current="page"]) {
    background: var(--acc-soft, rgba(91, 91, 240, 0.08)) !important;
    border-bottom-color: var(--acc, #5B5BF0) !important;
}
/* Active: accent tint + solid accent underline, bold text */
a[data-testid="stSidebarNavLink"][aria-current="page"] {
    background: var(--acc-soft, rgba(91, 91, 240, 0.12)) !important;
    border-bottom: 2px solid var(--acc, #5B5BF0) !important;
}
a[data-testid="stSidebarNavLink"][aria-current="page"] p {
    font-weight: 700 !important;
}
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.caption("🧰 **Dav Data Studio** — local productivity OS")
    st.caption("Everything runs on this machine. Nothing is sent anywhere.")

pg = st.navigation(
    {
        "📊 BI & Data Engineering": [
            st.Page("pages/metadata_dax_editor.py",
                    title="Metadata & DAX Editor",
                    url_path="metadata-dax-editor"),
            st.Page("../data-diff-duckdb-sandbox/app.py",
                    title="DuckDB SQL & Diff Sandbox",
                    url_path="sql-sandbox-diff"),
            st.Page("../messy-excel-sanitizer/app.py",
                    title="Messy Excel Sanitizer",
                    url_path="excel-sanitizer"),
            st.Page("../data-quality-watchdog/app.py",
                    title="Data Quality Watchdog",
                    url_path="data-quality-watchdog"),
            st.Page("pages/workspace_manager.py",
                    title="Workspace Data Manager",
                    url_path="workspace-data-manager"),
        ],
        "🛡️ Governance & Security": [
            st.Page("pages/security_command_center.py",
                    title="Security Command Center",
                    url_path="security-command-center"),
            st.Page("../power-apps-alm-masking/app.py",
                    title="Power Apps ALM & Masking",
                    url_path="power-apps-alm-masking"),
        ],
        "🎨 Design & Visual Studio": [
            st.Page("pages/theme_ui_studio.py",
                    title="Power BI Theme & UI Studio",
                    url_path="theme-ui-studio"),
            st.Page("../auto-ppt-playbook-builder/app.py",
                    title="Auto-PPT Playbook Builder",
                    url_path="ppt-playbook-builder"),
            st.Page("../interactive-flowchart-studio/app.py",
                    title="Interactive Flowchart Studio",
                    url_path="flowchart-studio"),
            st.Page("../mobile-stlite-sandbox-builder/app.py",
                    title="Stlite Sandbox Builder",
                    url_path="stlite-sandbox-builder"),
        ],
        "🤝 Project, Meeting & Comms": [
            st.Page("../bi-requirement-meeting-hub/app.py",
                    title="BI Requirement & Meeting Hub",
                    url_path="meeting-hub"),
            st.Page("../office-comms-pdf-toolkit/app.py",
                    title="Corporate Comms & PDF Toolkit",
                    url_path="comms-pdf-toolkit"),
        ],
        "🧠 AI, Study & Knowledge": [
            st.Page("../ai-prompt-privacy-hub/app.py",
                    title="AI Prompt & Privacy Hub",
                    url_path="prompt-privacy-hub"),
            st.Page("../knowledge-snippet-vault/app.py",
                    title="Knowledge & Snippet Vault",
                    url_path="snippet-vault"),
        ],
    }
)
pg.run()
