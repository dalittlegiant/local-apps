"""App 11 — Knowledge & Snippet Vault.

1. Multi-language code vault (DAX / M / Python / R / SQL): save, edit, tag,
   search, syntax-highlighted display, copy blocks.
2. Study & methodology notebook: Markdown notes with full LaTeX math
   rendering.
3. Instant search (full-text + multi-tag) and one-click Markdown
   cheat-sheet export.

Pure logic lives in vault_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="Knowledge & Snippet Vault", page_icon="📚", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "kv11_"
FENCE = {"DAX": "dax", "Power Query (M)": "powerquery", "Python": "python",
         "R": "r", "SQL": "sql"}


def _con():
    if P + "con" not in st.session_state:
        st.session_state[P + "con"] = core.connect()
    return st.session_state[P + "con"]


st.title("📚 Knowledge & Snippet Vault")
st.caption("Your local SQLite-backed library for reusable code and study "
           "notes — LaTeX included.")

tab_snip, tab_notes, tab_search, tab_export = st.tabs(
    ["💻 Code Snippets", "📝 Study Notes", "🔍 Search", "📦 Export"])

# ========================================================== TAB 1 ===
with tab_snip:
    st.header("Code vault")
    with st.expander("➕ Save a snippet"):
        s_title = st.text_input("Title", key=P + "st")
        s_lang = st.selectbox("Language", core.LANGUAGES, key=P + "sl")
        s_code = st.text_area("Code", height=160, key=P + "sc")
        s_ctx = st.text_area("Usage context / notes", key=P + "sx")
        s_tags = st.text_input("Tags (comma-separated)", key=P + "sg",
                               placeholder="dax, time-intelligence")
        if st.button("💾 Save snippet", type="primary", key=P + "ssave"):
            try:
                core.add_snippet(_con(), s_title, s_lang, s_code, s_ctx, s_tags)
                st.success("Snippet saved.")
                st.rerun()
            except ValueError as e:
                st.error(f"⚠️ {e}")

    with st.container(border=True):
        f1, f2 = st.columns(2)
        with f1:
            fl = st.selectbox("Language", ["(all)"] + list(core.LANGUAGES),
                              key=P + "fl")
        with f2:
            ft = st.selectbox("Tag", ["(all)"] + core.all_tags(_con()), key=P + "ft")
    res = core.search(_con(), language=None if fl == "(all)" else fl,
                      tags=[] if ft == "(all)" else [ft])
    st.caption(f"{len(res['snippets'])} snippet(s).")
    if not res["snippets"]:
        with st.container(border=True):
            st.subheader("📭 No snippets yet")
            st.markdown("1. Open the **➕ Save a snippet** expander above.\n"
                        "2. Paste your code, pick a language, add tags.\n"
                        "3. Search and reuse it from here any time.")
    for s in res["snippets"]:
        with st.expander(f"[{s['language']}] {s['title']}"):
            if s["tags"]:
                st.caption(f"🏷️ {s['tags']}")
            if s["context_notes"]:
                st.markdown(s["context_notes"])
            st.code(s["code"], language=FENCE[s["language"]])
            st.caption("Copy from the block above.")
            e1, e2 = st.columns([3, 1])
            with e1:
                if st.button("✏️ Edit", key=P + f"se_{s['id']}"):
                    st.session_state[P + "edit_snip"] = s["id"]
            with e2:
                if st.button("🗑️", key=P + f"sd_{s['id']}"):
                    core.delete_snippet(_con(), s["id"])
                    st.rerun()
            if st.session_state.get(P + "edit_snip") == s["id"]:
                et = st.text_input("Title", value=s["title"],
                                   key=P + f"et_{s['id']}")
                el = st.selectbox("Language", core.LANGUAGES,
                                   index=core.LANGUAGES.index(s["language"]),
                                   key=P + f"el_{s['id']}")
                ec = st.text_area("Code", value=s["code"], height=160,
                                  key=P + f"ec_{s['id']}")
                ex = st.text_area("Context", value=s["context_notes"] or "",
                                  key=P + f"ex_{s['id']}")
                eg = st.text_input("Tags", value=s["tags"] or "",
                                   key=P + f"eg_{s['id']}")
                if st.button("💾 Save", key=P + f"es_{s['id']}"):
                    core.update_snippet(_con(), s["id"],
                                        {"title": et, "language": el,
                                         "code": ec, "context_notes": ex,
                                         "tags": eg})
                    st.session_state.pop(P + "edit_snip")
                    st.rerun()

# ========================================================== TAB 2 ===
with tab_notes:
    st.header("Study & methodology notebook")
    st.caption("Markdown with LaTeX: `$E=mc^2$` inline, `$$…$$` for display "
               "math.")
    with st.expander("➕ New note"):
        n_title = st.text_input("Title", key=P + "nt")
        n_body = st.text_area("Markdown body (LaTeX supported)", height=200,
                              key=P + "nb",
                              placeholder="# Bayes' rule\n\n$$P(A|B) = "
                                          "\\frac{P(B|A)P(A)}{P(B)}$$")
        n_tags = st.text_input("Tags (comma-separated)", key=P + "ng")
        if st.button("💾 Save note", type="primary", key=P + "nsave"):
            try:
                core.add_note(_con(), n_title, n_body, n_tags)
                st.success("Note saved.")
                st.rerun()
            except ValueError as e:
                st.error(f"⚠️ {e}")

    res = core.search(_con())
    st.caption(f"{len(res['notes'])} note(s).")
    if not res["notes"]:
        with st.container(border=True):
            st.subheader("📭 No notes yet")
            st.markdown("1. Open the **➕ New note** expander above.\n"
                        "2. Write Markdown — LaTeX math works (`$E=mc^2$`, `$$…$$`).\n"
                        "3. Tag it and export a cheat sheet from the **📦 Export** tab.")
    for n in res["notes"]:
        with st.expander(n["title"]):
            if n["tags"]:
                st.caption(f"🏷️ {n['tags']}")
            st.markdown(n["body_md"])
            st.divider()
            e1, e2 = st.columns([3, 1])
            with e1:
                if st.button("✏️ Edit", key=P + f"ne_{n['id']}"):
                    st.session_state[P + "edit_note"] = n["id"]
            with e2:
                if st.button("🗑️", key=P + f"nd_{n['id']}"):
                    core.delete_note(_con(), n["id"])
                    st.rerun()
            if st.session_state.get(P + "edit_note") == n["id"]:
                et = st.text_input("Title", value=n["title"],
                                   key=P + f"net_{n['id']}")
                eb = st.text_area("Body", value=n["body_md"], height=200,
                                  key=P + f"neb_{n['id']}")
                eg = st.text_input("Tags", value=n["tags"] or "",
                                   key=P + f"neg_{n['id']}")
                if st.button("💾 Save", key=P + f"nes_{n['id']}"):
                    core.update_note(_con(), n["id"],
                                     {"title": et, "body_md": eb, "tags": eg})
                    st.session_state.pop(P + "edit_note")
                    st.rerun()

# ========================================================== TAB 3 ===
with tab_search:
    st.header("Instant search")
    with st.container(border=True):
        q = st.text_input("🔍 Full-text query", key=P + "q")
        tsel = st.multiselect("Tags", core.all_tags(_con()), key=P + "tsel")
    if q.strip() or tsel:
        res = core.search(_con(), query=q, tags=tsel)
        st.subheader(f"Snippets ({len(res['snippets'])})")
        for s in res["snippets"]:
            with st.expander(f"[{s['language']}] {s['title']}"):
                st.code(s["code"], language=FENCE[s["language"]])
        st.subheader(f"Notes ({len(res['notes'])})")
        for n in res["notes"]:
            with st.expander(n["title"]):
                st.markdown(n["body_md"][:800]
                            + ("…" if len(n["body_md"]) > 800 else ""))
    else:
        with st.container(border=True):
            st.subheader("🔍 Start a search")
            st.markdown("1. Type a **full-text query** above, or\n"
                        "2. Pick one or more **tags**.\n"
                        "3. Matching snippets and notes appear here.")

# ========================================================== TAB 4 ===
with tab_export:
    st.header("Cheat-sheet export")
    res = core.search(_con())
    with st.container(border=True):
        pick_s = st.multiselect(
            "Snippets",
            [s["id"] for s in res["snippets"]],
            format_func=lambda i: next(
                s["title"] + f" [{s['language']}]" for s in res["snippets"]
                if s["id"] == i),
            key=P + "ps")
        pick_n = st.multiselect(
            "Notes",
            [n["id"] for n in res["notes"]],
            format_func=lambda i: next(
                n["title"] for n in res["notes"] if n["id"] == i),
            key=P + "pn")
    if not res["snippets"] and not res["notes"]:
        with st.container(border=True):
            st.subheader("📭 Nothing to export yet")
            st.markdown("Save some **💻 Code Snippets** or **📝 Study Notes** first, "
                        "then pick them above to build a cheat sheet.")
    elif (pick_s or pick_n) and st.button("📦 Build cheat sheet",
                                          type="primary", key=P + "xgo"):
        md = core.export_cheatsheet(
            [s for s in res["snippets"] if s["id"] in pick_s],
            [n for n in res["notes"] if n["id"] in pick_n])
        st.session_state[P + "sheet"] = md
    sheet = st.session_state.get(P + "sheet")
    if sheet:
        with st.container(border=True):
            with st.expander("Preview"):
                st.markdown(sheet[:4000])
            st.download_button("⬇️ Download cheat_sheet.md",
                               sheet.encode("utf-8"), "cheat_sheet.md",
                               "text/markdown", key=P + "xdl")
