"""App 10 — AI Prompt & Privacy Hub.

1. Pattern-based prompt builder (RTC / Chain-of-Thought / Few-Shot /
   Repo-Upgrade guardrails) across 5 categories + custom saved templates.
2. Reversible local PII & schema masker (mask -> send to LLM -> unmask).
3. Local repo context packer (code/metadata only — data files excluded).

Pure logic lives in prompt_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prompt_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="AI Prompt & Privacy Hub", page_icon="🧠", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "pp10_"

st.title("🧠 AI Prompt & Privacy Hub")
st.caption("Write high-precision prompts systematically — and sanitize "
           "company data locally before anything touches a cloud LLM.")

tab_build, tab_mask, tab_pack = st.tabs(
    ["✍️ Prompt Builder", "🕵️ Data Masker", "📦 Repo Context Packer"])

# ========================================================== TAB 1 ===
with tab_build:
    st.header("Framework prompt builder")
    with st.container(border=True):
        fw_key = st.selectbox("Framework", list(core.FRAMEWORKS.keys()),
                              format_func=lambda k: core.FRAMEWORKS[k]["name"],
                              key=P + "fw")
        cat = st.selectbox("Category", list(core.CATEGORIES.keys()), key=P + "cat")
        fw = core.FRAMEWORKS[fw_key]
        values = {}
        for name, label, ph in fw["fields"]:
            values[name] = st.text_area(label, placeholder=ph, height=90,
                                        key=P + f"f_{fw_key}_{name}")
        if st.button("✨ Build prompt", type="primary", key=P + "build"):
            st.session_state[P + "prompt"] = core.build_prompt(fw_key, cat, values)
        prompt = st.session_state.get(P + "prompt")
        if prompt:
            st.code(prompt, language="markdown")
            st.caption("Copy from the block above into your LLM.")

    st.divider()
    st.subheader("Custom templates (saved locally)")
    with st.container(border=True):
        with st.expander("➕ Save a new template"):
            tname = st.text_input("Template name", key=P + "tname")
            tbody = st.text_area("Body — use {variables} for fill-ins", height=120,
                                 key=P + "tbody")
            if st.button("💾 Save template", key=P + "tsave"):
                try:
                    core.save_custom_template(tname, tbody)
                    st.success(f"Saved '{tname}'.")
                    st.rerun()
                except ValueError as e:
                    st.error(f"⚠️ {e}")
        customs = core.load_custom_templates()
        if customs:
            sel = st.selectbox("Template", list(customs.keys()), key=P + "tsel")
            body = customs[sel]
            var_vals = {}
            for v in core.detect_vars(body):
                var_vals[v] = st.text_input(f"{{{v}}}", key=P + f"cv_{sel}_{v}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✨ Fill template", key=P + "tfill"):
                    filled = body
                    for v, val in var_vals.items():
                        filled = filled.replace("{" + v + "}", val)
                    st.session_state[P + "custom_out"] = filled
            with c2:
                if st.button("🗑️ Delete template", key=P + "tdel"):
                    core.delete_custom_template(sel)
                    st.rerun()
            out = st.session_state.get(P + "custom_out")
            if out:
                st.code(out, language="markdown")
        else:
            st.subheader("📭 No custom templates yet")
            st.markdown("1. Open the **➕ Save a new template** expander above.\n"
                        "2. Give it a name and a body with `{variables}` for fill-ins.\n"
                        "3. Save it — fill and reuse it any time, all stored locally.")

# ========================================================== TAB 2 ===
with tab_mask:
    st.header("Reversible data masker")
    st.caption("Mask sensitive names before sending to a cloud LLM; restore "
               "them when the answer comes back. The mapping dictionary is "
               "saved locally and never leaves this machine.")
    mode = st.radio("Mode", ("Mask", "Unmask"), horizontal=True, key=P + "mode")

    if mode == "Mask":
        with st.container(border=True):
            raw = st.text_area("Paste raw text / SQL / DAX / CSV snippet",
                               height=160, key=P + "raw",
                               placeholder="Contact Amy Chan (amy.chan@company.com) "
                                           "about Store TST-01 sales…")
            c1, c2, c3 = st.columns(3)
            with c1:
                staff = st.text_area("Staff names (one per line)", height=100,
                                     key=P + "staff", placeholder="Amy Chan")
            with c2:
                stores = st.text_area("Store names / codes (one per line)",
                                      height=100, key=P + "stores",
                                      placeholder="Store TST-01")
            with c3:
                metrics = st.text_area("Sensitive metric names (one per line)",
                                       height=100, key=P + "metrics",
                                       placeholder="Net Profit Margin")
            if st.button("🕵️ Mask", type="primary", key=P + "mask_go"):
                masked, mapping = core.mask_text(
                    raw,
                    [s for s in staff.splitlines() if s.strip()],
                    [s for s in stores.splitlines() if s.strip()],
                    [s for s in metrics.splitlines() if s.strip()])
                st.session_state[P + "masked"] = (masked, mapping)
                core.save_mapping(mapping)
        res = st.session_state.get(P + "masked")
        if res:
            masked, mapping = res
            with st.container(border=True):
                st.subheader("Masked output (safe to send)")
                st.code(masked, language="text")
                st.subheader("Mapping dictionary (stored locally)")
                st.json(mapping)
                st.caption("Mapping auto-saved to storage/mask_map.json — "
                           "the Unmask tab reads it back. The file holds the "
                           "original names in plaintext on this machine only.")
                if st.button("🧹 Clear Local Mask Dictionary (mask_map.json)",
                             key=P + "clear_map",
                             help="Permanently deletes the local {token: "
                                  "original} mapping file."):
                    if core.clear_mapping():
                        st.success("Local mask dictionary deleted.")
                    else:
                        st.info("No local mask dictionary file exists.")
                    st.rerun()
    else:
        with st.container(border=True):
            ai_out = st.text_area("Paste the AI's response / code", height=160,
                                  key=P + "ai_out")
            mapping = core.load_mapping()
            if not mapping:
                st.subheader("📭 No mapping saved yet")
                st.markdown("1. Switch to the **Mask** tab and mask a snippet first.\n"
                            "2. The mapping is saved locally on this machine.\n"
                            "3. Come back here to restore the AI's answer to real names.")
            elif st.button("♻️ Restore original names", type="primary",
                           key=P + "unmask_go"):
                st.session_state[P + "restored"] = core.unmask_text(ai_out, mapping)
            restored = st.session_state.get(P + "restored")
            if restored:
                st.subheader("Restored output")
                st.code(restored, language="text")

# ========================================================== TAB 3 ===
with tab_pack:
    st.header("Repo context packer")
    st.caption("Bundles .py / .tmdl / .sql / .m / .md files into one Markdown "
               "block for LLM context. Data files (.csv, .xlsx, .db, "
               ".parquet) are strictly excluded.")
    with st.container(border=True):
        root = st.text_input("Local folder path", key=P + "root",
                             placeholder="/path/to/repo")
        if st.button("📦 Pack context", type="primary", key=P + "pack_go"):
            try:
                md, stats = core.pack_repo(root)
                st.session_state[P + "pack"] = (md, stats)
            except ValueError as e:
                st.error(f"⚠️ {e}")
    res = st.session_state.get(P + "pack")
    if res:
        md, stats = res
        with st.container(border=True):
            m1, m2, m3 = st.columns(3)
            m1.metric("Files packed", stats["files_packed"])
            m2.metric("Characters", f"{stats['chars']:,}")
            m3.metric("Data files excluded", stats["data_files_excluded"])
            if stats["files_truncated"]:
                st.warning(f"{stats['files_truncated']} file(s) truncated by size caps.")
            with st.expander("Preview (first 3,000 chars)"):
                st.code(md[:3000], language="markdown")
            st.download_button("⬇️ Download context.md", md.encode("utf-8"),
                               "repo_context.md", "text/markdown",
                               key=P + "pack_dl")
