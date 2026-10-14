"""Power BI Security & Governance Command Center.

A local Streamlit tool with three modules:
  1. RLS Engine — merge HR Staff List + Rule_Book + Overrides into Final_RLS.csv
  2. Delta Tracking — compare old vs new HR lists: Leavers / Joiners / Movers
  3. Access Audit — log manually granted cloud access + Gap Analysis vs rules

Everything runs locally. No Power BI API needed.

Run with: streamlit run app.py
"""

from datetime import date
from io import StringIO

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Power BI Security & Governance Command Center",
    page_icon="🛡️",
    layout="wide",
)


# ============================================================ helpers ===
EMAIL_COL = "Email"
STORE_COL = "Base_Store"
POSITION_COL = "Position"


def _norm_email(s: pd.Series) -> pd.Series:
    """Normalize emails for reliable joins (lowercase, stripped)."""
    return s.astype(str).str.strip().str.lower()


def _require_cols(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def read_hr_excel(uploaded) -> pd.DataFrame:
    """Read the HR Staff List Excel. Expects Email, Base_Store, Position."""
    df = pd.read_excel(uploaded, dtype=str).fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    _require_cols(df, [EMAIL_COL, STORE_COL, POSITION_COL], "HR Staff List")
    df["_email_key"] = _norm_email(df[EMAIL_COL])
    df = df[df["_email_key"] != ""].drop_duplicates(subset=["_email_key"], keep="last")
    return df


def read_csv_upload(uploaded) -> pd.DataFrame:
    df = pd.read_csv(uploaded, dtype=str).fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def sample_rule_book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Base_Store": "Store A",
                "Position": "Manager",
                "RLS_Stock_Room_Codes": "A-STOCK;A-OFFICE",
                "Report_Access": "Sales Dashboard;Inventory Report;Staff Performance",
            },
            {
                "Base_Store": "Store A",
                "Position": "Sales",
                "RLS_Stock_Room_Codes": "A-STOCK",
                "Report_Access": "Sales Dashboard",
            },
            {
                "Base_Store": "Store B",
                "Position": "Manager",
                "RLS_Stock_Room_Codes": "B-STOCK;B-OFFICE",
                "Report_Access": "Sales Dashboard;Inventory Report;Staff Performance",
            },
            {
                "Base_Store": "Store B",
                "Position": "Sales",
                "RLS_Stock_Room_Codes": "B-STOCK",
                "Report_Access": "Sales Dashboard",
            },
            {
                "Base_Store": "*",
                "Position": "Regional Manager",
                "RLS_Stock_Room_Codes": "ALL",
                "Report_Access": "Sales Dashboard;Inventory Report;Staff Performance;Regional Overview",
            },
        ]
    )


def sample_overrides() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Email": "temp.cover@example.com",
                "RLS_Stock_Room_Codes": "A-STOCK;B-STOCK",
                "Report_Access": "Sales Dashboard;Inventory Report",
                "Reason": "Covering Store B during renovation (until 2026-12-31)",
            },
        ]
    )


