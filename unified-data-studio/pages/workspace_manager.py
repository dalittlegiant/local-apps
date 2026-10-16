"""Workspace Data Manager — the central data control plane.

Overview of every module backed by the central ``workspace_master.db``
(code snippets, study notes, meeting requirements, prompt templates, mask
dictionary): live record counts, linked-folder location, one-click backup
download, and backup restore. The database auto-loads on startup and
auto-saves on every edit, so all modules always see the same data.
"""

from datetime import datetime

import streamlit as st

import workspace_db

P = "wsm_"  # session-state prefix: state is global across MPA pages

st.header("💾 Workspace Data Manager")
st.caption("One central database — `workspace_master.db` — holds the records "
           "of every storage-backed module. It auto-loads on startup and "
           "auto-saves on every edit.")

con = workspace_db.open_workspace()

# ------------------------------------------------------------ overview
st.subheader("① Overview")
counts = workspace_db.record_counts(con)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Code snippets", counts["snippets"])
c2.metric("Study notes", counts["notes"])
c3.metric("Requirements", counts["requirements"])
c4.metric("Prompt templates", counts["prompt_templates"])
c5.metric("Mask-map entries", counts["mask_map"])

db_path = workspace_db.resolve_db_path()
linked = workspace_db.link_file().exists()
st.caption(f"Effective database: `{db_path}`")
if linked:
    st.success("📁 Linked folder is active — the database lives in your "
               "chosen folder.")
else:
    st.info("Using the default location (`<repo>/workspace/`). Link a folder "
            "below to move it.")

other_links = con.execute(
    "SELECT key, value FROM app_meta WHERE key LIKE '%_linked_folder' "
    "ORDER BY key").fetchall()
if other_links:
    with st.expander("🔗 Other linked data folders"):
        for r in other_links:
            st.caption(f"`{r['key']}` → `{r['value']}`")

# ------------------------------------------------------------ linked folder
st.subheader("② Linked folder")
st.markdown(
    "Point the workspace database at a folder you own (e.g. a synced drive). "
    "The database **auto-loads from there on startup** and **auto-saves on "
    "every edit** — every module sees the same data. The current database is "
    "copied over the first time; a database already in the folder is never "
    "overwritten.")
folder = st.text_input("Folder path", key=P + "link_folder",
                       placeholder=r"C:\Data\Workspace  or  /home/user/workspace")
b1, b2 = st.columns(2)
with b1:
    if st.button("📁 Set linked folder", type="primary", key=P + "link_set"):
        try:
            eff = workspace_db.set_linked_folder(folder.strip())
            st.success(f"Linked. Database now lives at `{eff}`.")
            st.rerun()
        except ValueError as e:
            st.error(f"⚠️ {e}")
with b2:
    if st.button("✖ Clear linked folder", key=P + "link_clear",
                 disabled=not linked):
        workspace_db.clear_linked_folder()
        st.success("Link cleared — back to the default location.")
        st.rerun()

# ------------------------------------------------------------ backup
st.subheader("③ Backup")
st.markdown("Download a timestamped copy of the whole workspace database. "
            "Keep it somewhere safe — restore (below) brings it back.")
try:
    blob = workspace_db.backup_bytes()
    fname = f"workspace_master_backup_{datetime.now():%Y%m%d}.db"
    st.download_button("⬇️ Download backup", data=blob, file_name=fname,
                       mime="application/x-sqlite3", key=P + "dl")
except OSError as e:
    st.error(f"⚠️ Could not read the database file: {e}")

# ------------------------------------------------------------ restore
st.subheader("④ Restore")
st.markdown("Upload a backup `.db` file. It is validated first; the current "
            "database is automatically backed up beside itself before the "
            "restore replaces it.")
up = st.file_uploader("Workspace backup (.db)", type=["db"], key=P + "up")
if up and st.button("♻️ Restore from backup", type="primary", key=P + "go"):
    try:
        con.close()
        installed = workspace_db.restore_bytes(up.getvalue())
        st.success(f"Restored `{installed.name}`. Reloading…")
        st.rerun()
    except ValueError as e:
        st.error(f"⚠️ {e}")
        con = workspace_db.open_workspace()

# ------------------------------------------------------------ legacy note
st.divider()
st.caption("ℹ️ Legacy per-app storage files (`storage/vault.db`, "
           "`storage/meetings.db`, `storage/prompt_templates.json`, "
           "`storage/mask_map.json`) were imported into the central database "
           "once, automatically. You can leave them alone — the apps now read "
           "and write the central database.")
