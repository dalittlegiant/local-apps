"""App 13 — Stlite Sandbox Builder.

Pick any standalone app.py in this repo and wrap it into a single,
self-contained WebAssembly .html file (stlite + Pyodide via CDN) that runs
in a desktop or mobile browser with no Python install.

Pure logic lives in stlite_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stlite_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="Stlite Sandbox Builder",
                       page_icon="📱", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "sl13_"
REPO_ROOT = Path(__file__).resolve().parent.parent

st.title("📱 Stlite Sandbox Builder")
st.caption("Export any local app as a single WebAssembly `.html` file — "
           "send it to your iPhone and run it in Safari, no Python needed.")

with st.container(border=True):
    st.subheader("⚠️ Before you export")
    st.markdown(core.DISCLAIMER)

apps = core.scan_apps(REPO_ROOT)
if not apps:
    st.error("No standalone `app.py` tools found in the repo.")
    st.stop()

with st.container(border=True):
    st.subheader("① Pick an app")
    labels = [a["label"] for a in apps]
    sel = st.selectbox("App", labels, key=P + "sel",
                       help="Standalone app.py tools in this repo. "
                            "Suite pages are excluded (they need the lib/ package).")
    app = apps[labels.index(sel)]
    detected_reqs = core.read_requirements(app["path"])

with st.container(border=True):
    st.subheader("② Bundle contents")
    files = core.bundle_files(app)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Python modules** (bundled into the HTML)")
        for name in files:
            tag = " ← entry point" if name == core.ENTRY_NAME else ""
            st.markdown(f"- `{name}`{tag}")
    with c2:
        st.markdown("**Packages** (installed via micropip in the browser)")
        if detected_reqs:
            for r in detected_reqs:
                st.markdown(f"- `{r}`")
        else:
            st.markdown("_None detected — stdlib only._")
    extra = st.text_input(
        "Extra packages (comma-separated, optional)",
        placeholder="matplotlib, scikit-learn",
        key=P + "extra",
        help="Appended to the detected list. Only packages with Pyodide "
             "wheels will install.")
    title = st.text_input("HTML page title", value=app["dir"].replace("-", " ").title(),
                          key=P + "title")

with st.container(border=True):
    st.subheader("③ Generate")
    if st.button("⚙️ Build sandbox HTML", type="primary", key=P + "build"):
        reqs = detected_reqs + [e.strip() for e in extra.split(",") if e.strip()]
        reqs = list(dict.fromkeys(reqs))
        try:
            html = core.build_html(title.strip() or app["dir"], files, reqs)
        except Exception as e:
            st.error(f"⚠️ Could not build the HTML: {e}")
            st.stop()
        st.session_state[P + "html"] = html
        st.session_state[P + "fname"] = f"{app['dir']}-stlite.html"
        st.success(f"Built `{st.session_state[P + 'fname']}` "
                   f"({len(html) / 1024:.0f} KB of HTML + CDN runtime).")

    html = st.session_state.get(P + "html")
    if html:
        st.download_button("⬇️ Download sandbox_app.html", html,
                           st.session_state.get(P + "fname", "sandbox_app.html"),
                           "text/html", key=P + "dl")
        with st.expander("📲 Run it on your iPhone"):
            st.markdown(
                "1. **Download** the HTML above and save it to the **Files** "
                "app (or AirDrop it to your iPhone).\n"
                "2. Open it in **Safari** with an internet connection the "
                "first time (it fetches the stlite runtime + packages once, "
                "then the browser caches them).\n"
                "3. Use **Share → Add to Home Screen** for an app-like icon.\n"
                "4. Inside the exported app, always use its **“Upload File”** "
                "toggle — local-path reading cannot work in the browser "
                "sandbox.")
