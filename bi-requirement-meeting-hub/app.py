"""App 9 — BI Requirement & Meeting Hub.

1. Structured requirement capture stored in local SQLite.
2. Interactive triage board (filter + edit + delete via st.data_editor).
3. One-click meeting minutes & follow-up generator (Markdown / Email /
   Teams), grouped into confirmed / under review / not feasible / open.

Pure logic lives in meeting_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import meeting_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="BI Requirement & Meeting Hub", page_icon="🤝", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "mt9_"
EDIT_COLS = ["id", "project", "meeting_date", "stakeholder", "action_type",
             "feasibility_status", "title", "detail", "technical_notes"]


def _con():
    if P + "con" not in st.session_state:
        st.session_state[P + "con"] = core.connect()
    return st.session_state[P + "con"]


st.title("🤝 BI Requirement & Meeting Hub")
st.caption("Capture dashboard-review requests, triage feasibility, and "
           "generate stakeholder follow-ups — stored locally in SQLite.")

tab_cap, tab_tri, tab_min = st.tabs(
    ["📝 Capture", "🗂️ Triage Board", "📄 Minutes Generator"])

# ========================================================== TAB 1 ===
with tab_cap:
    st.header("Log a requirement")
    with st.container(border=True):
        with st.form(P + "form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                project = st.text_input("Project / Dashboard *",
                                        placeholder="e.g. Sales Performance Dashboard")
                meeting_date = st.date_input("Meeting date", value=date.today())
                stakeholder = st.text_input("Stakeholder",
                                            placeholder="Who raised it?")
            with c2:
                action_type = st.selectbox("Action type", core.ACTION_TYPES,
                                           help="Change: modify existing. Remove: delete. "
                                                "Suggestion: new idea. To Confirm: needs investigation.")
                feasibility = st.selectbox("Feasibility status", core.FEASIBILITY)
            title = st.text_input("Title *", placeholder="e.g. Add YoY column to sales table")
            detail = st.text_area("Detail", placeholder="What exactly was asked?")
            tech = st.text_area("Technical notes",
                                placeholder="If blocked: why (e.g. data siloed across domains). "
                                            "If feasible: implementation notes.")
            if st.form_submit_button("💾 Save requirement", type="primary"):
                try:
                    rid = core.add_requirement(
                        _con(), project, meeting_date.isoformat(), stakeholder,
                        action_type, feasibility, title, detail, tech)
                    st.success(f"Saved as #{rid}.")
                except ValueError as e:
                    st.error(f"⚠️ {e}")

# ========================================================== TAB 2 ===
with tab_tri:
    st.header("Triage board")
    con = _con()
    with st.container(border=True):
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            fp = st.selectbox("Dashboard", ["(all)"] + core.distinct(con, "project"),
                              key=P + "fp")
        with f2:
            fd = st.selectbox("Meeting date", ["(all)"] + core.distinct(con, "meeting_date"),
                              key=P + "fd")
        with f3:
            fa = st.selectbox("Action type", ["(all)"] + list(core.ACTION_TYPES),
                              key=P + "fa")
        with f4:
            ff = st.selectbox("Feasibility", ["(all)"] + list(core.FEASIBILITY),
                              key=P + "ff")
        fs = st.text_input("🔍 Search title / detail / notes / stakeholder",
                           key=P + "fs")

    rows = core.list_requirements(
        con,
        project=None if fp == "(all)" else fp,
        meeting_date=None if fd == "(all)" else fd,
        action_type=None if fa == "(all)" else fa,
        feasibility_status=None if ff == "(all)" else ff,
        search=fs)
    st.caption(f"{len(rows)} item(s). Edit cells directly, then Save. "
               "Tick ✖ to mark rows for deletion.")

    if rows:
        with st.container(border=True):
            df = pd.DataFrame(rows)[EDIT_COLS]
            df["✖"] = False
            edited = st.data_editor(
                df, use_container_width=True, hide_index=True, key=P + "board",
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "action_type": st.column_config.SelectboxColumn(
                        "Action", options=list(core.ACTION_TYPES)),
                    "feasibility_status": st.column_config.SelectboxColumn(
                        "Feasibility", options=list(core.FEASIBILITY)),
                    "title": st.column_config.TextColumn("Title", width="medium"),
                    "detail": st.column_config.TextColumn("Detail", width="large"),
                    "technical_notes": st.column_config.TextColumn(
                        "Technical notes", width="large"),
                })
            b1, b2 = st.columns(2)
            with b1:
                if st.button("💾 Save changes", type="primary", key=P + "save"):
                    orig = {r["id"]: r for r in rows}
                    n = 0
                    for _, row in edited.iterrows():
                        rid = int(row["id"])
                        o = orig[rid]
                        diff = {c: ("" if pd.isna(row[c]) else str(row[c]))
                                for c in EDIT_COLS[1:]
                                if str(o[c] or "") !=
                                ("" if pd.isna(row[c]) else str(row[c]))}
                        if diff:
                            core.update_requirement(con, rid, diff)
                            n += 1
                    st.success(f"Updated {n} record(s).")
                    st.rerun()
            with b2:
                if st.button("🗑️ Delete ticked", key=P + "del"):
                    rids = edited.loc[edited["✖"], "id"].astype(int).tolist()
                    if rids:
                        core.delete_requirements(con, rids)
                        st.success(f"Deleted {len(rids)} record(s).")
                        st.rerun()
                    else:
                        st.info("Tick the ✖ column on rows to delete.")
    else:
        with st.container(border=True):
            st.subheader("📭 No items here yet")
            st.markdown("1. Go to the **📝 Capture** tab and log your first requirement.\n"
                        "2. Come back here to filter, edit, and triage it.\n"
                        "3. When ready, use the **📄 Minutes Generator** to build your follow-up.")

# ========================================================== TAB 3 ===
with tab_min:
    st.header("Meeting minutes & follow-up generator")
    con = _con()
    with st.container(border=True):
        scope_kind = st.radio("Scope", ("Meeting date", "Dashboard"),
                              horizontal=True, key=P + "scope_kind")
        if scope_kind == "Meeting date":
            opts = core.distinct(con, "meeting_date")
            scope_val = st.selectbox("Meeting", opts, key=P + "scope_val")
            rows = core.list_requirements(con, meeting_date=scope_val) if scope_val else []
            scope = f"meeting {scope_val}"
        else:
            opts = core.distinct(con, "project")
            scope_val = st.selectbox("Dashboard", opts, key=P + "scope_val2")
            rows = core.list_requirements(con, project=scope_val) if scope_val else []
            scope = scope_val or ""

    if not rows:
        with st.container(border=True):
            st.subheader("📭 Nothing to summarize yet")
            st.markdown("1. Log requirements in the **📝 Capture** tab.\n"
                        "2. Pick a **Meeting date** or **Dashboard** scope above.\n"
                        "3. Click **✨ Generate minutes** for a grouped follow-up.")
    elif st.button("✨ Generate minutes", type="primary", key=P + "gen"):
        st.session_state[P + "minutes"] = core.generate_minutes(rows, scope)

    mins = st.session_state.get(P + "minutes")
    if mins:
        c = mins["counts"]
        with st.container(border=True):
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("✅ Confirmed", c["confirmed"])
            m2.metric("💡 Under review", c["suggestions"])
            m3.metric("🚫 Not feasible", c["blocked"])
            m4.metric("❓ Open", c["open"])
        with st.container(border=True):
            t1, t2, t3 = st.tabs(["Markdown", "Email", "Teams"])
            with t1:
                st.markdown(mins["markdown"])
                st.download_button("⬇️ minutes.md",
                                   mins["markdown"].encode("utf-8"),
                                   "minutes.md", "text/markdown",
                                   key=P + "dl_md")
            with t2:
                st.text_input("Subject", value=mins["email_subject"],
                              key=P + "em_subj")
                st.code(mins["email"], language="text")
            with t3:
                st.code(mins["teams"], language="text")
