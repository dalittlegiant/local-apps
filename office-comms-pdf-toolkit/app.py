"""App 7 — Office Comms & PDF Toolkit.

1. Corporate Comms Studio — templates (launch, training, schedule change,
   delay notice, audit reminder) -> email + Teams drafts + checklist.
2. Offline PDF Toolkit — merge, split/extract pages, text watermark, table
   extraction to Excel (multi-strategy: pdfplumber grid/text → PyMuPDF →
   pypdf layout fallback, with a mode toggle).
3. Screenshot Beautifier — trim, padding, rounded corners, drop shadow
   (Pillow), batch + zip download.

Pure logic lives in toolkit_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import toolkit_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="Office Comms & PDF Toolkit",
                       page_icon="📄", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "pdf7_"

st.title("📄 Office Comms & PDF Toolkit")
st.caption("Routine communications, offline PDF surgery, and "
           "presentation-ready screenshots — 100% local.")

tab_comms, tab_pdf, tab_beauty = st.tabs([
    "💬 Comms Studio", "📑 PDF Toolkit", "✨ Screenshot Beautifier",
])

# ========================================================== TAB 1 ===
with tab_comms:
    st.header("Corporate communications studio")
    with st.container(border=True):
        st.subheader("① Scenario & details")
        tpl_key = st.selectbox(
            "Scenario",
            list(core.TEMPLATES.keys()),
            format_func=lambda k: f"{core.TEMPLATES[k]['icon']} "
                                  f"{core.TEMPLATES[k]['title']}",
            key=P + "tpl")
        tpl = core.TEMPLATES[tpl_key]

        values = {}
        for name, label, default in tpl["variables"]:
            values[name] = st.text_input(label, value=default,
                                         key=P + f"var_{tpl_key}_{name}")

        if st.button("✨ Generate drafts", type="primary", key=P + "gen"):
            st.session_state[P + "draft"] = core.render_comms(tpl_key, values)

    draft = st.session_state.get(P + "draft")
    if draft:
        with st.container(border=True):
            st.subheader("② Drafts")
            st.subheader("📧 Email draft")
            st.text_input("Subject", value=draft["subject"], key=P + "subject")
            st.code(draft["email"], language="text")
            st.subheader("💬 Teams message")
            st.code(draft["teams"], language="text")
            st.caption("Copy from the code blocks above — formatting preserved.")

            st.subheader("✅ Pre-launch checklist")
            done = 0
            for i, item in enumerate(draft["checklist"]):
                if st.checkbox(item, key=P + f"chk_{tpl_key}_{i}"):
                    done += 1
            st.progress(done / len(draft["checklist"]))
            st.caption(f"{done}/{len(draft['checklist'])} done.")

# ========================================================== TAB 2 ===
with tab_pdf:
    st.header("Offline PDF toolkit")

    with st.container(border=True):
        st.subheader("🔗 Merge PDFs")
        m_ups = st.file_uploader("PDFs in merge order", type=["pdf"],
                                 accept_multiple_files=True, key=P + "merge")
        if m_ups:
            if st.button("Merge", type="primary", key=P + "merge_go"):
                try:
                    out = core.merge_pdfs([u.getvalue() for u in m_ups])
                    st.success(f"Merged {len(m_ups)} file(s), "
                               f"{core.pdf_page_count(out)} pages.")
                    st.download_button("⬇️ Download merged.pdf", out, "merged.pdf",
                                       "application/pdf", key=P + "merge_dl")
                except ValueError as e:
                    st.error(f"⚠️ {e}")
        else:
            st.subheader("Get started")
            st.markdown(
                "1. Upload **two or more PDFs** in merge order.\n"
                "2. Click **Merge** to combine them into one file."
            )

        st.divider()
        st.subheader("✂️ Split / extract pages")
        s_up = st.file_uploader("PDF", type=["pdf"], key=P + "split")
        if s_up:
            try:
                data = s_up.getvalue()
                n = core.pdf_page_count(data)
            except Exception as e:
                st.error(f"⚠️ Could not read that PDF: {e}")
                n = 0
            if n:
                st.caption(f"{n} page(s).")
                spec = st.text_input("Pages (e.g. 1-3,5)", value=f"1-{min(n, 3)}",
                                     key=P + "range")
                if st.button("Extract", type="primary", key=P + "split_go"):
                    try:
                        pages = core.parse_page_range(spec, n)
                        out = core.split_pdf(data, pages)
                        st.success(f"Extracted {len(pages)} page(s).")
                        st.download_button("⬇️ Download extracted.pdf", out,
                                           "extracted.pdf", "application/pdf",
                                           key=P + "split_dl")
                    except ValueError as e:
                        st.error(f"⚠️ {e}")
        else:
            st.subheader("Get started")
            st.markdown(
                "1. Upload a **PDF**.\n"
                "2. Enter a page range like `1-3,5`.\n"
                "3. Click **Extract** to download those pages."
            )

    with st.container(border=True):
        st.subheader("💧 Text watermark")
        w_up = st.file_uploader("PDF", type=["pdf"], key=P + "wm")
        if w_up:
            w1, w2, w3 = st.columns(3)
            with w1:
                wtext = st.text_input("Watermark text", value="CONFIDENTIAL",
                                      key=P + "wtext")
            with w2:
                wop = st.slider("Opacity %", 5, 80, 25, key=P + "wop")
            with w3:
                wsz = st.slider("Font size", 24, 96, 48, key=P + "wsize")
            if st.button("Apply watermark", type="primary", key=P + "wm_go"):
                try:
                    out = core.add_watermark(w_up.getvalue(), wtext,
                                             opacity=wop / 100, font_size=wsz)
                    st.success("Watermark applied to every page.")
                    st.download_button("⬇️ Download watermarked.pdf", out,
                                       "watermarked.pdf", "application/pdf",
                                       key=P + "wm_dl")
                except ValueError as e:
                    st.error(f"⚠️ {e}")
        else:
            st.subheader("Get started")
            st.markdown(
                "1. Upload a **PDF**.\n"
                "2. Set the watermark text, opacity, and size.\n"
                "3. Click **Apply watermark**."
            )

        st.divider()
        st.subheader("📊 Extract tables to Excel")
        mode_label = st.radio(
            "Extraction mode",
            ["Auto", "Grid/Bordered", "Borderless/Text-Aligned"],
            horizontal=True, key=P + "tab_mode",
            help="Auto tries bordered-grid detection first, then text-aligned, "
                 "then PyMuPDF, then a text-layout fallback — per page.")
        mode = {"Auto": "auto", "Grid/Bordered": "grid",
                "Borderless/Text-Aligned": "borderless"}[mode_label]
        t_up = st.file_uploader("PDF", type=["pdf"], key=P + "tables")
        if t_up:
            if st.button("Extract tables", type="primary", key=P + "tab_go"):
                try:
                    tables = core.extract_tables(t_up.getvalue(), mode=mode)
                except Exception as e:
                    st.error(f"⚠️ Could not read that PDF: {e}")
                else:
                    if not tables:
                        st.warning("No tables detected on any page "
                                   f"(mode: {mode_label}).")
                    else:
                        st.success(f"Found {len(tables)} table(s).")
                        for pi, ti, df, strat in tables[:6]:
                            st.markdown(
                                f"**Page {pi}, table {ti}** "
                                f"({len(df)} rows × {len(df.columns)} cols) — "
                                f"`{core.STRATEGY_LABELS[strat]}`")
                            st.dataframe(df.head(10), use_container_width=True)
                        if len(tables) > 6:
                            st.caption(f"…and {len(tables) - 6} more in the download.")
                        st.download_button(
                            "⬇️ Download tables.xlsx", core.tables_to_excel(tables),
                            "pdf_tables.xlsx",
                            "application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet", key=P + "tab_dl")
        else:
            st.subheader("Get started")
            st.markdown(
                "1. Upload a **PDF** containing tables.\n"
                "2. Click **Extract tables** to pull them into Excel."
            )

# ========================================================== TAB 3 ===
with tab_beauty:
    st.header("Screenshot beautifier")
    st.caption("Trim, pad, round corners, and add drop shadows — batch mode "
               "with a zip download.")

    with st.container(border=True):
        st.subheader("① Style options & results")
        b_ups = st.file_uploader("Screenshots", type=["png", "jpg", "jpeg"],
                                 accept_multiple_files=True, key=P + "beauty")
        c1, c2 = st.columns(2)
        with c1:
            trim = st.checkbox("Auto-trim solid borders", value=True, key=P + "b_trim")
            cl = st.slider("Crop left %", 0, 40, 0, key=P + "b_cl")
            ct = st.slider("Crop top %", 0, 40, 0, key=P + "b_ct")
            padding = st.slider("Padding (px)", 0, 120, 24, key=P + "b_pad")
            pad_color = st.color_picker("Padding color", "#FFFFFF", key=P + "b_pc")
        with c2:
            radius = st.slider("Rounded corners (px)", 0, 80, 16, key=P + "b_rad")
            shadow = st.checkbox("Drop shadow", value=True, key=P + "b_sh")
            s_blur = st.slider("Shadow blur", 4, 60, 18, key=P + "b_sb")
            s_off = st.slider("Shadow offset", 0, 40, 12, key=P + "b_so")
            s_op = st.slider("Shadow opacity %", 10, 90, 45, key=P + "b_sop")
        cr = st.slider("Crop right %", 0, 40, 0, key=P + "b_cr")
        cb = st.slider("Crop bottom %", 0, 40, 0, key=P + "b_cb")

        opts = {"trim": trim, "crop_l": cl, "crop_t": ct, "crop_r": cr,
                "crop_b": cb, "padding": padding, "pad_color": pad_color,
                "radius": radius, "shadow": shadow, "shadow_blur": s_blur,
                "shadow_offset": s_off, "shadow_opacity": s_op}

        if b_ups:
            outs: list[tuple[str, bytes]] = []
            for up in b_ups:
                try:
                    img = Image.open(up).convert("RGB")
                except Exception as e:
                    st.error(f"⚠️ Could not read {up.name}: {e}")
                    continue
                pretty = core.beautify(img, opts)
                buf = io.BytesIO()
                pretty.save(buf, format="PNG")
                outs.append((up.name, buf.getvalue()))
                b1, b2 = st.columns(2)
                with b1:
                    st.caption(f"Before — {up.name}")
                    st.image(img, use_container_width=True)
                with b2:
                    st.caption("After")
                    st.image(pretty, use_container_width=True)
                st.download_button(f"⬇️ {up.name} (PNG)", outs[-1][1],
                                   f"pretty_{Path(up.name).stem}.png", "image/png",
                                   key=P + f"dl_{up.name}")
            if len(outs) > 1:
                zbuf = io.BytesIO()
                with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as z:
                    for name, data in outs:
                        z.writestr(f"pretty_{Path(name).stem}.png", data)
                st.download_button("⬇️ Download all (.zip)", zbuf.getvalue(),
                                   "pretty_screenshots.zip", "application/zip",
                                   key=P + "dl_all")
        else:
            st.subheader("Get started")
            st.markdown(
                "1. Upload one or more **screenshots** above.\n"
                "2. Tune trim, padding, corners, and shadow.\n"
                "3. Download each beautified PNG — or all as a zip."
            )