def simulate_rls(
    hr: pd.DataFrame, rules: pd.DataFrame, overrides: pd.DataFrame | None
) -> tuple[pd.DataFrame, list[str]]:
    """Merge HR + Rule_Book (+ Overrides) into the final RLS table.

    Rule matching: exact (Base_Store, Position) first, then wildcard
    Base_Store="*" fallback. Overrides win per-email.
    Returns (final_df, warnings).
    """
    warnings: list[str] = []
    _require_cols(rules, ["Base_Store", "Position", "RLS_Stock_Room_Codes", "Report_Access"], "Rule_Book")

    hr = hr.copy()
    hr["_rule_key"] = hr[STORE_COL] + "||" + hr[POSITION_COL]

    rules = rules.copy()
    rules["_rule_key"] = rules["Base_Store"] + "||" + rules["Position"]
    wild = rules[rules["Base_Store"] == "*"].copy()
    wild["_rule_key"] = "*||" + wild["Position"]
    exact = rules[rules["Base_Store"] != "*"]

    merged = hr.merge(
        exact[["_rule_key", "RLS_Stock_Room_Codes", "Report_Access"]],
        on="_rule_key",
        how="left",
    )
    # Wildcard fallback for rows with no exact match.
    need_wild = merged["RLS_Stock_Room_Codes"].isna() | (merged["RLS_Stock_Room_Codes"] == "")
    if need_wild.any():
        hr["_wild_key"] = "*||" + hr[POSITION_COL]
        wmerge = hr[need_wild].merge(
            wild[["_rule_key", "RLS_Stock_Room_Codes", "Report_Access"]].rename(
                columns={"_rule_key": "_wild_key"}
            ),
            on="_wild_key",
            how="left",
        )
        for col in ["RLS_Stock_Room_Codes", "Report_Access"]:
            merged.loc[need_wild, col] = wmerge[col].values

    unmatched = merged[
        merged["RLS_Stock_Room_Codes"].isna() | (merged["RLS_Stock_Room_Codes"] == "")
    ]
    if not unmatched.empty:
        warnings.append(
            f"{len(unmatched)} staff have no matching rule "
            f"(e.g. {unmatched.iloc[0][EMAIL_COL]} — "
            f"{unmatched.iloc[0][STORE_COL]} / {unmatched.iloc[0][POSITION_COL]}). "
            "Add a rule or a wildcard '*' row."
        )
    merged["RLS_Stock_Room_Codes"] = merged["RLS_Stock_Room_Codes"].fillna("")
    merged["Report_Access"] = merged["Report_Access"].fillna("")
    merged["Source"] = "Rule_Book"

    # Overrides win per email.
    if overrides is not None and not overrides.empty:
        _require_cols(overrides, ["Email", "RLS_Stock_Room_Codes", "Report_Access"], "Overrides")
        overrides = overrides.copy()
        overrides["_email_key"] = _norm_email(overrides["Email"])
        omap = overrides.set_index("_email_key")
        for idx, row in merged.iterrows():
            key = row["_email_key"]
            if key in omap.index:
                ov = omap.loc[key]
                if isinstance(ov, pd.DataFrame):
                    ov = ov.iloc[0]
                if ov["RLS_Stock_Room_Codes"]:
                    merged.at[idx, "RLS_Stock_Room_Codes"] = ov["RLS_Stock_Room_Codes"]
                if ov["Report_Access"]:
                    merged.at[idx, "Report_Access"] = ov["Report_Access"]
                merged.at[idx, "Source"] = "Override"

    keep = [EMAIL_COL, STORE_COL, POSITION_COL, "RLS_Stock_Room_Codes", "Report_Access", "Source"]
    extra = [c for c in hr.columns if c not in keep and not c.startswith("_")]
    final = merged[keep + extra].copy()
    return final, warnings


def compute_deltas(
    old: pd.DataFrame, new: pd.DataFrame, rules: pd.DataFrame | None
) -> dict[str, pd.DataFrame]:
    """Anti-joins + change detection between two HR snapshots."""
    old = old.copy()
    new = new.copy()

    leavers = old.merge(new[["_email_key"]], on="_email_key", how="left", indicator=True)
    leavers = leavers[leavers["_merge"] == "left_only"].drop(columns=["_merge"])

    joiners = new.merge(old[["_email_key"]], on="_email_key", how="left", indicator=True)
    joiners = joiners[joiners["_merge"] == "left_only"].drop(columns=["_merge"])

    # Suggest access for joiners from the Rule_Book.
    if rules is not None and not rules.empty and not joiners.empty:
        try:
            sug, _ = simulate_rls(joiners, rules, None)
            joiners = sug
        except ValueError:
            pass

    both = old.merge(
        new,
        on="_email_key",
        how="inner",
        suffixes=("_old", "_new"),
    )
    moved_mask = (both[f"{STORE_COL}_old"] != both[f"{STORE_COL}_new"]) | (
        both[f"{POSITION_COL}_old"] != both[f"{POSITION_COL}_new"]
    )
    movers = both[moved_mask].copy()

    return {"leavers": leavers, "joiners": joiners, "movers": movers}


