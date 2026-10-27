"""App — Power Apps ALM & Masking Tool.

Unpack a .msapp with the Power Platform CLI (pac), mask sensitive strings
so the sources can go to GitHub for AI revision, then unmask and pack back
into a .msapp. 100% local except the GitHub step you do yourself.

Pure logic lives in pac_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pac_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="Power Apps ALM & Masking", page_icon="🎨",
                       layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "pam_"
STORAGE = Path(__file__).resolve().parent / "storage"
APP_DIR = Path(__file__).resolve().parent


def set_status(step, kind, msg):
    st.session_state.setdefault(P + "status", {})[step] = (kind, msg)


def show_status(step):
    kind, msg = st.session_state.get(P + "status", {}).get(step, (None, None))
    if kind == "success":
        st.success(msg)
    elif kind == "error":
        st.error(msg)
    elif kind == "info":
        st.info(msg)


def show_report(report):
    st.write(f"Files scanned: **{report['files_scanned']}** · "
             f"files changed: **{report['files_changed']}** · "
             f"total replacements: **{report['total']}**")
    if report["per_file"]:
        rows = [{"file": f, "replacements": n}
                for f, n in sorted(report["per_file"].items())]
        st.dataframe(rows, use_container_width=True, hide_index=True,
                     height=min(400, 40 + 35 * len(rows)))


def show_verification(counts, what):
    leftovers = {k: v for k, v in counts.items() if v > 0}
    if not leftovers:
        st.success(f"Verification passed — no {what} values remain in the sources.")
    else:
        st.warning(f"Verification: these {what} values still appear "
                   f"({sum(leftovers.values())} occurrences) — they may live "
                   "in files this tool does not scan (other suffixes), or in "
                   "a form that differs from the mapping (check spelling/case):")
        st.write(leftovers)


def show_renames(report):
    st.write(f"Filename/folder renames: **{report['total']}**")
    if report["renames"]:
        st.dataframe([{"from": a, "to": b} for a, b in report["renames"]],
                     use_container_width=True, hide_index=True)
    for old, reason in report["skipped"]:
        st.warning(f"Skipped rename {old}: {reason} — nothing was "
                   "overwritten. Fix the clash (or the mapping) and re-run.")


def mapping_dict():
    return st.session_state.setdefault(P + "mapping", {})


def editor_frame():
    import pandas as pd
    rows = [{"Real value": k, "Masked value": v}
            for k, v in mapping_dict().items()]
    return pd.DataFrame(rows, columns=["Real value", "Masked value"])


st.title("🎨 Power Apps ALM & Masking Tool")
st.caption("Unpack → mask → GitHub + AI revision → unmask → pack. "
           "Everything here runs on this machine; only the masked sources "
           "ever leave it, when you upload them yourself.")

# ------------------------------------------------------------ workflow
with st.container(border=True):
    st.subheader("🗺️ The workflow this tool is built for")
    st.markdown(
        "1. **Unpack** your `.msapp` into a sources folder (Step 1).\n"
        "2. **Define the mapping and mask** the sources — file contents AND "
        "file/folder names (Step 2). Run the leftover scan, then upload "
        "only the masked sources folder to GitHub (or grab the ZIP).\n"
        "3. Let your **AI agent revise / reformat** the app there.\n"
        "4. **Download the revised sources back**, replacing the folder.\n"
        "5. **Diff against the masked baseline** (Step 3) — catch any masked "
        "value the AI renamed or deleted before you unmask.\n"
        "6. **Unmask** (Step 4) and **pack** a new `.msapp` (Step 5), then "
        "import it into Power Apps.\n\n"
        "🔒 **Never upload these to GitHub:** the original `.msapp`, the "
        "mapping file (it maps masked values back to real ones — it *is* "
        "the sensitive data), or the backup folder. The mapping file lives "
        "in this app's `storage/` folder, which the repo `.gitignore` "
        "already excludes — and it is never written inside the sources folder.")
    st.info("⚠️ Masking is exact-text replacement on `.pa.yaml` and `.json` "
            "files only. After masking, always check the verification report "
            "and eyeball the result before uploading — anything not in your "
            "mapping (a new URL, a differently-spelled table name) stays "
            "in the sources as-is.")

# ------------------------------------------------------------ environment
with st.container(border=True):
    st.subheader("🔧 Environment — Power Platform CLI (pac)")
    show_status("env")
    if st.button("Check pac CLI", key=P + "check"):
        info = core.check_pac()
        if info["available"]:
            set_status("env", "success",
                       f"pac is installed"
                       + (f" — version: {info['version']}" if info["version"]
                          else " and answering."))
        else:
            set_status("env", "error", info["hint"])
        st.rerun()
    st.caption("pac must be installed on the machine running Streamlit "
               "(your PC), not on your phone. Unpack / Pack will also tell "
               "you clearly if pac is missing — the app never crashes on it.")

# ------------------------------------------------------------ shared folder
st.header("📁 Sources folder (shared by all steps)")
sources = st.text_input(
    "Unpacked sources folder path",
    placeholder=r"C:\PowerApps\MyApp_sources  (or /home/user/MyApp_sources)",
    help="Step 1 unpacks INTO this folder. Steps 2–4 work ON this folder. "
         "Type it once here; every step below uses it.",
    key=P + "sources")

# ------------------------------------------------------------ step 1: unpack
st.header("① Unpack — .msapp → source code")
with st.container(border=True):
    show_status("unpack")
    mode = st.radio("Source .msapp", ["Local path", "Upload file"],
                    horizontal=True, key=P + "unpack_mode")
    msapp_path = None
    if mode == "Local path":
        msapp_path = st.text_input(
            ".msapp file path",
            placeholder=r"C:\PowerApps\MyApp.msapp",
            key=P + "msapp_in")
    else:
        up = st.file_uploader("Upload a .msapp file", type=["msapp"],
                              key=P + "msapp_up")
        st.caption("The upload is staged to a temporary file only for the "
                   "unpack run — it is not kept by the app.")
    if st.button("📦 Unpack", key=P + "unpack_btn"):
        try:
            if not sources.strip():
                raise core.PacError("Please enter the sources folder path above.")
            if mode == "Upload file":
                if up is None:
                    raise core.PacError("Please upload a .msapp file first.")
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".msapp")
                tmp.write(up.read())
                tmp.close()
                msapp_path = tmp.name
            elif not (msapp_path or "").strip():
                raise core.PacError("Please enter the .msapp file path.")
            with st.spinner("Unpacking… (pac can take a while for large apps)"):
                res = core.unpack_msapp(msapp_path, sources)
            set_status("unpack", "success",
                       f"Unpacked to {sources}. Next: define the mapping and mask (Step 2).")
            st.session_state[P + "log_unpack"] = res["stdout"] + res["stderr"]
        except core.PacError as exc:
            set_status("unpack", "error", str(exc))
        except Exception as exc:  # never crash the app on an unexpected error
            set_status("unpack", "error", f"Unexpected error: {exc}")
        st.rerun()
    log = st.session_state.get(P + "log_unpack")
    if log:
        with st.expander("pac output"):
            st.code(log)

# ------------------------------------------------------------ step 2: mask
st.header("② Mask — hide sensitive data")
with st.container(border=True):
    show_status("mask")
    st.caption("Real value → masked value. Exact text match, case-sensitive. "
               "Longer real values are replaced first, so `TableName` is never "
               "half-eaten by `Table`. File and folder names containing a "
               "real value are renamed too (children before parents); a "
               "rename that would overwrite an existing file is skipped, "
               "never forced.")
    ver = st.session_state.setdefault(P + "editor_ver", 0)
    edited = st.data_editor(
        editor_frame(), num_rows="dynamic", use_container_width=True,
        key=P + f"map_editor_v{ver}")
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("💾 Save mapping", key=P + "map_save"):
            try:
                new_map, bad = {}, []
                for _, row in edited.iterrows():
                    real = str(row["Real value"]).strip() \
                        if str(row["Real value"]) != "nan" else ""
                    masked = str(row["Masked value"]).strip() \
                        if str(row["Masked value"]) != "nan" else ""
                    if not real and not masked:
                        continue
                    if real and not masked:
                        bad.append(real)
                        continue
                    new_map[real] = masked
                if bad:
                    raise core.PacError(
                        "These real values have no masked value: "
                        + ", ".join(bad))
                errors, warnings = core.validate_mapping(new_map) \
                    if new_map else (["The mapping is empty."], [])
                if errors:
                    raise core.PacError(" ".join(errors))
                st.session_state[P + "mapping"] = new_map
                for w in warnings:
                    st.warning(w)
                set_status("mask", "success",
                           f"Mapping saved ({len(new_map)} rows). "
                           "Now run a dry run, then Mask.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            st.rerun()
    with c2:
        map_up = st.file_uploader("Load mapping JSON", type=["json"],
                                  key=P + "map_json_up")
        if st.button("📥 Load this JSON into the editor", key=P + "map_load"):
            try:
                if map_up is None:
                    raise core.PacError("Please choose a mapping JSON file first.")
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
                tmp.write(map_up.read())
                tmp.close()
                loaded = core.load_mapping(tmp.name)
                errors, warnings = core.validate_mapping(loaded)
                if errors:
                    raise core.PacError(" ".join(errors))
                st.session_state[P + "mapping"] = loaded
                st.session_state[P + "editor_ver"] = ver + 1
                for w in warnings:
                    st.warning(w)
                set_status("mask", "success",
                           f"Loaded {len(loaded)} mapping rows into the editor. "
                           "Press “Save mapping” if you edit them, then Mask.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            st.rerun()
    with c3:
        st.download_button(
            "📤 Download current mapping as JSON",
            data=json.dumps(mapping_dict(), indent=2, ensure_ascii=False),
            file_name="mapping.json", mime="application/json",
            key=P + "map_dl")
    st.divider()
    backup = st.checkbox(
        "Back up the sources folder before masking (safety copy in storage/)",
        value=False, key=P + "backup",
        help="Recommended the first time: if anything goes wrong you still "
             "have the pristine sources. The backup stays on this machine.")
    c4, c5 = st.columns(2)
    with c4:
        if st.button("🔍 Dry run — preview what masking would change",
                     key=P + "mask_dry"):
            try:
                if not sources.strip():
                    raise core.PacError("Please enter the sources folder path above.")
                if not mapping_dict():
                    raise core.PacError("The mapping is empty — save at least one row first.")
                report = core.mask_directory(sources, mapping_dict(), dry_run=True)
                rrep = core.rename_paths(sources, mapping_dict(), dry_run=True)
                st.session_state[P + "dry_report"] = report
                st.session_state[P + "dry_renames"] = rrep
                set_status("mask", "info",
                           "Dry run only — nothing was written. Review the "
                           "counts and renames below, then press Mask.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            st.rerun()
    with c5:
        if st.button("🎭 Mask now", key=P + "mask_btn"):
            try:
                if not sources.strip():
                    raise core.PacError("Please enter the sources folder path above.")
                if not mapping_dict():
                    raise core.PacError("The mapping is empty — save at least one row first.")
                if backup:
                    bpath = core.backup_directory(sources, STORAGE / "backups")
                    st.info(f"Backup created: {bpath}")
                with st.spinner("Masking…"):
                    report = core.mask_directory(sources, mapping_dict())
                    rrep = core.rename_paths(sources, mapping_dict())
                mpath = core.save_mapping_state(
                    core.mapping_path_for(sources, STORAGE), mapping_dict(),
                    rrep["renames"])
                spath = core.save_snapshot(
                    core.snapshot_path_for(sources, STORAGE),
                    core.snapshot_directory(sources))
                leftover = core.scan_leftovers(
                    sources, masked_values=list(mapping_dict().values()))
                st.session_state[P + "mask_report"] = report
                st.session_state[P + "mask_renames"] = rrep
                st.session_state[P + "mapping_path"] = str(mpath)
                st.session_state[P + "snapshot_path"] = str(spath)
                st.session_state[P + "leftover"] = leftover
                set_status("mask", "success",
                           f"Masked {report['total']} occurrences in "
                           f"{report['files_changed']} files and renamed "
                           f"{rrep['total']} files/folders. Mapping + rename "
                           f"log saved to {mpath} (local only — never upload "
                           "this file); masked baseline snapshot saved for "
                           "the Diff step. Check the leftover scan below "
                           "before uploading to GitHub.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            except Exception as exc:
                set_status("mask", "error", f"Unexpected error: {exc}")
            st.rerun()
    dry = st.session_state.get(P + "dry_report")
    if dry:
        st.subheader("Dry-run preview")
        show_report(dry)
        dry_r = st.session_state.get(P + "dry_renames")
        if dry_r:
            st.write("Planned filename/folder renames (preview only):")
            show_renames(dry_r)
    rep = st.session_state.get(P + "mask_report")
    if rep:
        st.subheader("Mask result")
        show_report(rep)
        mask_r = st.session_state.get(P + "mask_renames")
        if mask_r:
            show_renames(mask_r)
        show_verification(core.count_occurrences(sources, list(mapping_dict())),
                          "real")
    st.divider()
    st.subheader("🔍 Leftover sensitive-value scan")
    st.caption("Heuristic scan for URLs, emails, domains, SQL connection "
               "strings and IP addresses still in the sources after masking. "
               "Already-masked placeholders are excluded. Run it before "
               "uploading — anything flagged here is something your mapping "
               "missed.")
    if st.button("Scan for leftovers now", key=P + "leftover_btn"):
        try:
            if not sources.strip():
                raise core.PacError("Please enter the sources folder path above.")
            st.session_state[P + "leftover"] = core.scan_leftovers(
                sources, masked_values=list(mapping_dict().values()))
        except core.PacError as exc:
            set_status("mask", "error", str(exc))
        st.rerun()
    leftover = st.session_state.get(P + "leftover")
    if leftover:
        st.write(f"Possible leftovers: **{leftover['total']}** "
                 f"(showing first {len(leftover['findings'])})")
        if leftover["findings"]:
            st.dataframe(leftover["findings"], use_container_width=True,
                         hide_index=True)
            if st.button("➕ Add distinct leftovers to the mapping editor",
                         key=P + "leftover_add"):
                added = 0
                cur = mapping_dict()
                for v in core.distinct_leftovers(leftover):
                    if v not in cur and v not in cur.values():
                        cur[v] = ""
                        added += 1
                st.session_state[P + "editor_ver"] = \
                    st.session_state.get(P + "editor_ver", 0) + 1
                set_status("mask", "info",
                           f"Added {added} leftover values to the editor "
                           "with empty masked values — fill them in, press "
                           "“Save mapping”, then Mask again.")
                st.rerun()
        else:
            st.success("No leftovers found — nothing sensitive-looking "
                       "remains outside the mapping.")
    st.divider()
    st.subheader("📚 Mapping templates")
    st.caption("Save a mapping you reuse across apps (standard SharePoint "
               "URLs, SQL server names, …) and load it back here instead of "
               "retyping rows. Templates live in gitignored storage — they "
               "hold real values, so never upload them either.")
    tpl_name = st.text_input("Template name", key=P + "tpl_name",
                             placeholder="e.g. company-standard")
    tc1, tc2, tc3 = st.columns(3)
    with tc1:
        if st.button("💾 Save current mapping as template", key=P + "tpl_save"):
            try:
                core.save_template(STORAGE, tpl_name, mapping_dict())
                set_status("mask", "success",
                           f"Template “{tpl_name}” saved.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            st.rerun()
    existing = core.list_templates(STORAGE)
    with tc2:
        sel = st.selectbox("Saved templates", existing or ["(none yet)"],
                           key=P + "tpl_sel")
        if st.button("📥 Load template into editor", key=P + "tpl_load"):
            try:
                if not existing:
                    raise core.PacError("No templates saved yet.")
                loaded = core.load_template(STORAGE, sel)
                st.session_state[P + "mapping"] = loaded
                st.session_state[P + "editor_ver"] = \
                    st.session_state.get(P + "editor_ver", 0) + 1
                set_status("mask", "success",
                           f"Template “{sel}” loaded ({len(loaded)} rows). "
                           "Press “Save mapping” if you edit it.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            st.rerun()
    with tc3:
        if st.button("🗑️ Delete template", key=P + "tpl_del"):
            try:
                if not existing:
                    raise core.PacError("No templates saved yet.")
                core.delete_template(STORAGE, sel)
                set_status("mask", "success", f"Template “{sel}” deleted.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            st.rerun()
    st.divider()
    st.subheader("📦 Masked-sources ZIP")
    st.caption("For a quick one-off (no Git): export the masked folder as a "
               "zip you can drop into an LLM chat. The zip excludes `.git` "
               "and any mapping-state file.")
    if st.button("Prepare ZIP for download", key=P + "zip_prep"):
        try:
            if not sources.strip():
                raise core.PacError("Please enter the sources folder path above.")
            st.session_state[P + "zip_bytes"] = core.zip_sources_bytes(sources)
            st.session_state[P + "zip_name"] = \
                f"{Path(sources).name}_masked.zip"
        except core.PacError as exc:
            set_status("mask", "error", str(exc))
        st.rerun()
    zip_bytes = st.session_state.get(P + "zip_bytes")
    if zip_bytes:
        st.download_button("⬇️ Download masked sources ZIP",
                           data=zip_bytes,
                           file_name=st.session_state[P + "zip_name"],
                           mime="application/zip", key=P + "zip_dl")

# ------------------------------------------------------------ step 3: diff
def _load_diff_mapping():
    """Mapping for the Diff step: uploaded override wins, else saved state."""
    if diff_up is not None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(diff_up.read())
        tmp.close()
        return core.load_mapping(tmp.name)
    if not sources.strip():
        raise core.PacError("Please enter the sources folder path above.")
    path = core.mapping_path_for(sources, STORAGE)
    if not path.is_file():
        raise core.PacError(
            f"No saved mapping found for this sources folder ({path}). "
            "Mask from this app first (Step 2), or upload the mapping JSON below.")
    return core.load_mapping(path)


st.header("③ Diff — review AI changes before unmasking")
with st.container(border=True):
    show_status("diff")
    st.caption("Compares the current sources folder against the masked "
               "baseline snapshot saved at Mask time. Do this AFTER "
               "downloading the AI-revised sources and BEFORE unmasking. "
               "The critical flag is an orphaned masked value: the AI "
               "renamed or deleted it, so Unmask cannot restore it — fix "
               "that in the sources first.")
    snap_path = core.snapshot_path_for(sources, STORAGE) if sources.strip() else None
    st.write("Baseline snapshot:")
    st.code(str(snap_path) if snap_path else "(enter the sources folder above)")
    diff_up = st.file_uploader(
        "Or load a different mapping JSON for the orphan check (optional)",
        type=["json"], key=P + "diff_map_up")
    if st.button("🔍 Compare against masked baseline", key=P + "diff_btn"):
        try:
            mapping = _load_diff_mapping()
            snap = core.load_snapshot(
                core.snapshot_path_for(sources, STORAGE))
            d = core.diff_against_snapshot(sources, snap, mapping)
            st.session_state[P + "diff_report"] = d
            set_status("diff", "success" if not d["orphaned_masked"] else "error",
                       f"Added: {d['counts']['added']} · removed: "
                       f"{d['counts']['removed']} · modified: "
                       f"{d['counts']['modified']} · renamed: "
                       f"{d['counts']['renamed']} · orphaned masked values: "
                       f"{d['counts']['orphaned']}.")
        except core.PacError as exc:
            set_status("diff", "error", str(exc))
        st.rerun()
    d = st.session_state.get(P + "diff_report")
    if d:
        if d["orphaned_masked"]:
            st.error("⚠️ Orphaned masked values — the AI renamed or deleted "
                     "these, so Unmask cannot restore them. Fix them in the "
                     "sources (or extend the mapping) before unmasking:")
            st.dataframe(d["orphaned_masked"], use_container_width=True,
                         hide_index=True)
        else:
            st.success("No orphaned masked values — every masked value is "
                       "still present, so Unmask can restore them all.")
        if d["renamed"]:
            st.write("Renamed files (same content, new name):")
            st.dataframe([{"from": a, "to": b} for a, b in d["renamed"]],
                         use_container_width=True, hide_index=True)
        for label, items in (("Added files", d["added"]),
                             ("Removed files", d["removed"]),
                             ("Modified files", d["modified"])):
            if items:
                st.write(f"{label} ({len(items)}):")
                st.write(items)
        for p, text in d["diffs"].items():
            with st.expander(f"Diff: {p}"):
                st.code(text)

# ------------------------------------------------------------ step 4: unmask
def _load_unmask_mapping():
    """Mapping for unmasking: uploaded override wins, else the saved file."""
    if un_up is not None:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.write(un_up.read())
        tmp.close()
        return core.load_mapping(tmp.name)
    if not sources.strip():
        raise core.PacError("Please enter the sources folder path above.")
    path = core.mapping_path_for(sources, STORAGE)
    if not path.is_file():
        raise core.PacError(
            f"No saved mapping found for this sources folder ({path}). "
            "Mask from this app first (Step 2), or upload the mapping JSON above.")
    return core.load_mapping(path)


st.header("④ Unmask — restore real data")
with st.container(border=True):
    show_status("unmask")
    st.caption("One click. Loads the mapping saved during masking, reverses "
               "it, and restores the original values — file and folder names "
               "first (parents before children), then file contents. Use "
               "this after you download the AI-revised sources back from "
               "GitHub and have reviewed the Diff (Step 3).")
    auto_path = core.mapping_path_for(sources, STORAGE) if sources.strip() else None
    st.write("Mapping file used:")
    st.code(str(auto_path) if auto_path else "(enter the sources folder above)")
    un_up = st.file_uploader(
        "Or load a different mapping JSON (optional override)",
        type=["json"], key=P + "unmap_up")
    c6, c7 = st.columns(2)
    with c6:
        if st.button("🔍 Preview restore (dry run)", key=P + "unmask_dry"):
            try:
                mapping = _load_unmask_mapping()
                rrep = core.rename_paths(
                    sources, core.reverse_mapping(mapping),
                    dry_run=True, topdown=True)
                report = core.unmask_directory(sources, mapping, dry_run=True)
                st.session_state[P + "unmask_dry_renames"] = rrep
                st.session_state[P + "unmask_dry_report"] = report
                set_status("unmask", "info",
                           "Dry run only — nothing was written.")
            except core.PacError as exc:
                set_status("unmask", "error", str(exc))
            st.rerun()
    with c7:
        if st.button("↩️ Restore original values", key=P + "unmask_btn"):
            try:
                mapping = _load_unmask_mapping()
                with st.spinner("Restoring…"):
                    rrep = core.rename_paths(
                        sources, core.reverse_mapping(mapping), topdown=True)
                    report = core.unmask_directory(sources, mapping)
                st.session_state[P + "unmask_renames"] = rrep
                st.session_state[P + "unmask_report"] = report
                st.session_state[P + "unmask_mapping"] = mapping
                set_status("unmask", "success",
                           f"Restored {report['total']} occurrences in "
                           f"{report['files_changed']} files and renamed "
                           f"{rrep['total']} files/folders back. Next: pack "
                           "(Step 5).")
            except core.PacError as exc:
                set_status("unmask", "error", str(exc))
            except Exception as exc:
                set_status("unmask", "error", f"Unexpected error: {exc}")
            st.rerun()
    udry = st.session_state.get(P + "unmask_dry_report")
    if udry:
        st.subheader("Restore preview")
        show_report(udry)
        udry_r = st.session_state.get(P + "unmask_dry_renames")
        if udry_r:
            st.write("Planned filename/folder restores (preview only):")
            show_renames(udry_r)
    urep = st.session_state.get(P + "unmask_report")
    if urep:
        st.subheader("Restore result")
        show_report(urep)
        urep_r = st.session_state.get(P + "unmask_renames")
        if urep_r:
            show_renames(urep_r)
        show_verification(
            core.count_occurrences(
                sources, list(st.session_state[P + "unmask_mapping"].values())),
            "masked")


# ------------------------------------------------------------ step 5: pack
st.header("⑤ Pack — source code → .msapp")
with st.container(border=True):
    show_status("pack")
    out_path = st.text_input(
        "Output .msapp file path",
        placeholder=r"C:\PowerApps\MyApp_updated.msapp",
        help="The new .msapp is built from the (unmasked) sources folder "
             "above. Use a new filename so the original stays untouched.",
        key=P + "pack_out")
    if st.button("📦 Pack", key=P + "pack_btn"):
        try:
            if not sources.strip():
                raise core.PacError("Please enter the sources folder path above.")
            if not (out_path or "").strip():
                raise core.PacError("Please enter an output .msapp path.")
            with st.spinner("Packing… (pac can take a while for large apps)"):
                res = core.pack_msapp(sources, out_path)
            set_status("pack", "success",
                       f"Packed to {out_path}. Import this file into Power Apps.")
            st.session_state[P + "log_pack"] = res["stdout"] + res["stderr"]
        except core.PacError as exc:
            set_status("pack", "error", str(exc))
        except Exception as exc:
            set_status("pack", "error", f"Unexpected error: {exc}")
        st.rerun()
    log = st.session_state.get(P + "log_pack")
    if log:
        with st.expander("pac output"):
            st.code(log)

st.caption("Tip: after the AI revises the code on GitHub, download the "
           "revised sources and diff them against your masked copy before "
           "unmasking — if the AI renamed a masked value, unmasking cannot "
           "restore it, and you will want to catch that in the diff.")
