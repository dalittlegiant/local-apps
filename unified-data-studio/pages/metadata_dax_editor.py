"""App 1 — PBIP Metadata & DAX Editor.

Parse .tmdl files inside a PBIP folder, review tables/columns/measures, edit
DAX formulas and descriptions in the browser, and save back to the .tmdl
files with byte-level preservation of everything else (lineageTag,
indentation, comments, blank lines).

Two load modes:
  - "PBIP folder path": edits are saved in place on the local disk.
  - "Upload PBIP .zip":   edits apply to an extracted temp copy; download
    the updated .zip afterwards (works on hosted Streamlit too).
"""

import copy
import difflib
import io
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st

from lib.tmdl_io import (
    apply_line_ops,
    build_edit_ops,
    detect_pbip_format,
    parse_tmdl_text,
    read_tmdl_file,
    render_tmdl_text,
    tables_summary,
    to_markdown,
    validate_dax,
)

SS = "tmdl"


def _state() -> dict:
    if SS not in st.session_state:
        st.session_state[SS] = {"loaded": False}
    return st.session_state[SS]


def _reset():
    st.session_state[SS] = {"loaded": False}


# ------------------------------------------------------------ loading
def _load_from_paths(files: list[Path], mode: str, label: str):
    file_data: dict[str, dict] = {}
    objects = []
    warnings: list[str] = []
    for f in files:
        try:
            tfile, meta = read_tmdl_file(f)
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"Skipped {f.name}: cannot read ({exc})")
            continue
        # Keep the exact original lines for diffing.
        text = f.read_bytes().decode("utf-8-sig")
        file_data[f.name] = {"path": f, "lines": text.splitlines(), "meta": meta}
        if not tfile.objects:
            warnings.append(f"{f.name}: no editable objects found")
        objects.extend(tfile.objects)
    st.session_state[SS] = {
        "loaded": True,
        "mode": mode,
        "label": label,
        "files": file_data,          # name -> {path, lines, meta}
        "objects": objects,          # working copies (mutated by the UI)
        "orig": copy.deepcopy(objects),
        "warnings": warnings,
    }


def _load_folder(root: Path):
    _, files = detect_pbip_format(root)
    _load_from_paths(files, "folder", root.name)


def _load_zip(uploaded) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="pbip_"))
    with zipfile.ZipFile(uploaded) as z:
        z.extractall(tmp)
    # A PBIP zip usually contains one top-level folder; detect handles nesting.
    candidates = [p for p in tmp.iterdir() if p.is_dir()]
    root = tmp
    for c in candidates:
        try:
            detect_pbip_format(c)
            root = c
            break
        except ValueError:
            continue
    _, files = detect_pbip_format(root)
    _load_from_paths(files, "zip", uploaded.name)
    return tmp


# ------------------------------------------------------------ diff/save
def _changed_ops() -> dict[str, list]:
    """Working vs original -> {file_name: [LineOp]} for changed objects."""
    s = _state()
    per_file: dict[str, list] = {}
    for work, orig in zip(s["objects"], s["orig"]):
        new_expr = (work.expression if (work.expression or "").strip()
                    != (orig.expression or "").strip() else None)
        new_desc = work.description if work.description != orig.description else None
        if new_expr is None and new_desc is None:
            continue
        ops = build_edit_ops(orig, new_expr, new_desc)
        if ops:
            fname = orig.id.split("\x1f")[0]
            per_file.setdefault(fname, []).extend(ops)
    return per_file


def _apply_all(per_file: dict[str, list]) -> dict[str, list[str]]:
    """Apply ops -> {file_name: new_lines}."""
    s = _state()
    return {fname: apply_line_ops(s["files"][fname]["lines"], ops)
            for fname, ops in per_file.items()}


# ================================================================== UI
st.title("📊 PBIP Metadata & DAX Editor")
st.caption("Extract, edit, and save back TMDL metadata — lineageTag-safe by design.")

s = _state()