def split_access_list(s: str) -> list[str]:
    return [p.strip() for p in str(s).split(";") if p.strip()]


def gap_analysis(
    expected: pd.DataFrame, audit: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross-check expected (HR+rules) vs actual (audit log).

    Returns (missing_required, excess_or_unknown).
    """
    # Expand expected per (email, report).
    exp_rows = []
    for _, r in expected.iterrows():
        for rep in split_access_list(r["Report_Access"]):
            exp_rows.append({"_email_key": r["_email_key"], EMAIL_COL: r[EMAIL_COL], "Asset": rep})
    exp = pd.DataFrame(exp_rows)

    act_rows = []
    if audit is not None and not audit.empty:
        for _, r in audit.iterrows():
            act_rows.append(
                {"_email_key": _norm_email(pd.Series([r[EMAIL_COL]])).iloc[0],
                 EMAIL_COL: r[EMAIL_COL], "Asset": str(r["Asset_Name"]).strip()}
            )
    act = pd.DataFrame(act_rows, columns=["_email_key", EMAIL_COL, "Asset"])

    if exp.empty:
        return pd.DataFrame(), act

    merged = exp.merge(act[["_email_key", "Asset"]], on=["_email_key", "Asset"],
                       how="left", indicator=True)
    missing = merged[merged["_merge"] == "left_only"].drop(columns=["_merge"])

    merged2 = act.merge(exp[["_email_key", "Asset"]], on=["_email_key", "Asset"],
                        how="left", indicator=True)
    excess = merged2[merged2["_merge"] == "left_only"].drop(columns=["_merge"])

    return missing, excess


# ============================================================ state ===
for key, default in [
    ("hr_current", None),
    ("hr_current_name", ""),
    ("audit_log", pd.DataFrame(columns=["Date", EMAIL_COL, "Asset_Name", "Permission_Level"])),
    ("final_rls", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================ UI ===
st.title("🛡️ Power BI Security & Governance Command Center")
st.caption("Local-only RLS engine · delta tracking · access audit. Nothing leaves this machine.")

tab_rls, tab_delta, tab_audit = st.tabs(
    ["🔐 RLS Engine", "🔄 Delta Tracking", "📋 Access Audit & Gap Analysis"]
)


# ------------------------------------------------------- TAB 1: RLS ---
with tab_rls:
    st.header("Simulate & Combine → Final_RLS.csv")
    st.caption(
        "Upload the monthly HR Staff List (Excel), the Rule_Book.csv "
        "(Base_Store + Position → RLS codes & report access), and optional Overrides.csv."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        hr_up = st.file_uploader("HR Staff List (.xlsx)", type=["xlsx", "xls"], key="rls_hr")
    with c2:
        rules_up = st.file_uploader("Rule_Book.csv", type=["csv"], key="rls_rules")
    with c3:
        ov_up = st.file_uploader("Overrides.csv (optional)", type=["csv"], key="rls_ov")

    with st.expander("📥 Download template files"):
        st.download_button(
            "Rule_Book template",
            sample_rule_book().to_csv(index=False).encode(),
            "Rule_Book_template.csv",
            "text/csv",
        )
        st.download_button(
            "Overrides template",
            sample_overrides().to_csv(index=False).encode(),
            "Overrides_template.csv",
            "text/csv",
        )

    if st.button("▶️ Simulate & Combine", type="primary", key="rls_go"):
        if not hr_up or not rules_up:
            st.error("Please upload both the HR Staff List and the Rule_Book.csv.")
        else:
            try:
                hr = read_hr_excel(hr_up)
                rules = read_csv_upload(rules_up)
                ov = read_csv_upload(ov_up) if ov_up else None
                final, warns = simulate_rls(hr, rules, ov)
                st.session_state["final_rls"] = final
                st.session_state["hr_current"] = hr
                st.session_state["hr_current_name"] = hr_up.name
                for w in warns:
                    st.warning(w)
                st.success(f"✅ {len(final)} staff resolved ({(final['Source'] == 'Override').sum()} overrides applied).")
            except ValueError as e:
                st.error(f"⚠️ {e}")
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")

    final = st.session_state["final_rls"]
    if final is not None:
        st.subheader("Final_RLS.csv preview")
        st.dataframe(final, use_container_width=True)
        st.download_button(
            "⬇️ Download Final_RLS.csv",
            final.drop(columns=[c for c in final.columns if c.startswith("_")], errors="ignore")
            .to_csv(index=False).encode(),
            "Final_RLS.csv",
            "text/csv",
        )


# ----------------------------------------------------- TAB 2: DELTA ---
with tab_delta:
    st.header("Personnel Movement — Joiners / Leavers / Movers")
    st.caption(
        "Upload the previous HR list and the new HR list. "
        "Leavers are flagged for access revocation; joiners get suggested access from the Rule_Book."
    )

    d1, d2, d3 = st.columns(3)
    with d1:
        old_up = st.file_uploader("Previous HR List (.xlsx)", type=["xlsx", "xls"], key="delta_old")
    with d2:
        new_up = st.file_uploader("New HR List (.xlsx)", type=["xlsx", "xls"], key="delta_new")
    with d3:
        delta_rules_up = st.file_uploader("Rule_Book.csv (for joiner suggestions)", type=["csv"], key="delta_rules")

    if st.button("🔍 Compare", type="primary", key="delta_go"):
        if not old_up or not new_up:
            st.error("Please upload both the previous and the new HR list.")
        else:
            try:
                old = read_hr_excel(old_up)
                new = read_hr_excel(new_up)
                rules = read_csv_upload(delta_rules_up) if delta_rules_up else None
                res = compute_deltas(old, new, rules)
                st.session_state["delta_res"] = res
                st.session_state["hr_current"] = new
                st.session_state["hr_current_name"] = new_up.name
            except ValueError as e:
                st.error(f"⚠️ {e}")
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")

    res = st.session_state.get("delta_res")
    if res:
        leavers, joiners, movers = res["leavers"], res["joiners"], res["movers"]

        if not leavers.empty:
            st.error(f"🚨 **{len(leavers)} Leaver(s)** — revoke their cloud access now:")
            show = [c for c in [EMAIL_COL, STORE_COL, POSITION_COL] if c in leavers.columns]
            st.dataframe(leavers[show], use_container_width=True)
        else:
            st.success("No leavers detected. ✅")

        st.divider()
        if not joiners.empty:
            st.warning(f"👋 **{len(joiners)} Joiner(s)** — provision access:")
            show = [c for c in [EMAIL_COL, STORE_COL, POSITION_COL,
                                "RLS_Stock_Room_Codes", "Report_Access", "Source"]
                    if c in joiners.columns]
            st.dataframe(joiners[show], use_container_width=True)
        else:
            st.success("No joiners detected. ✅")

        st.divider()
        if not movers.empty:
            st.warning(f"🔀 **{len(movers)} Mover(s)** — position or store changed:")
            show = [c for c in movers.columns
                    if not c.startswith("_") and c != "_merge"]
            st.dataframe(movers[show], use_container_width=True)
        else:
            st.success("No movers detected. ✅")


# ----------------------------------------------------- TAB 3: AUDIT ---
with tab_audit:
    st.header("Access Audit Register & Gap Analysis")
    st.caption(
        "Log manually granted cloud access below. Gap Analysis cross-checks "
        "what staff *should* have (HR + Rule_Book) against what they *actually* have."
    )

    st.subheader("➕ Log granted access")
    with st.form("audit_form", clear_on_submit=True):
        f1, f2 = st.columns(2)
        with f1:
            a_date = st.date_input("Date", value=date.today())
            a_email = st.text_input("Email").strip()
        with f2:
            a_asset = st.text_input("Asset_Name (e.g. Sales Dashboard)").strip()
            a_perm = st.selectbox("Permission_Level", ["Viewer", "Contributor", "Member", "Admin"])
        if st.form_submit_button("Add entry"):
            if not a_email or not a_asset:
                st.error("Email and Asset_Name are required.")
            else:
                row = pd.DataFrame([{
                    "Date": a_date.isoformat(), EMAIL_COL: a_email,
                    "Asset_Name": a_asset, "Permission_Level": a_perm,
                }])
                st.session_state["audit_log"] = pd.concat(
                    [st.session_state["audit_log"], row], ignore_index=True
                )
                st.success("Entry logged.")

    st.subheader("📜 Audit log")
    audit = st.session_state["audit_log"]
    if not audit.empty:
        st.dataframe(audit, use_container_width=True)
        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "⬇️ Download Access_Audit.csv",
                audit.to_csv(index=False).encode(),
                "Access_Audit.csv",
                "text/csv",
            )
        with c2:
            audit_up = st.file_uploader("…or load an existing Access_Audit.csv", type=["csv"], key="audit_load")
            if audit_up:
                try:
                    loaded = read_csv_upload(audit_up)
                    _require_cols(loaded, ["Date", EMAIL_COL, "Asset_Name", "Permission_Level"], "Access_Audit.csv")
                    st.session_state["audit_log"] = loaded
                    st.success(f"Loaded {len(loaded)} audit rows.")
                    st.rerun()
                except ValueError as e:
                    st.error(f"⚠️ {e}")
    else:
        st.info("No audit entries yet.")

    st.divider()
    st.subheader("🔎 Gap Analysis")
    g1, g2 = st.columns(2)
    with g1:
        gap_hr_up = st.file_uploader("Current HR List (.xlsx)", type=["xlsx", "xls"], key="gap_hr")
    with g2:
        gap_rules_up = st.file_uploader("Rule_Book.csv", type=["csv"], key="gap_rules")

    # Default to the HR list already in session (from RLS or Delta tabs).
    if st.button("Run Gap Analysis", type="primary", key="gap_go"):
        try:
            hr = read_hr_excel(gap_hr_up) if gap_hr_up else st.session_state["hr_current"]
            if hr is None:
                st.error("Upload a current HR list (or run the RLS / Delta tab first).")
            elif not gap_rules_up:
                st.error("Please upload the Rule_Book.csv.")
            else:
                rules = read_csv_upload(gap_rules_up)
                expected, warns = simulate_rls(hr, rules, None)
                for w in warns:
                    st.warning(w)
                missing, excess = gap_analysis(expected, st.session_state["audit_log"])
                st.session_state["gap_res"] = (missing, excess)
        except ValueError as e:
            st.error(f"⚠️ {e}")
        except Exception as e:
            st.error(f"⚠️ Unexpected error: {e}")

    gap = st.session_state.get("gap_res")
    if gap:
        missing, excess = gap
        if not missing.empty:
            st.error(f"🚨 **{len(missing)} Missing Required Access** — grant these:")
            st.dataframe(missing[[EMAIL_COL, "Asset"]], use_container_width=True)
        else:
            st.success("No missing access — everyone has what the rules require. ✅")
        st.divider()
        if not excess.empty:
            st.warning(f"⚠️ **{len(excess)} Excess / Unknown Access** — review these grants:")
            st.dataframe(excess[[EMAIL_COL, "Asset"]], use_container_width=True)
        else:
            st.success("No excess access found. ✅")
