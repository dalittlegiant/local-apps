"""App 2 — Security Command Center (platform-agnostic).

A general data-governance tool: access rule mapping, personnel delta
tracking, and local access auditing. The engine maps people
(Work Email / Department / Position) to assets via a rule book — it was
born as a Power BI RLS tool, but the logic is asset-agnostic: Department
holds asset codes, Report_Access holds any named grants (reports, folders,
shares, ...).

Pure logic lives in lib/rules_engine.py + lib/csv_loader.py (ported from
the standalone Security & Governance Command Center v4 — same column
contracts, so existing files keep working).
"""

from datetime import date

import pandas as pd
import streamlit as st

from lib.csv_loader import (
    DEPT, EMAIL, POS, REPORT_ACCESS, STORE_ACCESS, STORE_NAME,
    read_hr_excel, read_table_upload,
)
from lib.rules_engine import (
    check_unmapped_master_data, compute_deltas, gap_analysis,
    sample_exceptions, sample_rule_book, sample_store_master, simulate_rls,
)

P = "sec_"  # session-state prefix: state is global across MPA pages


def _init():
    for key, default in [
        ("hr_current", None),
        ("hr_current_name", ""),
        ("store_master_current", None),
        ("audit_log", pd.DataFrame(
            columns=["Date", EMAIL, "Asset_Name", "Permission_Level", "Remark"])),
        ("final_rls", None),
        ("delta_res", None),
        ("gap_res", None),
    ]:
        if P + key not in st.session_state:
            st.session_state[P + key] = default


def _warn_unmapped(new_pos: list[str], new_dept: list[str]) -> None:
    if new_pos or new_dept:
        details = []
        if new_pos:
            details.append(f"Positions: {', '.join(new_pos)}")
        if new_dept:
            details.append(f"Departments: {', '.join(new_dept)}")
        st.error(
            "🚨 **New Position/Department detected in HR List. "
            "Please update the Rule Book to assign access logic.**\n\n"
            + "\n".join(details)
        )


_init()

# ---- sidebar: schema mapping (page-scoped, below the launcher nav) ----
with st.sidebar:
    st.header("⚙️ Schema Mapping")
    st.caption("Map your raw HR column names to the required columns. "
               "Defaults match the standard template.")
    map_email = st.text_input("HR column → Work Email", value=EMAIL, key="sec_map_email")
    map_dept = st.text_input("HR column → Department", value=DEPT, key="sec_map_dept")
    map_pos = st.text_input("HR column → Position", value=POS, key="sec_map_pos")
schema_mapping = {EMAIL: map_email.strip(), DEPT: map_dept.strip(), POS: map_pos.strip()}

st.title("🛡️ Security Command Center")
st.caption("Local-only governance: access rules · personnel deltas · audit & gap analysis. "
           "Platform-agnostic — Power BI, file shares, or any asset model. Nothing leaves this machine.")

tab_rls, tab_delta, tab_audit, tab_query = st.tabs(
    ["🔐 Rule Engine", "🔄 Delta Tracking", "📋 Access Audit & Gap Analysis",
     "🔍 Access Query Tool"]
)

