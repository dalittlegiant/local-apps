"""App 4 — Automated PowerPoint & Playbook Builder.

1. Annotated Screenshot Slide Builder — numbered callout badges on
   screenshots (Pillow) -> .pptx slide (image left, steps table right).
2. Data Dictionary to Slides — CSV/Markdown tables paginated into clean
   table slides (configurable rows per slide, never overflows).
3. Data-Driven Slide Cloner — {{tag}} template + dataset -> one populated
   slide per row.

Pure logic lives in ppt_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import io
import sys
from pathlib import Path

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ppt_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="PowerPoint & Playbook Builder",
                       page_icon="📽️", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "ppt4_"


def _init():
    st.session_state.setdefault(P + "deck", [])  # [{title, png, steps}]
    st.session_state.setdefault(P + "template", None)


_init()

st.title("📽️ Automated PowerPoint & Playbook Builder")
st.caption("Annotated screenshots, data-dictionary slides, and {{tag}} "
           "mail-merge — 100% local via python-pptx + Pillow.")

tab1, tab2, tab3 = st.tabs([
    "🖼️ Annotated Screenshot Builder",
    "📊 Data Dictionary to Slides",
    "✉️ Slide Cloner (Mail-Merge)",
])

# ============================================================ TAB 1 ===
with tab1:
    st.header("Annotated screenshot slide")
    st.caption("Upload a screenshot, place numbered badges with the X/Y "
               "sliders, describe each step, and append the slide to your deck.")

    with st.container(border=True):
        st.subheader("① Inputs")
        shot = st.file_uploader("Dashboard / system screenshot",
                                type=["png", "jpg", "jpeg"], key=P + "shot")
        tpl = st.file_uploader("Corporate .pptx template (optional — deck-wide)",
                               type=["pptx"], key=P + "template_up")
        if tpl is not None:
            st.session_state[P + "template"] = tpl.getvalue()
            st.caption(f"Template loaded: {tpl.name}")
        elif st.session_state[P + "template"]:
            st.caption("Using the previously loaded corporate template.")

        title = st.text_input("Slide title", value="Dashboard walkthrough",
                              key=P + "slide_title")

    if shot is None:
        with st.container(border=True):
            st.subheader("Get started")
            st.markdown(
                "1. Upload a **dashboard or system screenshot** above.\n"
                "2. Place numbered callouts with the X/Y sliders.\n"
                "3. Describe each step, check the live preview, then "
                "**➕ Add slide to deck**."
            )
    else:
        with st.container(border=True):
            st.subheader("② Callouts & live preview")
            try:
                img = Image.open(shot).convert("RGB")
            except Exception as e:
                st.error(f"⚠️ Could not read that image: {e}")
                img = None
            if img is not None:
                st.caption(f"Image: {img.size[0]}×{img.size[1]} px — "
                           "X/Y are % of width/height.")
                n_callouts = st.number_input("Number of callouts", 1, 12, 3,
                                             key=P + "n_callouts")
                callouts, steps = [], []
                for i in range(1, int(n_callouts) + 1):
                    c1, c2, c3 = st.columns([1, 1, 3])
                    with c1:
                        x = st.slider(f"#{i} X %", 0, 100, 50, key=P + f"cx_{i}")
                    with c2:
                        y = st.slider(f"#{i} Y %", 0, 100, 30, key=P + f"cy_{i}")
                    with c3:
                        txt = st.text_input(f"#{i} step description",
                                            key=P + f"ct_{i}",
                                            placeholder=f"What happens at point {i}…")
                    callouts.append({"x": x, "y": y, "n": i})
                    steps.append({"n": i, "text": txt or f"(step {i} — no description yet)"})

                st.subheader("Live preview")
                st.image(core.annotate_screenshot(img, callouts),
                         use_container_width=True)

                if st.button("➕ Add slide to deck", type="primary",
                             key=P + "add_slide"):
                    buf = io.BytesIO()
                    core.annotate_screenshot(img, callouts).save(buf, format="PNG")
                    st.session_state[P + "deck"].append({
                        "title": title or "Annotated walkthrough",
                        "png": buf.getvalue(),
                        "steps": steps,
                    })
                    st.success(f"Slide added — deck now has "
                               f"{len(st.session_state[P + 'deck'])} slide(s).")

    st.divider()
    deck = st.session_state[P + "deck"]
    st.subheader(f"Deck ({len(deck)} slide(s))")
    if deck:
        for i, s in enumerate(deck, start=1):
            st.write(f"{i}. {s['title']} — {len(s['steps'])} step(s)")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("⬇️ Download deck (.pptx)", type="primary",
                         key=P + "dl_deck"):
                prs = core.load_template(st.session_state[P + "template"])
                for s in deck:
                    core.add_annotated_slide(
                        prs, Image.open(io.BytesIO(s["png"])), s["steps"],
                        title=s["title"])
                st.download_button(
                    "💾 Save playbook_deck.pptx", core.prs_to_bytes(prs),
                    "playbook_deck.pptx",
                    "application/vnd.openxmlformats-officedocument."
                    "presentationml.presentation", key=P + "dl_deck_file")
        with c2:
            if st.button("🗑️ Clear deck", key=P + "clear_deck"):
                st.session_state[P + "deck"] = []
                st.rerun()
    else:
        st.info("Deck is empty — build a slide above.")

# ============================================================ TAB 2 ===
with tab2:
    st.header("Data Dictionary → table slides")
    st.caption("Feed it the CSV/Markdown output of the Metadata Extractor; it "
               "paginates rows into clean table slides so text never overflows.")

    with st.container(border=True):
        st.subheader("① Input")
        src = st.radio("Input", ("Upload CSV", "Paste Markdown table"),
                       horizontal=True, key=P + "dd_src")
        df = None
        try:
            if src == "Upload CSV":
                up = st.file_uploader("KPI / measure table (.csv)", type=["csv"],
                                      key=P + "dd_csv")
                if up is not None:
                    df = core.read_csv_smart(up.getvalue())
            else:
                md = st.text_area("Markdown table", height=180, key=P + "dd_md",
                                  placeholder="| Measure | DAX | Description |\n"
                                              "|---|---|---|\n| Total Sales | SUM(...) | ... |")
                if md.strip():
                    cols, rows = core.parse_markdown_table(md)
                    df = pd.DataFrame(rows, columns=cols)
        except ValueError as e:
            st.error(f"⚠️ {e}")

    if df is not None and not df.empty:
        with st.container(border=True):
            st.subheader("② Preview & slide options")
            st.dataframe(df.head(10), use_container_width=True)
            if len(df) > 10:
                st.caption(f"…and {len(df) - 10} more row(s).")
            cols = st.multiselect("Columns on slides", list(df.columns),
                                  default=list(df.columns), key=P + "dd_cols")
            rps = st.slider("Rows per slide", 4, 10, 7, key=P + "dd_rps",
                            help="Keeps text from overflowing the table.")
            prefix = st.text_input("Slide title prefix", value="Data Dictionary",
                                   key=P + "dd_prefix")
            tpl2 = st.file_uploader("Corporate .pptx template (optional)",
                                    type=["pptx"], key=P + "dd_template")
            if st.button("⚙️ Generate slides", type="primary", key=P + "dd_go"):
                if not cols:
                    st.error("Pick at least one column.")
                else:
                    sub = df[cols].fillna("").astype(str)
                    prs = core.load_template(tpl2.getvalue() if tpl2 else None)
                    n = core.add_dictionary_slides(
                        prs, cols, sub.values.tolist(),
                        rows_per_slide=int(rps),
                        title_prefix=prefix or "Data Dictionary")
                    st.success(f"Generated {n} slide(s) for {len(sub)} row(s).")
                    st.download_button(
                        "⬇️ Download data_dictionary.pptx", core.prs_to_bytes(prs),
                        "data_dictionary.pptx",
                        "application/vnd.openxmlformats-officedocument."
                        "presentationml.presentation", key=P + "dd_dl")
    elif df is not None:
        st.warning("No rows found in the input.")
    else:
        with st.container(border=True):
            st.subheader("Get started")
            st.markdown(
                "1. Upload a **CSV** data dictionary (e.g. exported from the "
                "Metadata Extractor), or paste a **Markdown table**.\n"
                "2. Choose which columns go on the slides and the rows per slide.\n"
                "3. Click **⚙️ Generate slides** to build the deck."
            )

# ============================================================ TAB 3 ===
with tab3:
    st.header("Data-driven slide cloner")
    st.caption("Template .pptx with {{Placeholder}} tags + a dataset → one "
               "populated slide per row. Tags are replaced in text boxes and "
               "tables; images on the template slide are preserved.")

    with st.container(border=True):
        st.subheader("① Template & dataset")
        t_up = st.file_uploader("Template .pptx", type=["pptx"], key=P + "mm_template")
        if t_up is None:
            st.subheader("Get started")
            st.markdown(
                "1. Upload a **template .pptx** whose slide contains `{{tags}}`.\n"
                "2. Pick the template slide number below.\n"
                "3. Upload a **dataset (.csv / .xlsx)** — one column per tag — "
                "to generate the merged deck."
            )
        else:
            t_bytes = t_up.getvalue()
            try:
                prs = core.load_template(t_bytes)
            except Exception as e:
                st.error(f"⚠️ Could not read that template: {e}")
                prs = None
            if prs is not None:
                n_slides = len(prs.slides)
                idx = st.number_input("Template slide number", 1, n_slides, 1,
                                      key=P + "mm_idx") - 1
                tags = core.find_tags(prs, int(idx))
                if tags:
                    st.success(f"Detected tags: {', '.join('{{' + t + '}}' for t in tags)}")
                else:
                    st.warning("No {{tags}} found on that slide — check the slide number.")

                st.divider()
                d_up = st.file_uploader("Dataset (.csv / .xlsx)",
                                        type=["csv", "xlsx", "xls"],
                                        key=P + "mm_data")
                if d_up is None:
                    st.subheader("Next step")
                    st.markdown(
                        "Upload a **dataset (.csv / .xlsx)** with one column "
                        "per `{{tag}}` to generate the merged deck."
                    )
                else:
                    try:
                        if d_up.name.lower().endswith(".csv"):
                            ddf = core.read_csv_smart(d_up.getvalue())
                        else:
                            ddf = pd.read_excel(d_up, dtype=str).fillna("")
                        ddf = ddf.loc[:, ~(ddf.columns.astype(str).str.startswith("Unnamed"))]
                        st.dataframe(ddf.head(8), use_container_width=True)
                        st.caption(f"{len(ddf)} row(s) → {len(ddf)} slide(s).")
                        missing = [t for t in tags if t not in ddf.columns]
                        if missing:
                            st.warning("Dataset has no column for tag(s): "
                                       + ", ".join(missing) + " — they will stay as-is.")
                        if st.button("⚙️ Generate merged deck", type="primary",
                                     key=P + "mm_go"):
                            dataset = ddf.fillna("").astype(str).to_dict("records")
                            out = core.mail_merge(t_bytes, int(idx), dataset)
                            st.success(f"Merged {len(dataset)} slide(s).")
                            st.download_button(
                                "⬇️ Download merged deck", out, "merged_deck.pptx",
                                "application/vnd.openxmlformats-officedocument."
                                "presentationml.presentation", key=P + "mm_dl")
                    except ValueError as e:
                        st.error(f"⚠️ {e}")
                    except Exception as e:
                        st.error(f"⚠️ Could not read dataset: {e}")
