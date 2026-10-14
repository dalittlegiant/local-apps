"""App 3 — Power BI Theme & UI Studio.

Two tools:
  1. Theme Generator — color pickers + sliders -> live dashboard mockup
     preview -> downloadable standard Power BI theme.json.
  2. Bulk Visual Editor — scan PBIP visual.json files and standardize
     container formatting (padding, rounded corners, ...) across a report.

Pure logic lives in lib/theme_builder.py.
"""

import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from lib.theme_builder import (
    FONT_FACES, PALETTES, apply_vco_standard, build_theme, default_settings,
    render_preview_html, scan_visual_jsons, standard_presets, theme_to_json,
    validate_theme,
)

T = "thu_"  # widget/state prefix


def _init():
    d = default_settings()
    defaults = {
        "name": d["name"], "page_bg": d["page_bg"], "foreground": d["foreground"],
        "table_accent": d["table_accent"], "card_bg": d["card_bg"],
        "card_transparency": d["card_transparency"],
        "border_show": d["border_show"], "border_color": d["border_color"],
        "border_width": d["border_width"], "corner_radius": d["corner_radius"],
        "shadow_show": d["shadow_show"], "shadow_color": d["shadow_color"],
        "shadow_blur": d["shadow_blur"],
        "shadow_transparency": d["shadow_transparency"], "padding": d["padding"],
        "title_show": d["title_show"], "title_color": d["title_color"],
        "title_size": d["title_size"], "font_face": d["font_face"],
        "label_color": d["label_color"], "label_size": d["label_size"],
        "header_color": d["header_color"], "header_size": d["header_size"],
        "callout_color": d["callout_color"], "callout_size": d["callout_size"],
        "palette": "Power BI Default",
    }
    for i, c in enumerate(d["data_colors"]):
        defaults[f"c{i}"] = c
    for k, v in defaults.items():
        st.session_state.setdefault(T + k, v)


def _settings() -> dict:
    g = lambda k: st.session_state[T + k]  # noqa: E731
    return {
        "name": g("name"),
        "data_colors": [g(f"c{i}") for i in range(8)],
        "page_bg": g("page_bg"), "foreground": g("foreground"),
        "table_accent": g("table_accent"), "card_bg": g("card_bg"),
        "card_transparency": g("card_transparency"),
        "border_show": g("border_show"), "border_color": g("border_color"),
        "border_width": g("border_width"), "corner_radius": g("corner_radius"),
        "shadow_show": g("shadow_show"), "shadow_color": g("shadow_color"),
        "shadow_blur": g("shadow_blur"),
        "shadow_transparency": g("shadow_transparency"),
        "padding": g("padding"), "title_show": g("title_show"),
        "title_color": g("title_color"), "title_size": g("title_size"),
        "font_face": g("font_face"), "label_color": g("label_color"),
        "label_size": g("label_size"), "header_color": g("header_color"),
        "header_size": g("header_size"), "callout_color": g("callout_color"),
        "callout_size": g("callout_size"),
    }


_init()

st.title("🎨 Power BI Theme & UI Studio")
st.caption("Design a theme, watch the mockup update live, export theme.json — "
           "then standardize container formatting across a whole report.")

tab_theme, tab_bulk = st.tabs(["🎨 Theme Generator", "🧱 Bulk Visual Editor"])