# ------------------------------------------------------- TAB 1: RULES ---
with tab_rls:
    st.header("Simulate & Combine → access table")
    st.caption(
        "Upload the HR Staff List (Excel), the Rule_Book (Department as asset "
        "code + Position → asset & report access), optional Exceptions, and an "
        "asset master for friendly names. Multi-asset cells use ':' and are "
        "exploded into one row per asset. CSVs are read with encoding "
        "auto-detection (utf-8-sig → cp1252); Excel avoids encoding issues."
    )
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            hr_up = st.file_uploader("HR Staff List (.xlsx)", type=["xlsx", "xls"], key="sec_rls_hr")
            rules_up = st.file_uploader("Rule_Book (.csv / .xlsx)", type=["csv", "xlsx", "xls"],
                                        key="sec_rls_rules")
        with c2:
            ex_up = st.file_uploader("Exceptions (.csv / .xlsx, optional)",
                                     type=["csv", "xlsx", "xls"], key="sec_rls_ex")
            sm_up = st.file_uploader("Asset_Master (.csv / .xlsx, optional)",
                                     type=["csv", "xlsx", "xls"], key="sec_rls_sm")

    with st.expander("📥 Download template files"):
        st.download_button("Rule_Book template",
                           sample_rule_book().to_csv(index=False).encode("utf-8-sig"),
                           "Rule_Book_template.csv", "text/csv", key="sec_tpl_rules")
        st.download_button("Exceptions template",
                           sample_exceptions().to_csv(index=False).encode("utf-8-sig"),
                           "Exceptions_template.csv", "text/csv", key="sec_tpl_ex")
        st.download_button("Asset_Master template",
                           sample_store_master().to_csv(index=False).encode("utf-8-sig"),
                           "Asset_Master_template.csv", "text/csv", key="sec_tpl_sm")

    if st.button("▶️ Simulate & Combine", type="primary", key="sec_rls_go"):
        if not hr_up or not rules_up:
            st.error("Please upload both the HR Staff List and the Rule_Book.")
        else:
            try:
                hr = read_hr_excel(hr_up, schema_mapping)
                rules = read_table_upload(rules_up)
                ex = read_table_upload(ex_up) if ex_up else None
                sm = read_table_upload(sm_up) if sm_up else None
                _warn_unmapped(*check_unmapped_master_data(hr, rules))
                final, warns = simulate_rls(hr, rules, ex, sm)
                st.session_state[P + "final_rls"] = final
                st.session_state[P + "hr_current"] = hr
                st.session_state[P + "hr_current_name"] = hr_up.name
                st.session_state[P + "store_master_current"] = sm
                for w in warns:
                    st.warning(w)
                n_people = final[EMAIL].nunique()
                n_exc = (final["Source"] == "Exception").sum()
                st.success(f"✅ {n_people} staff → {len(final)} access rows "
                           f"({n_exc} exception rows).")
            except ValueError as e:
                st.error(f"⚠️ {e}")
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")

    final = st.session_state[P + "final_rls"]
    if final is not None:
        with st.container(border=True):
            st.subheader("Access table preview (one row per user per asset)")
            st.dataframe(final, use_container_width=True)
            st.download_button("⬇️ Download access table (CSV)",
                               final.to_csv(index=False).encode("utf-8-sig"),
                               "Access_Table.csv", "text/csv", key="sec_rls_dl")
    else:
        with st.container(border=True):
            st.subheader("Get started")
            st.markdown(
                "1. Upload the **HR Staff List** and the **Rule_Book** above "
                "(Exceptions and Asset_Master are optional).\n"
                "2. Click **▶️ Simulate & Combine** — the access table appears here.\n"
                "3. Download it as CSV, then use the other tabs for deltas, "
                "audits, and queries."
            )

# ----------------------------------------------------- TAB 2: DELTA ---
with tab_delta:
    st.header("Personnel Movement — Joiners / Leavers / Movers")
    st.caption("Upload the previous HR list and the new HR list. Leavers are "
               "flagged for access revocation; joiners get suggested access "
               "from the Rule_Book.")
    with st.container(border=True):
        d1, d2, d3 = st.columns(3)
        with d1:
            old_up = st.file_uploader("Previous HR List (.xlsx)", type=["xlsx", "xls"],
                                      key="sec_delta_old")
        with d2:
            new_up = st.file_uploader("New HR List (.xlsx)", type=["xlsx", "xls"],
                                      key="sec_delta_new")
        with d3:
            delta_rules_up = st.file_uploader("Rule_Book (.csv / .xlsx)",
                                              type=["csv", "xlsx", "xls"],
                                              key="sec_delta_rules")

    if st.button("🔍 Compare", type="primary", key="sec_delta_go"):
        if not old_up or not new_up:
            st.error("Please upload both the previous and the new HR list.")
        else:
            try:
                old = read_hr_excel(old_up, schema_mapping)
                new = read_hr_excel(new_up, schema_mapping)
                rules = read_table_upload(delta_rules_up) if delta_rules_up else None
                sm = st.session_state[P + "store_master_current"]
                if rules is not None:
                    _warn_unmapped(*check_unmapped_master_data(new, rules))
                res = compute_deltas(old, new, rules, sm)
                st.session_state[P + "delta_res"] = res
                st.session_state[P + "hr_current"] = new
                st.session_state[P + "hr_current_name"] = new_up.name
            except ValueError as e:
                st.error(f"⚠️ {e}")
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")

    res = st.session_state[P + "delta_res"]
    if res:
        with st.container(border=True):
            leavers, joiners, movers = res["leavers"], res["joiners"], res["movers"]
            if not leavers.empty:
                st.error(f"🚨 **{len(leavers)} Leaver(s)** — revoke their access now:")
                show = [c for c in [EMAIL, DEPT, POS] if c in leavers.columns]
                st.dataframe(leavers[show], use_container_width=True)
            else:
                st.success("No leavers detected. ✅")
            st.divider()
            if not joiners.empty:
                st.warning(f"👋 **{len(joiners)} Joiner(s)** — provision access:")
                show = [c for c in [EMAIL, DEPT, POS, STORE_ACCESS, STORE_NAME,
                                    REPORT_ACCESS, "Source"] if c in joiners.columns]
                st.dataframe(joiners[show], use_container_width=True)
            else:
                st.success("No joiners detected. ✅")
            st.divider()
            if not movers.empty:
                st.warning(f"🔀 **{len(movers)} Mover(s)** — department or position changed:")
                st.dataframe(movers, use_container_width=True)
            else:
                st.success("No movers detected. ✅")
    else:
        with st.container(border=True):
            st.subheader("Get started")
            st.markdown(
                "1. Upload the **previous** and **new** HR lists above "
                "(a Rule_Book is optional but enables access suggestions).\n"
                "2. Click **🔍 Compare** — joiners, leavers, and movers appear here.\n"
                "3. Leavers are flagged for access revocation."
            )

