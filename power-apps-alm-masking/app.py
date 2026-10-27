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
        "2. **Define the mapping** and **mask** the sources (Step 2).\n"
        "3. **Upload only the masked sources folder to GitHub** and let your "
        "AI agent revise / reformat the app there.\n"
        "4. **Download the revised sources back**, replacing the folder.\n"
        "5. **Unmask** (Step 3) and **pack** a new `.msapp` (Step 4), then "
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
               "half-eaten by `Table`.")
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
                st.session_state[P + "dry_report"] = report
                set_status("mask", "info",
                           "Dry run only — nothing was written. Review the "
                           "counts below, then press Mask.")
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
                mpath = core.save_mapping(
                    core.mapping_path_for(sources, STORAGE), mapping_dict())
                st.session_state[P + "mask_report"] = report
                st.session_state[P + "mapping_path"] = str(mpath)
                set_status("mask", "success",
                           f"Masked {report['total']} occurrences in "
                           f"{report['files_changed']} files. Mapping saved to "
                           f"{mpath} (local only — never upload this file). "
                           "The sources folder is now safe to upload to GitHub.")
            except core.PacError as exc:
                set_status("mask", "error", str(exc))
            except Exception as exc:
                set_status("mask", "error", f"Unexpected error: {exc}")
            st.rerun()
    dry = st.session_state.get(P + "dry_report")
    if dry:
        st.subheader("Dry-run preview")
        show_report(dry)
    rep = st.session_state.get(P + "mask_report")
    if rep:
        st.subheader("Mask result")
        show_report(rep)
        show_verification(core.count_occurrences(sources, list(mapping_dict())),
                          "real")

# ------------------------------------------------------------ step 3: unmask
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


st.header("③ Unmask — restore real data")
with st.container(border=True):
    show_status("unmask")
    st.caption("One click. Loads the mapping saved during masking, reverses "
               "it, and restores the original values. Use this after you "
               "download the AI-revised sources back from GitHub.")
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
                report = core.unmask_directory(sources, mapping, dry_run=True)
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
                    report = core.unmask_directory(sources, mapping)
                st.session_state[P + "unmask_report"] = report
                st.session_state[P + "unmask_mapping"] = mapping
                set_status("unmask", "success",
                           f"Restored {report['total']} occurrences in "
                           f"{report['files_changed']} files. Next: pack (Step 4).")
            except core.PacError as exc:
                set_status("unmask", "error", str(exc))
            except Exception as exc:
                set_status("unmask", "error", f"Unexpected error: {exc}")
            st.rerun()
    udry = st.session_state.get(P + "unmask_dry_report")
    if udry:
        st.subheader("Restore preview")
        show_report(udry)
    urep = st.session_state.get(P + "unmask_report")
    if urep:
        st.subheader("Restore result")
        show_report(urep)
        show_verification(
            core.count_occurrences(
                sources, list(st.session_state[P + "unmask_mapping"].values())),
            "masked")


# ------------------------------------------------------------ step 4: pack
st.header("④ Pack — source code → .msapp")
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