# ==================================================== TAB 1: THEME ===
with tab_theme:
    left, right = st.columns([1, 1.35])

    with left:
        st.subheader("Controls")
        st.text_input("Theme name", key=T + "name")

        st.markdown("**Data colors**")
        pal = st.selectbox("Palette preset", list(PALETTES.keys()), key=T + "palette")
        if st.button("Apply palette", key=T + "apply_pal"):
            for i, c in enumerate(PALETTES[pal]):
                st.session_state[T + f"c{i}"] = c
            st.rerun()
        cols = st.columns(4)
        for i in range(8):
            with cols[i % 4]:
                st.color_picker(f"C{i + 1}", key=T + f"c{i}")

        st.markdown("**Page & text**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.color_picker("Page background", key=T + "page_bg")
        with c2:
            st.color_picker("Default text", key=T + "foreground")
        with c3:
            st.color_picker("Table accent", key=T + "table_accent")
        st.selectbox("Font face", FONT_FACES, key=T + "font_face")

        st.markdown("**Card container**")
        c1, c2 = st.columns(2)
        with c1:
            st.color_picker("Card background", key=T + "card_bg")
        with c2:
            st.slider("Card transparency %", 0, 100, key=T + "card_transparency")
        st.slider("Card padding (px)", 0, 32, key=T + "padding")

        st.markdown("**Border**")
        b1, b2, b3 = st.columns(3)
        with b1:
            st.checkbox("Show border", key=T + "border_show")
        with b2:
            st.color_picker("Border color", key=T + "border_color")
        with b3:
            st.slider("Width", 0, 5, key=T + "border_width")
        st.slider("Rounded corners (radius px)", 0, 24, key=T + "corner_radius")

        st.markdown("**Shadow**")
        s1, s2 = st.columns(2)
        with s1:
            st.checkbox("Show shadow", key=T + "shadow_show")
            st.color_picker("Shadow color", key=T + "shadow_color")
        with s2:
            st.slider("Blur", 0, 24, key=T + "shadow_blur")
            st.slider("Shadow transparency %", 0, 100, key=T + "shadow_transparency")

        st.markdown("**Titles & text classes**")
        t1, t2, t3 = st.columns(3)
        with t1:
            st.checkbox("Show titles", key=T + "title_show")
        with t2:
            st.color_picker("Title color", key=T + "title_color")
        with t3:
            st.slider("Title size", 8, 24, key=T + "title_size")
        x1, x2, x3 = st.columns(3)
        with x1:
            st.color_picker("Label color", key=T + "label_color")
            st.slider("Label size", 8, 16, key=T + "label_size")
        with x2:
            st.color_picker("Header color", key=T + "header_color")
            st.slider("Header size", 8, 16, key=T + "header_size")
        with x3:
            st.color_picker("Callout color", key=T + "callout_color")
            st.slider("Callout size", 16, 48, key=T + "callout_size")

    settings = _settings()
    theme = build_theme(settings)

    with right:
        st.subheader("Live preview")
        components.html(render_preview_html(settings), height=620, scrolling=True)

        for w in validate_theme(theme):
            st.warning(w)

        with st.expander("View theme.json"):
            st.code(theme_to_json(theme), language="json")
        safe_name = re.sub(r"[^\w\-]+", "_", settings["name"]).strip("_") or "theme"
        st.download_button(
            "⬇️ Download theme.json",
            theme_to_json(theme).encode("utf-8"),
            f"{safe_name}.json", "application/json", key=T + "dl_theme",
            help="Import via Power BI View → Themes → Browse for themes.")
        st.caption("If a Desktop build ignores the rounded corners, delete the "
                   "`radius` key inside `border` in the exported JSON.")

# ===================================================== TAB 2: BULK ===
with tab_bulk:
    st.header("Standardize container formatting across a report")
    st.caption("Scans `visual.json` files (from a PBIP report) for container "
               "formatting — padding, border, background, shadow, titles — and "
               "applies one standard everywhere. Only the chosen properties "
               "are touched; everything else in each file is preserved.")

    src = st.radio("Source", ("Upload visual.json files", "Upload report .zip"),
                   horizontal=True, key=T + "bulk_src")
    visuals: list[tuple[str, dict]] = []
    if src == "Upload visual.json files":
        ups = st.file_uploader("visual.json files", type=["json"],
                               accept_multiple_files=True, key=T + "bulk_files")
        if ups:
            for u in ups:
                try:
                    visuals.append((u.name, json.loads(u.getvalue().decode("utf-8-sig"))))
                except (ValueError, UnicodeDecodeError):
                    visuals.append((u.name, {}))
    else:
        zup = st.file_uploader("PBIP report .zip", type=["zip"], key=T + "bulk_zip")
        if zup:
            try:
                tmp = Path(tempfile.mkdtemp(prefix="pbi_report_"))
                with zipfile.ZipFile(zup) as z:
                    z.extractall(tmp)
                for p in sorted(tmp.rglob("visual.json")):
                    try:
                        visuals.append((str(p.relative_to(tmp)),
                                        json.loads(p.read_text(encoding="utf-8-sig"))))
                    except (ValueError, UnicodeDecodeError):
                        visuals.append((str(p.relative_to(tmp)), {}))
            except zipfile.BadZipFile:
                st.error("⚠️ That file is not a valid .zip.")

    if visuals:
        st.subheader(f"① Scan — {len(visuals)} visual(s)")
        scan_df = scan_visual_jsons(visuals)
        st.dataframe(scan_df, use_container_width=True, hide_index=True)

        st.subheader("② Choose the standard")
        presets = standard_presets()
        mode = st.radio("Standard source", ("Preset", "Custom"), horizontal=True,
                        key=T + "std_mode")
        standard: dict = {}
        if mode == "Preset":
            pname = st.selectbox("Preset", list(presets.keys()), key=T + "preset")
            standard = presets[pname]
            st.json(standard)
        else:
            cp1, cp2, cp3 = st.columns(3)
            with cp1:
                pad = st.number_input("Padding (px, all sides)", 0, 64, 8,
                                      key=T + "cp_pad")
                use_pad = st.checkbox("Apply padding", value=True, key=T + "cp_pad_on")
            with cp2:
                rad = st.number_input("Corner radius (px)", 0, 32, 8, key=T + "cp_rad")
                use_rad = st.checkbox("Apply corner radius", value=True,
                                      key=T + "cp_rad_on")
            with cp3:
                use_bg = st.checkbox("Ensure card background visible", value=False,
                                     key=T + "cp_bg_on")
            if use_pad:
                standard["padding"] = {"top": pad, "bottom": pad,
                                       "left": pad, "right": pad}
            if use_rad:
                standard["border"] = {"show": True, "radius": rad}
            if use_bg:
                standard.setdefault("background", {})["show"] = True

        st.subheader("③ Preview & apply")
        if st.button("🔍 Preview changes", key=T + "preview"):
            any_change = False
            for name, visual in visuals:
                _, changes = apply_vco_standard(visual, standard)
                if changes:
                    any_change = True
                    with st.expander(f"{name} — {len(changes)} change(s)"):
                        for ch in changes:
                            st.write("• " + ch)
            if not any_change:
                st.success("No changes needed — every visual already matches.")
            st.session_state[T + "standard"] = standard

        if T + "standard" in st.session_state:
            if st.button("💾 Apply & download .zip", type="primary", key=T + "apply"):
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for name, visual in visuals:
                        new_visual, _ = apply_vco_standard(
                            visual, st.session_state[T + "standard"])
                        z.writestr(name, json.dumps(new_visual, indent=2,
                                                   ensure_ascii=False))
                st.download_button(
                    "⬇️ Download standardized visual.json files",
                    buf.getvalue(), "visuals_standardized.zip",
                    "application/zip", key=T + "dl_zip",
                    help="Copy each visual.json back over the matching file in "
                         "your PBIP report's definition/pages/ tree.")
    else:
        st.info("👆 Upload visual.json files (or a report .zip) to scan them.")