# ---- 1. Load -----------------------------------------------------------
with st.expander("① Load a PBIP model", expanded=not s["loaded"]):
    mode = st.radio("Source", ("PBIP folder path", "Upload PBIP .zip"),
                    horizontal=True, key="tmdl_src_mode")
    if mode == "PBIP folder path":
        folder = st.text_input("PBIP project root path",
                               placeholder=r"C:\Projects\MyReport  or  /home/user/MyReport",
                               key="tmdl_folder")
        if st.button("📂 Load model", type="primary", key="tmdl_load_folder"):
            try:
                _load_folder(Path(folder.strip()).expanduser())
                st.rerun()
            except ValueError as e:
                st.error(f"⚠️ {e}")
    else:
        up = st.file_uploader("PBIP project as .zip", type=["zip"], key="tmdl_zip")
        if up and st.button("📦 Load model", type="primary", key="tmdl_load_zip"):
            try:
                _load_zip(up)
                st.rerun()
            except ValueError as e:
                st.error(f"⚠️ {e}")
            except zipfile.BadZipFile:
                st.error("⚠️ That file is not a valid .zip.")

if not s["loaded"]:
    with st.container(border=True):
        st.subheader("Get started")
        st.markdown(
            "1. Choose **PBIP folder path** to edit a model in place on disk, "
            "or **Upload PBIP .zip** to work on an extracted copy.\n"
            "2. Click **Load model** — tables, columns, and measures appear below.\n"
            "3. Edit descriptions and DAX, review the diffs, then save."
        )
    st.stop()

for w in s["warnings"]:
    st.warning(w)

objects: list = s["objects"]
n_tables = len({o.table for o in objects if o.kind == "table"} or
               {o.table for o in objects})
with st.container(border=True):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tables", n_tables)
    m2.metric("Columns", sum(1 for o in objects if o.kind == "column"))
    m3.metric("Measures", sum(1 for o in objects if o.kind == "measure"))
    m4.metric("Files", len(s["files"]))
    st.caption(f"Source: `{s['label']}` · mode: {s['mode']} · "
               "edits are staged until you save.")

# ---- 2. Edit descriptions ----------------------------------------------
with st.container(border=True):
    st.subheader("② Edit descriptions")
    desc_df = pd.DataFrame([{
        "Table": o.table,
        "Type": o.kind,
        "Name": o.name,
        "Description": o.description or "",
        "LineageTag": "✅" if o.has_lineage_tag else "—",
    } for o in objects])
    edited = st.data_editor(
        desc_df,
        use_container_width=True,
        hide_index=True,
        disabled=["Table", "Type", "Name", "LineageTag"],
        column_config={
            "Description": st.column_config.TextColumn("Description", width="large"),
            "LineageTag": st.column_config.TextColumn("LineageTag", width="small",
                                                      help="lineageTag is never modified"),
        },
        key="tmdl_desc_editor",
    )
    for i, o in enumerate(objects):
        val = edited.iloc[i]["Description"]
        o.description = "" if pd.isna(val) else str(val)

# ---- 3. Edit DAX ---------------------------------------------------------
with st.container(border=True):
    st.subheader("③ Edit DAX formulas")
    measures = [o for o in objects if o.kind == "measure"]
    if not measures:
        st.info("No measures in this model.")
    else:
        labels = [f"{o.table} :: {o.name}" for o in measures]
        pick = st.selectbox("Measure", labels, key="tmdl_meas_pick")
        mobj = measures[labels.index(pick)]
        # Key includes the measure index so switching measures resets the box
        # to the newly selected DAX instead of showing stale widget state.
        new_dax = st.text_area("DAX expression", value=mobj.expression or "",
                               height=280, key=f"tmdl_dax_area_{labels.index(pick)}",
                               help="Multi-line DAX is preserved verbatim.")
        for w in validate_dax(new_dax):
            st.warning(f"DAX check: {w}")
        c1, c2 = st.columns([1, 4])
        with c1:
            if st.button("📌 Stage DAX change", key="tmdl_stage_dax"):
                mobj.expression = new_dax
                st.success(f"Staged new DAX for `{mobj.name}`. Save below to write it.")
        with c2:
            if (mobj.expression or "").strip() != (new_dax or "").strip():
                st.caption("✏️ Unstaged changes in the box above — click **Stage DAX change**.")