# ----------------------------------------------------- TAB 3: AUDIT ---
with tab_audit:
    st.header("Access Audit Register & Gap Analysis")
    st.caption("Log manually granted access below. Gap Analysis cross-checks "
               "what staff *should* have (HR + Rule_Book) against what they "
               "*actually* have — compared strictly on the Work Email column.")

    with st.container(border=True):
        st.subheader("➕ Log granted access")
        with st.form("sec_audit_form", clear_on_submit=True):
            f1, f2 = st.columns(2)
            with f1:
                a_date = st.date_input("Date", value=date.today())
                a_email = st.text_input("Work Email").strip()
                a_remark = st.text_input("Remark (justification for this access)").strip()
            with f2:
                a_asset = st.text_input("Asset_Name (e.g. Sales Dashboard)").strip()
                a_perm = st.selectbox("Permission_Level",
                                      ["Viewer", "Contributor", "Member", "Admin"])
            if st.form_submit_button("Add entry"):
                if not a_email or not a_asset:
                    st.error("Work Email and Asset_Name are required.")
                else:
                    row = pd.DataFrame([{
                        "Date": a_date.isoformat(), EMAIL: a_email,
                        "Asset_Name": a_asset, "Permission_Level": a_perm,
                        "Remark": a_remark,
                    }])
                    st.session_state[P + "audit_log"] = pd.concat(
                        [st.session_state[P + "audit_log"], row], ignore_index=True)
                    st.success("Entry logged.")

    with st.container(border=True):
        st.subheader("📜 Audit log")
        audit = st.session_state[P + "audit_log"]
        if not audit.empty:
            st.dataframe(audit, use_container_width=True)
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download Access_Audit.csv",
                    audit.to_csv(index=False).encode("utf-8-sig"),
                    "Access_Audit.csv", "text/csv", key="sec_audit_dl")
            with c2:
                audit_up = st.file_uploader(
                    "…or load an existing Access_Audit (.csv / .xlsx)",
                    type=["csv", "xlsx", "xls"], key="sec_audit_load")
                if audit_up:
                    try:
                        from lib.csv_loader import _require_cols
                        loaded = read_table_upload(audit_up)
                        _require_cols(loaded, ["Date", EMAIL, "Asset_Name",
                                               "Permission_Level"], "Access_Audit")
                        if "Remark" not in loaded.columns:
                            loaded["Remark"] = ""
                        st.session_state[P + "audit_log"] = loaded
                        st.success(f"Loaded {len(loaded)} audit rows.")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"⚠️ {e}")
                    except Exception as e:
                        st.error(f"⚠️ Unexpected error: {e}")
        else:
            st.info("No audit entries yet. The log lives in memory — "
                    "download the CSV before closing the browser.")

    st.divider()
    with st.container(border=True):
        st.subheader("🔎 Gap Analysis")
        g1, g2 = st.columns(2)
        with g1:
            gap_hr_up = st.file_uploader("Current HR List (.xlsx)", type=["xlsx", "xls"],
                                         key="sec_gap_hr")
        with g2:
            gap_rules_up = st.file_uploader("Rule_Book (.csv / .xlsx)",
                                            type=["csv", "xlsx", "xls"], key="sec_gap_rules")

    if st.button("Run Gap Analysis", type="primary", key="sec_gap_go"):
        try:
            hr = (read_hr_excel(gap_hr_up, schema_mapping) if gap_hr_up
                  else st.session_state[P + "hr_current"])
            if hr is None:
                st.error("Upload a current HR list (or run the Rule Engine / "
                         "Delta tab first).")
            elif not gap_rules_up:
                st.error("Please upload the Rule_Book.")
            else:
                rules = read_table_upload(gap_rules_up)
                sm = st.session_state[P + "store_master_current"]
                _warn_unmapped(*check_unmapped_master_data(hr, rules))
                expected, warns = simulate_rls(hr, rules, None, sm)
                for w in warns:
                    st.warning(w)
                missing, excess = gap_analysis(expected, st.session_state[P + "audit_log"])
                st.session_state[P + "gap_res"] = (missing, excess)
        except ValueError as e:
            st.error(f"⚠️ {e}")
        except Exception as e:
            st.error(f"⚠️ Unexpected error: {e}")

    gap = st.session_state[P + "gap_res"]
    if gap:
        with st.container(border=True):
            missing, excess = gap
            if not missing.empty:
                st.error(f"🚨 **{len(missing)} Missing Required Access** — grant these:")
                st.dataframe(missing[[EMAIL, "Asset"]], use_container_width=True)
            else:
                st.success("No missing access — everyone has what the rules require. ✅")
            st.divider()
            if not excess.empty:
                st.warning(f"⚠️ **{len(excess)} Excess / Unknown Access** — review these grants:")
                st.dataframe(excess[[EMAIL, "Asset"]], use_container_width=True)
            else:
                st.success("No excess access found. ✅")

