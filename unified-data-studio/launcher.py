"""Dav Data Studio — unified launcher.

Shell for the monorepo's local productivity & governance suite.
`st.navigation` with sections; every tool is a self-contained script:

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

with st.sidebar:
    st.caption("🧰 **Dav Data Studio** — local productivity & governance suite")
    st.caption("Everything runs on this machine. Nothing is sent anywhere.")

pg = st.navigation(
    {
        "📊 BI & Data Engineering": [
            st.Page(
                "pages/metadata_dax_editor.py",
                title="PBIP Metadata & DAX Editor",
                icon="📊",
                url_path="metadata-dax-editor",
            ),
            st.Page(
                "../data-diff-duckdb-sandbox/app.py",
                title="SQL Sandbox & Diff Engine",
                icon="🦆",
                url_path="sql-sandbox-diff",
            ),
            st.Page(
                "../messy-excel-sanitizer/app.py",
                title="Messy Excel Sanitizer",
                icon="🧹",
                url_path="excel-sanitizer",
            ),
        ],
        "🛡️ Governance & Security": [
            st.Page(
                "pages/security_command_center.py",
                title="Security Command Center",
                icon="🛡️",
                url_path="security-command-center",
            ),
        ],
        "🎨 Design & Office Productivity": [
            st.Page(
                "pages/theme_ui_studio.py",
                title="Theme & UI Studio",
                icon="🎨",
                url_path="theme-ui-studio",
            ),
            st.Page(
                "../auto-ppt-playbook-builder/app.py",
                title="PPT Playbook Builder",
                icon="📽️",
                url_path="ppt-playbook-builder",
            ),
            st.Page(
                "../office-comms-pdf-toolkit/app.py",
                title="Comms & PDF Toolkit",
                icon="📄",
                url_path="comms-pdf-toolkit",
            ),
        ],
    }
)
pg.run()
