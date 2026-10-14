"""Dav Data Studio — unified launcher.

Shell for the monorepo's Streamlit multi-page app. Each tool lives in
``pages/`` as a self-contained script; shared pure logic lives in ``lib/``.

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

pages = [
    st.Page(
        "pages/metadata_dax_editor.py",
        title="PBIP Metadata & DAX Editor",
        icon="📊",
    ),
    st.Page(
        "pages/security_command_center.py",
        title="Security Command Center",
        icon="🛡️",
    ),
    st.Page(
        "pages/theme_ui_studio.py",
        title="Theme & UI Studio",
        icon="🎨",
    ),
]

pg = st.navigation(pages)
pg.run()