# ----------------------------------------------------- TAB 4: QUERY ---
with tab_query:
    st.header("🔍 Access Query Tool — Effective Access Resolver")
    st.caption("Search by user to see their assets (rule engine) and grants "
               "(audit register), or search by asset to list everyone who can reach it.")

    final_q = st.session_state[P + "final_rls"]
    audit_q = st.session_state[P + "audit_log"]
    if final_q is None:
        with st.container(border=True):
            st.subheader("Get started")
            st.markdown(
                "1. Go to the **🔐 Rule Engine** tab and upload your HR list and Rule_Book.\n"
                "2. Click **▶️ Simulate & Combine**.\n"
                "3. Return here to search effective access by user or by asset."
            )
    else:
        with st.container(border=True):
            mode = st.radio("Search mode", ["By User (Email)", "By Asset"],
                            horizontal=True, key="sec_query_mode")
            if mode == "By User (Email)":
                q = st.text_input("Work Email", key="sec_query_user").strip().lower()
                if q:
                    user_rows = final_q[final_q[EMAIL].str.strip().str.lower() == q]
                    if user_rows.empty:
                        st.warning(f"No access rows found for '{q}'. Check the email spelling.")
                    else:
                        person = user_rows.iloc[0]
                        st.subheader(f"👤 {person[EMAIL]} — {person[DEPT]} / {person[POS]}")
                        st.markdown("**🏬 Assets visible (rule engine):**")
                        st.dataframe(user_rows[[STORE_ACCESS, STORE_NAME, "Source"]]
                                     .drop_duplicates(), use_container_width=True)
                        st.markdown("**📊 Grants (audit register):**")
                        granted = (audit_q[audit_q[EMAIL].str.strip().str.lower() == q]
                                   if not audit_q.empty else audit_q)
                        if not granted.empty:
                            st.dataframe(granted[["Date", "Asset_Name", "Permission_Level",
                                                  "Remark"]], use_container_width=True)
                        else:
                            st.info("No grants logged for this user yet.")
            else:
                q = st.text_input("Asset code / asset name / report name",
                                  key="sec_query_asset").strip()
                if q:
                    ql = q.lower()
                    store_hits = final_q[
                        final_q[STORE_ACCESS].str.lower().str.contains(ql, na=False, regex=False)
                        | final_q[STORE_NAME].str.lower().str.contains(ql, na=False, regex=False)
                    ]
                    if not store_hits.empty:
                        st.subheader(f"🏬 Users with access to asset '{q}'")
                        st.dataframe(store_hits[[EMAIL, DEPT, POS, STORE_ACCESS,
                                                 STORE_NAME, "Source"]]
                                     .drop_duplicates().sort_values(EMAIL),
                                     use_container_width=True)
                    exp_hits = final_q[final_q[REPORT_ACCESS].str.lower()
                                       .str.contains(ql, na=False, regex=False)]
                    act_hits = (audit_q[audit_q["Asset_Name"].str.lower()
                                        .str.contains(ql, na=False, regex=False)]
                                if not audit_q.empty else pd.DataFrame())
                    if not exp_hits.empty or not act_hits.empty:
                        st.subheader(f"📊 Report access for '{q}'")
                        if not exp_hits.empty:
                            st.markdown("*Should have (per rules):*")
                            st.dataframe(exp_hits[[EMAIL, DEPT, POS]].drop_duplicates()
                                         .sort_values(EMAIL), use_container_width=True)
                        if not act_hits.empty:
                            st.markdown("*Actually granted (audit register):*")
                            st.dataframe(act_hits[[EMAIL, "Permission_Level", "Date", "Remark"]]
                                         .drop_duplicates().sort_values(EMAIL),
                                         use_container_width=True)
                    if store_hits.empty and exp_hits.empty and act_hits.empty:
                        st.warning(f"Nothing found matching '{q}'.")
