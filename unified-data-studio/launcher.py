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
/* ---------- Dav Data Studio sidebar theme ---------- */
section[data-testid="stSidebar"] {
    background: #FAFAFC;
}
/* Pillar headers: small-caps, muted — like a modern app menu */
header[data-testid="stNavSectionHeader"] p {
    font-size: 11px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.12em !important;
    color: #8A8A93 !important;
    font-weight: 700 !important;
}
/* Nav items: pill rows */
a[data-testid="stSidebarNavLink"] {
    border-radius: 999px !important;
    margin-top: 2px !important;
    margin-bottom: 2px !important;
}
/* Active page: indigo pill, white text */
a[data-testid="stSidebarNavLink"][aria-current="page"] {
    background: linear-gradient(135deg, #5B5BF0 0%, #7C6CF8 100%) !important;
    box-shadow: 0 4px 14px rgba(91, 91, 240, 0.35) !important;
}
a[data-testid="stSidebarNavLink"][aria-current="page"] p {
    color: #FFFFFF !important;
    font-weight: 700 !important;
}
/* Hover: soft indigo tint */
a[data-testid="stSidebarNavLink"]:hover:not([aria-current="page"]) {
    background: rgba(91, 91, 240, 0.08) !important;
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
                    title="Metadata & DAX Editor", icon="📊",
                    url_path="metadata-dax-editor"),
            st.Page("../data-diff-duckdb-sandbox/app.py",
                    title="DuckDB SQL & Diff Sandbox", icon="🦆",
                    url_path="sql-sandbox-diff"),
            st.Page("../messy-excel-sanitizer/app.py",
                    title="Messy Excel Sanitizer", icon="🧹",
                    url_path="excel-sanitizer"),
            st.Page("../data-quality-watchdog/app.py",
                    title="Data Quality Watchdog", icon="🐶",
                    url_path="data-quality-watchdog"),
        ],
        "🛡️ Governance & Security": [
            st.Page("pages/security_command_center.py",
                    title="Security Command Center", icon="🛡️",
                    url_path="security-command-center"),
        ],
        "🎨 Design & Visual Studio": [
            st.Page("pages/theme_ui_studio.py",
                    title="Power BI Theme & UI Studio", icon="🎨",
                    url_path="theme-ui-studio"),
            st.Page("../auto-ppt-playbook-builder/app.py",
                    title="Auto-PPT Playbook Builder", icon="📽️",
                    url_path="ppt-playbook-builder"),
            st.Page("../interactive-flowchart-studio/app.py",
                    title="Interactive Flowchart Studio", icon="🔀",
                    url_path="flowchart-studio"),
        ],
        "🤝 Project, Meeting & Comms": [
            st.Page("../bi-requirement-meeting-hub/app.py",
                    title="BI Requirement & Meeting Hub", icon="🤝",
                    url_path="meeting-hub"),
            st.Page("../office-comms-pdf-toolkit/app.py",
                    title="Corporate Comms & PDF Toolkit", icon="📄",
                    url_path="comms-pdf-toolkit"),
        ],
        "🧠 AI, Study & Knowledge": [
            st.Page("../ai-prompt-privacy-hub/app.py",
                    title="AI Prompt & Privacy Hub", icon="🧠",
                    url_path="prompt-privacy-hub"),
            st.Page("../knowledge-snippet-vault/app.py",
                    title="Knowledge & Snippet Vault", icon="📚",
                    url_path="snippet-vault"),
        ],
    }
)
pg.run()
