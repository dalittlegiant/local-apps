"""Power BI Security & Governance Command Center.

A local Streamlit tool with three modules:
  1. RLS Engine — merge HR Staff List + Rule_Book + Exceptions into Final_RLS.csv
     (one row per user per store; Store_Access exploded on ":")
  2. Delta Tracking — compare old vs new HR lists: Leavers / Joiners / Movers
  3. Access Audit — log manually granted cloud access + Gap Analysis vs rules

Everything runs locally. No Power BI API needed.

Run with: streamlit run app.py
"""

from datetime import date

import pandas as pd
import streamlit as st


st.set_page_config(
    page_title="Power BI Security & Governance Command Center",
    page_icon="🛡️",
    layout="wide",
)


# ============================================================ schema ==
# Canonical column names used everywhere in the app.
EMAIL = "Work Email"
DEPT = "Department"
POS = "Position"
STORE_ACCESS = "Store_Access"
REPORT_ACCESS = "Report_Access"

STORE_SEP = ":"   # multi-store delimiter inside Store_Access
REPORT_SEP = ";"  # multi-report delimiter inside Report_Access


# ============================================================ helpers ==
def split_list(s: str, sep: str) -> list[str]:
    return [p.strip() for p in str(s).split(sep) if p.strip()]


def _require_cols(df: pd.DataFrame, cols: list[str], label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing columns: {', '.join(missing)}")


def read_hr_excel(uploaded, mapping: dict[str, str]) -> pd.DataFrame:
    """Read the HR Staff List Excel and rename raw columns to the canonical
    schema using the user-provided mapping.

    mapping: {"Work Email": <raw col>, "Department": <raw col>, "Position": <raw col>}
    """
    df = pd.read_excel(uploaded, dtype=str).fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()

    rename = {raw: canon for canon, raw in mapping.items() if raw and raw in df.columns}
    df = df.rename(columns=rename)
    _require_cols(df, [EMAIL, DEPT, POS], "HR Staff List (after schema mapping)")
    df = df[df[EMAIL] != ""].drop_duplicates(subset=[EMAIL], keep="last")
    return df


def read_csv_upload(uploaded) -> pd.DataFrame:
    df = pd.read_csv(uploaded, dtype=str).fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def sample_rule_book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {DEPT: "Store A", POS: "Manager", STORE_ACCESS: "Store A",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report;Staff Performance"},
            {DEPT: "Store A", POS: "Sales", STORE_ACCESS: "Store A",
             REPORT_ACCESS: "Sales Dashboard"},
            {DEPT: "Store B", POS: "Manager", STORE_ACCESS: "Store B",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report;Staff Performance"},
            {DEPT: "Store B", POS: "Sales", STORE_ACCESS: "Store B",
             REPORT_ACCESS: "Sales Dashboard"},
            {DEPT: "North Region", POS: "Regional Manager",
             STORE_ACCESS: "Store A:Store C",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report;Staff Performance;Regional Overview"},
            {DEPT: "*", POS: "IT Officer", STORE_ACCESS: "Store A:Store B:Store C",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report"},
        ]
    )


def sample_exceptions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {EMAIL: "temp.cover@example.com", STORE_ACCESS: "Store A:Store B",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report",
             "Reason": "Covering Store B during renovation (until 2026-12-31)"},
        ]
    )


def explode_store_access(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten Store_Access on ':' so one user with 'Store A:Store B'
    becomes two rows. Rows with no store keep a single blank row so they
    stay visible for follow-up."""
    df = df.copy()
    parts = df[STORE_ACCESS].apply(lambda s: split_list(s, STORE_SEP))
    has_store = parts.map(len) > 0

    exploded = df[has_store].copy()
    exploded[STORE_ACCESS] = parts[has_store]
    exploded = exploded.explode(STORE_ACCESS)

    rest = df[~has_store].copy()
    rest[STORE_ACCESS] = ""

    out = pd.concat([exploded, rest], ignore_index=True)
    return out.sort_values([EMAIL, STORE_ACCESS]).reset_index(drop=True)


def simulate_rls(
    hr: pd.DataFrame, rules: pd.DataFrame, exceptions: pd.DataFrame | None
) -> tuple[pd.DataFrame, list[str]]:
    """Merge HR + Rule_Book (+ Exceptions) into the final RLS table.

    Rule matching: exact (Department, Position) first, then wildcard
    Department="*" fallback. Per-email exceptions win. Store_Access is
    exploded on ':' into one row per store.
    Returns (final_df, warnings).
    """
    warnings: list[str] = []
    _require_cols(rules, [DEPT, POS, STORE_ACCESS, REPORT_ACCESS], "Rule_Book")

    rules = rules.copy()
    wild = rules[rules[DEPT] == "*"].copy()
    exact = rules[rules[DEPT] != "*"]

    def lookup(dept: str, pos: str):
        hit = exact[(exact[DEPT] == dept) & (exact[POS] == pos)]
        if not hit.empty:
            return hit.iloc[0]
        hit = wild[wild[POS] == pos]
        if not hit.empty:
            return hit.iloc[0]
        return None

    rows = []
    for _, person in hr.iterrows():
        rule = lookup(person[DEPT], person[POS])
        if rule is None:
            warnings.append(
                f"No matching rule for {person[EMAIL]} "
                f"({person[DEPT]} / {person[POS]}). Add a rule or a wildcard '*' row."
            )
            store, reports, source = "", "", "NO RULE"
        else:
            store, reports, source = (
                rule[STORE_ACCESS], rule[REPORT_ACCESS], "Rule_Book",
            )
        rows.append({
            EMAIL: person[EMAIL], DEPT: person[DEPT], POS: person[POS],
            STORE_ACCESS: store, REPORT_ACCESS: reports, "Source": source,
        })
    merged = pd.DataFrame(rows)

    # Exceptions win per email.
    if exceptions is not None and not exceptions.empty:
        _require_cols(exceptions, [EMAIL], "Exceptions")
        emap = exceptions.set_index(EMAIL)
        for idx, row in merged.iterrows():
            if row[EMAIL] in emap.index:
                ex = emap.loc[row[EMAIL]]
                if isinstance(ex, pd.DataFrame):
                    ex = ex.iloc[0]
                if STORE_ACCESS in ex and ex[STORE_ACCESS]:
                    merged.at[idx, STORE_ACCESS] = ex[STORE_ACCESS]
                if REPORT_ACCESS in ex and ex[REPORT_ACCESS]:
                    merged.at[idx, REPORT_ACCESS] = ex[REPORT_ACCESS]
                merged.at[idx, "Source"] = "Exception"

    return explode_store_access(merged), warnings


def compute_deltas(
    old: pd.DataFrame, new: pd.DataFrame, rules: pd.DataFrame | None
) -> dict[str, pd.DataFrame]:
    """Anti-joins + change detection between two HR snapshots, joined
    strictly on the 'Work Email' column."""
    leavers = old.merge(new[[EMAIL]], on=EMAIL, how="left", indicator=True)
    leavers = leavers[leavers["_merge"] == "left_only"].drop(columns=["_merge"])

    joiners = new.merge(old[[EMAIL]], on=EMAIL, how="left", indicator=True)
    joiners = joiners[joiners["_merge"] == "left_only"].drop(columns=["_merge"])

    # Suggest access for joiners from the Rule_Book.
    if rules is not None and not rules.empty and not joiners.empty:
        try:
            joiners, _ = simulate_rls(joiners, rules, None)
        except ValueError:
            pass

    both = old.merge(new, on=EMAIL, how="inner", suffixes=("_old", "_new"))
    moved_mask = (both[f"{DEPT}_old"] != both[f"{DEPT}_new"]) | (
        both[f"{POS}_old"] != both[f"{POS}_new"]
    )
    movers = both[moved_mask].copy()

    return {"leavers": leavers, "joiners": joiners, "movers": movers}


def gap_analysis(
    expected: pd.DataFrame, audit: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross-check expected access (HR + rules) vs actual grants (audit log).

    Compares strictly on the 'Work Email' column — no hidden temp keys.
    Returns (missing_required, excess_or_unknown).
    """
    exp_rows = []
    for _, r in expected.iterrows():
        for rep in split_list(r[REPORT_ACCESS], REPORT_SEP):
            exp_rows.append({EMAIL: r[EMAIL], "Asset": rep})
    expected_pairs = pd.DataFrame(exp_rows).drop_duplicates()

    actual_rows = []
    if audit is not None and not audit.empty:
        for _, r in audit.iterrows():
            asset = str(r["Asset_Name"]).strip()
            if r[EMAIL] and asset:
                actual_rows.append({EMAIL: r[EMAIL], "Asset": asset})
    actual_pairs = pd.DataFrame(actual_rows, columns=[EMAIL, "Asset"]).drop_duplicates()

    if expected_pairs.empty:
        return pd.DataFrame(columns=[EMAIL, "Asset"]), actual_pairs

    missing = expected_pairs.merge(
        actual_pairs, on=[EMAIL, "Asset"], how="left", indicator=True
    )
    missing = missing[missing["_merge"] == "left_only"].drop(columns=["_merge"])

    excess = actual_pairs.merge(
        expected_pairs, on=[EMAIL, "Asset"], how="left", indicator=True
    )
    excess = excess[excess["_merge"] == "left_only"].drop(columns=["_merge"])

    return missing, excess


# ============================================================ state ==
for key, default in [
    ("hr_current", None),
    ("hr_current_name", ""),
    ("audit_log", pd.DataFrame(
        columns=["Date", EMAIL, "Asset_Name", "Permission_Level", "Remark"])),
    ("final_rls", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================ sidebar ==
st.sidebar.header("⚙️ Schema Mapping")
st.sidebar.caption(
    "Map your raw HR Excel column names to the system's required columns. "
    "Defaults match the standard template — change only if HR renames theirs."
)
map_email = st.sidebar.text_input("HR column → Work Email", value=EMAIL)
map_dept = st.sidebar.text_input("HR column → Department", value=DEPT)
map_pos = st.sidebar.text_input("HR column → Position", value=POS)
schema_mapping = {EMAIL: map_email.strip(), DEPT: map_dept.strip(), POS: map_pos.strip()}


# ============================================================ UI =======
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
        "(Department + Position → Store_Access & report access), and optional Exceptions.csv. "
        f"Multiple stores in Store_Access use '{STORE_SEP}' and are exploded into one row per store."
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        hr_up = st.file_uploader("HR Staff List (.xlsx)", type=["xlsx", "xls"], key="rls_hr")
    with c2:
        rules_up = st.file_uploader("Rule_Book.csv", type=["csv"], key="rls_rules")
    with c3:
        ex_up = st.file_uploader("Exceptions.csv (optional)", type=["csv"], key="rls_ex")

    with st.expander("📥 Download template files"):
        st.download_button(
            "Rule_Book template",
            sample_rule_book().to_csv(index=False).encode(),
            "Rule_Book_template.csv",
            "text/csv",
        )
        st.download_button(
            "Exceptions template",
            sample_exceptions().to_csv(index=False).encode(),
            "Exceptions_template.csv",
            "text/csv",
        )

    if st.button("▶️ Simulate & Combine", type="primary", key="rls_go"):
        if not hr_up or not rules_up:
            st.error("Please upload both the HR Staff List and the Rule_Book.csv.")
        else:
            try:
                hr = read_hr_excel(hr_up, schema_mapping)
                rules = read_csv_upload(rules_up)
                ex = read_csv_upload(ex_up) if ex_up else None
                final, warns = simulate_rls(hr, rules, ex)
                st.session_state["final_rls"] = final
                st.session_state["hr_current"] = hr
                st.session_state["hr_current_name"] = hr_up.name
                for w in warns:
                    st.warning(w)
                n_people = final[EMAIL].nunique()
                n_exc = (final["Source"] == "Exception").sum()
                st.success(f"✅ {n_people} staff → {len(final)} RLS rows ({n_exc} exception rows).")
            except ValueError as e:
                st.error(f"⚠️ {e}")
            except Exception as e:
                st.error(f"⚠️ Unexpected error: {e}")

    final = st.session_state["final_rls"]
    if final is not None:
        st.subheader("Final_RLS.csv preview (one row per user per store)")
        st.dataframe(final, use_container_width=True)
        st.download_button(
            "⬇️ Download Final_RLS.csv",
            final.to_csv(index=False).encode(),
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
                old = read_hr_excel(old_up, schema_mapping)
                new = read_hr_excel(new_up, schema_mapping)
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
            show = [c for c in [EMAIL, DEPT, POS] if c in leavers.columns]
            st.dataframe(leavers[show], use_container_width=True)
        else:
            st.success("No leavers detected. ✅")

        st.divider()
        if not joiners.empty:
            st.warning(f"👋 **{len(joiners)} Joiner(s)** — provision access:")
            show = [c for c in [EMAIL, DEPT, POS, STORE_ACCESS, REPORT_ACCESS, "Source"]
                    if c in joiners.columns]
            st.dataframe(joiners[show], use_container_width=True)
        else:
            st.success("No joiners detected. ✅")

        st.divider()
        if not movers.empty:
            st.warning(f"🔀 **{len(movers)} Mover(s)** — department or position changed:")
            show = [c for c in movers.columns if c != "_merge"]
            st.dataframe(movers[show], use_container_width=True)
        else:
            st.success("No movers detected. ✅")


# ----------------------------------------------------- TAB 3: AUDIT ---
with tab_audit:
    st.header("Access Audit Register & Gap Analysis")
    st.caption(
        "Log manually granted cloud access below. Gap Analysis cross-checks "
        "what staff *should* have (HR + Rule_Book) against what they *actually* have — "
        "compared strictly on the Work Email column."
    )

    st.subheader("➕ Log granted access")
    with st.form("audit_form", clear_on_submit=True):
        f1, f2 = st.columns(2)
        with f1:
            a_date = st.date_input("Date", value=date.today())
            a_email = st.text_input("Work Email").strip()
            a_remark = st.text_input("Remark (justification for this access)").strip()
        with f2:
            a_asset = st.text_input("Asset_Name (e.g. Sales Dashboard)").strip()
            a_perm = st.selectbox("Permission_Level", ["Viewer", "Contributor", "Member", "Admin"])
        if st.form_submit_button("Add entry"):
            if not a_email or not a_asset:
                st.error("Work Email and Asset_Name are required.")
            else:
                row = pd.DataFrame([{
                    "Date": a_date.isoformat(), EMAIL: a_email,
                    "Asset_Name": a_asset, "Permission_Level": a_perm,
                    "Remark": a_remark,
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
                    _require_cols(loaded, ["Date", EMAIL, "Asset_Name", "Permission_Level"], "Access_Audit.csv")
                    if "Remark" not in loaded.columns:
                        loaded["Remark"] = ""
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
            hr = read_hr_excel(gap_hr_up, schema_mapping) if gap_hr_up else st.session_state["hr_current"]
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
            st.dataframe(missing[[EMAIL, "Asset"]], use_container_width=True)
        else:
            st.success("No missing access — everyone has what the rules require. ✅")
        st.divider()
        if not excess.empty:
            st.warning(f"⚠️ **{len(excess)} Excess / Unknown Access** — review these grants:")
            st.dataframe(excess[[EMAIL, "Asset"]], use_container_width=True)
        else:
            st.success("No excess access found. ✅")