# ---- 4. Review & save ----------------------------------------------------
with st.container(border=True):
    st.subheader("④ Review & save")
    per_file = _changed_ops()
    if not per_file:
        st.success("No staged changes. Edit descriptions or DAX above, then save here.")
    else:
        new_lines_map = _apply_all(per_file)
        total_ops = sum(len(v) for v in per_file.values())
        st.warning(f"**{total_ops}** edit operation(s) staged across "
                   f"**{len(per_file)}** file(s). Review the diffs, then save.")
        with st.expander("🔍 Preview diffs (per file)"):
            for fname, new_lines in new_lines_map.items():
                old_lines = s["files"][fname]["lines"]
                diff = "\n".join(difflib.unified_diff(
                    old_lines, new_lines, fromfile=fname + " (original)",
                    tofile=fname + " (edited)", lineterm=""))
                st.code(diff or "(no textual change)", language="diff")

        col_a, col_b = st.columns(2)
        with col_a:
            confirm = st.checkbox("I understand this rewrites the .tmdl files",
                                  key="tmdl_confirm")
            if st.button("💾 Save all changes", type="primary",
                         disabled=not confirm, key="tmdl_save"):
                for fname, new_lines in new_lines_map.items():
                    meta = s["files"][fname]["meta"]
                    data = render_tmdl_text(new_lines, meta)
                    s["files"][fname]["path"].write_bytes(data)
                    s["files"][fname]["lines"] = new_lines
                # Re-baseline: re-parse so orig matches the new files.
                fresh = []
                for f in s["files"].values():
                    tfile, _ = read_tmdl_file(f["path"])
                    fresh.extend(tfile.objects)
                # Carry staged descriptions/expressions onto the fresh parse by id.
                by_id = {o.id: o for o in s["objects"]}
                for o in fresh:
                    if o.id in by_id:
                        o.description = by_id[o.id].description
                        if o.kind == "measure":
                            o.expression = by_id[o.id].expression
                s["objects"] = fresh
                s["orig"] = copy.deepcopy(fresh)
                st.success("✅ Saved. lineageTag lines and indentation untouched "
                           "outside your edits.")
                st.rerun()
        with col_b:
            if s["mode"] == "zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for fname, f in s["files"].items():
                        z.writestr(fname, render_tmdl_text(f["lines"], f["meta"]))
                st.download_button(
                    "⬇️ Download updated .tmdl files (.zip)",
                    buf.getvalue(), "tmdl_updated.zip", "application/zip",
                    key="tmdl_dl_zip",
                    help="Copy these over your PBIP definition/tables/ folder.")
            if st.button("↩️ Discard all staged changes", key="tmdl_discard"):
                s["objects"] = copy.deepcopy(s["orig"])
                st.rerun()

# ---- 5. Export ------------------------------------------------------------
st.divider()
all_tables: list[dict] = []
for f in s["files"].values():
    tfile, _ = read_tmdl_file(f["path"])
    # Show the *staged* values in the export.
    by_id = {o.id: o for o in s["objects"]}
    for o in tfile.objects:
        if o.id in by_id:
            o.description = by_id[o.id].description
            if o.kind == "measure":
                o.expression = by_id[o.id].expression
    all_tables.extend(tables_summary(tfile))
md_text = to_markdown(all_tables, s["label"], f"TMDL ({len(s['files'])} files)")
with st.container(border=True):
    st.subheader("⑤ Export data dictionary")
    st.download_button("⬇️ Download Data Dictionary (Markdown)",
                       md_text.encode("utf-8"), "documentation.md",
                       "text/markdown", key="tmdl_dl_md")
    with st.expander("Preview Markdown"):
        st.code(md_text[:6000] + ("…" if len(md_text) > 6000 else ""),
                language="markdown")
