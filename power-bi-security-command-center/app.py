"""Power BI Security & Governance Command Center.

A local Streamlit tool with four modules:
  1. RLS Engine — merge HR Staff List + Rule_Book + Exceptions into Final_RLS.csv
     (one row per user per store; Store_Access exploded on ":";
     Store_Codes resolved to Store_Name via the Store Master)
  2. Delta Tracking — compare old vs new HR lists: Leavers / Joiners / Movers,
     plus unmapped Position/Department warnings
  3. Access Audit — log manually granted cloud access + Gap Analysis vs rules
  4. Access Query Tool — effective access resolver (by user or by asset)

Everything runs locally. No Power BI API needed.

Run with: streamlit run app.py
"""

import io
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
STORE_ACCESS = "Store_Access"   # holds Store_Code values (exploded)
STORE_NAME = "Store_Name"       # user-friendly name from the Store Master
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


def _clean_str_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.fillna("")
    for c in df.columns:
        df[c] = df[c].astype(str).str.strip()
    return df


def read_csv_bytes(raw: bytes) -> tuple[pd.DataFrame, str]:
    """Robust CSV reader. Tries utf-8-sig first (handles BOM + most files),
    then plain utf-8, then cp1252 (covers é/ü-style Latin characters that
    break utf-8 decoding), with latin-1 as the final safety net."""
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, encoding=enc), enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(io.BytesIO(raw), dtype=str, encoding="latin-1"), "latin-1"


def read_table_upload(uploaded) -> pd.DataFrame:
    """Read a CSV or Excel upload into a cleaned string dataframe.

    Excel uploads (.xlsx/.xls) sidestep CSV encoding issues entirely.
    The detected encoding is stored on df.attrs['source_encoding'].
    """
    name = uploaded.name.lower()
    if name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded, dtype=str)
        enc = "excel"
    else:
        df, enc = read_csv_bytes(uploaded.getvalue())
    df = _clean_str_df(df)
    df.attrs["source_encoding"] = enc
    return df


def read_hr_excel(uploaded, mapping: dict[str, str]) -> pd.DataFrame:
    """Read the HR Staff List Excel and rename raw columns to the canonical
    schema using the user-provided mapping.

    mapping: {"Work Email": <raw col>, "Department": <raw col>, "Position": <raw col>}
    """
    df = _clean_str_df(pd.read_excel(uploaded, dtype=str))

    rename = {raw: canon for canon, raw in mapping.items() if raw and raw in df.columns}
    df = df.rename(columns=rename)
    _require_cols(df, [EMAIL, DEPT, POS], "HR Staff List (after schema mapping)")
    df = df[df[EMAIL] != ""].drop_duplicates(subset=[EMAIL], keep="last")
    return df


def sample_rule_book() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {DEPT: "A", POS: "Manager", STORE_ACCESS: "A",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report;Staff Performance"},
            {DEPT: "A", POS: "Sales", STORE_ACCESS: "A",
             REPORT_ACCESS: "Sales Dashboard"},
            {DEPT: "B", POS: "Manager", STORE_ACCESS: "B",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report;Staff Performance"},
            {DEPT: "B", POS: "Sales", STORE_ACCESS: "B",
             REPORT_ACCESS: "Sales Dashboard"},
            {DEPT: "*", POS: "Regional Manager", STORE_ACCESS: "A:C",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report;Staff Performance;Regional Overview"},
            {DEPT: "*", POS: "IT Officer", STORE_ACCESS: "A:B:C",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report"},
        ]
    )


def sample_exceptions() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {EMAIL: "temp.cover@example.com", STORE_ACCESS: "A:B",
             REPORT_ACCESS: "Sales Dashboard;Inventory Report",
             "Reason": "Covering Store B during renovation (until 2026-12-31)"},
        ]
    )


def sample_store_master() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Store_Code": "A", "Store_Name": "Flagship Store — Causeway Bay"},
            {"Store_Code": "B", "Store_Name": "Tsim Sha Tsui Store"},
            {"Store_Code": "C", "Store_Name": "Central Café Store"},
        ]
    )


def explode_store_access(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten Store_Access on ':' so one user with 'A:B' becomes two rows.
    Rows with no store keep a single blank row so they stay visible."""
    df = df.copy()
    parts = df[STORE_ACCESS].apply(lambda s: split_list(s, STORE_SEP))
    has_store = parts.map(len) > 0

    exploded = df[has_store].copy()
    exploded[STORE_ACCESS] = parts[has_store]
    exploded = exploded.explode(STORE_ACCESS)

    rest = df[~has_store].copy()
    rest[STORE_ACCESS] = ""

    return pd.concat([exploded, rest], ignore_index=True)


def apply_store_master(df: pd.DataFrame, store_master: pd.DataFrame | None) -> pd.DataFrame:
    """Join Store_Code -> Store_Name for display. Falls back to the code
    itself when no master is provided or a code is unknown."""
    df = df.copy()
    if store_master is not None and not store_master.empty:
        _require_cols(store_master, ["Store_Code", "Store_Name"], "Store_Master")
        sm = store_master[["Store_Code", "Store_Name"]].drop_duplicates("Store_Code")
        df = df.merge(sm, left_on=STORE_ACCESS, right_on="Store_Code", how="left")
        df[STORE_NAME] = df[STORE_NAME].fillna(df[STORE_ACCESS])
        df = df.drop(columns=["Store_Code"])
    else:
        df[STORE_NAME] = df[STORE_ACCESS]
    cols = [EMAIL, DEPT, POS, STORE_ACCESS, STORE_NAME, REPORT_ACCESS, "Source"]
    return df[cols].sort_values([EMAIL, STORE_ACCESS]).reset_index(drop=True)


def simulate_rls(
    hr: pd.DataFrame,
    rules: pd.DataFrame,
    exceptions: pd.DataFrame | None,
    store_master: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Merge HR + Rule_Book (+ Exceptions) into the final RLS table.

    Rule matching on (Department, Position) — Department holds Store_Codes,
    with "*" as the position-wide wildcard. Per-email exceptions win.
    Store_Access is exploded on ':' into one row per store, then resolved
    to Store_Name via the Store Master.
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
            store, reports, source = rule[STORE_ACCESS], rule[REPORT_ACCESS], "Rule_Book"
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

    return apply_store_master(explode_store_access(merged), store_master), warnings


def check_unmapped_master_data(
    hr: pd.DataFrame, rules: pd.DataFrame
) -> tuple[list[str], list[str]]:
    """Compare HR's unique Positions/Departments against the Rule_Book.
    Returns (new_positions, new_departments) not defined in the rules."""
    hr_pos = {p for p in hr[POS].unique() if p}
    hr_dept = {d for d in hr[DEPT].unique() if d}
    rule_pos = set(rules[POS].unique()) if POS in rules.columns else set()
    rule_dept = (set(rules[DEPT].unique()) - {"*"}) if DEPT in rules.columns else set()
    return sorted(hr_pos - rule_pos), sorted(hr_dept - rule_dept)


def warn_unmapped(new_pos: list[str], new_dept: list[str]) -> None:
    """Bright warning for master data the Rule_Book doesn't cover."""
    if new_pos or new_dept:
        details = []
        if new_pos:
            details.append(f"Positions: {', '.join(new_pos)}")
        if new_dept:
            details.append(f"Departments: {', '.join(new_dept)}")
        st.error(
            "🚨 **New Position/Department detected in HR List. "
            "Please update the Rule Book to assign RLS logic.**\n\n" + "\n".join(details)
        )


def compute_deltas(
    old: pd.DataFrame, new: pd.DataFrame, rules: pd.DataFrame | None,
    store_master: pd.DataFrame | None = None,
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
            joiners, _ = simulate_rls(joiners, rules, None, store_master)
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
    ("store_master_current", None),
    ("audit_log", pd.DataFrame(
        columns=["Date", EMAIL, "Asset_Name", "Permission_Level", "Remark"])),
    ("final_rls", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ============================================================ sidebar ==
st.sidebar.header("Navigate")
page = st.sidebar.radio(
    "Go to",
    ["🛠️ Workspace", "📖 How to Use"],
    key="nav_page",
    label_visibility="collapsed",
)

st.sidebar.header("⚙️ Schema Mapping")
st.sidebar.caption(
    "Map your raw HR Excel column names to the system's required columns. "
    "Defaults match the standard template — change only if HR renames theirs."
)
map_email = st.sidebar.text_input("HR column → Work Email", value=EMAIL)
map_dept = st.sidebar.text_input("HR column → Department", value=DEPT)
map_pos = st.sidebar.text_input("HR column → Position", value=POS)
schema_mapping = {EMAIL: map_email.strip(), DEPT: map_dept.strip(), POS: map_pos.strip()}


# ============================================================ docs ===
def render_docs() -> None:
    """The 'How to Use' page — a self-contained guide for new team members."""
    st.title("📖 How to Use — Security & Governance Command Center")
    st.caption("Read this page top to bottom and you'll know how to run the monthly governance cycle.")

    st.header("1. What this app does")
    st.markdown(
        """
This is a **local-only** governance tool for Power BI security. It answers three questions every month:

- **Who should see what?** → the RLS Engine builds the row-level-security table from HR data + rules.
- **What changed?** → Delta Tracking spots joiners, leavers, and movers between two HR lists.
- **Are we compliant?** → the Audit Register logs manually granted access, and Gap Analysis flags what's missing or excessive.

It has **four modules**, each with its own tab in the 🛠️ Workspace:

| Module | One-line intro |
|---|---|
| 🔐 **RLS Engine** | Merges the HR list, Rule Book, and Exceptions into `Final_RLS.csv` — one row per user per store. |
| 🔄 **Delta Tracking** | Compares the previous and new HR lists: leavers to deprovision, joiners to provision, movers to review. |
| 📋 **Access Audit & Gap Analysis** | A register of manually granted cloud access, cross-checked against what the rules say people *should* have. |
| 🔍 **Access Query Tool** | Search by user ("what can Alice see?") or by asset ("who can see Store B?"). |
"""
    )

    st.header("2. Monthly workflow (the 5-minute version)")
    st.markdown(
        """
1. **Delta Tracking tab** — upload last month's HR list and this month's HR list, click **Compare**.
   Revoke cloud access for every **leaver** (red), provision **joiners** (amber), review **movers**.
2. **RLS Engine tab** — upload this month's HR list + Rule_Book (+ Exceptions and Store_Master if you have them),
   click **Simulate & Combine**, download `Final_RLS.csv`, hand it to whoever publishes the Power BI dataset.
3. **Access Audit tab** — log any access you granted manually this month (email, asset, level, remark).
4. **Gap Analysis** (same tab) — upload the HR list + Rule_Book, click **Run Gap Analysis**,
   chase down every "Missing Required Access" row.
"""
    )

    st.header("3. File requirements")
    st.markdown(
        """
All tabular files accept **CSV or Excel (.xlsx)**. CSVs are read with automatic encoding detection
(`utf-8-sig → utf-8 → cp1252`), so files with characters like `é` won't crash the app —
but when in doubt, **Excel is the safest format**. Downloads are UTF-8 with BOM so Excel opens them cleanly.

**HR Staff List** (`.xlsx` only)
- Required columns: `Work Email`, `Department`, `Position`.
- If HR renames their columns, don't edit the file — update the **⚙️ Schema Mapping** in the sidebar instead.
- `Department` holds **store codes** (e.g. `A`), matching the Rule Book.

**Rule_Book** (`.csv` / `.xlsx`) — the heart of the system
- Columns: `Department`, `Position`, `Store_Access`, `Report_Access`.
- `Department` is a **store code**, or `*` for a position-wide wildcard (e.g. every IT Officer).
- `Store_Access`: one store code, or several separated by **`:`** (e.g. `A:C`).
- `Report_Access`: report names separated by **`;`** (e.g. `Sales Dashboard;Inventory Report`).
- Download the **template** from the RLS Engine tab to see the exact shape.

**Exceptions** (`.csv` / `.xlsx`, optional) — per-person overrides that beat the Rule Book
- Columns: `Work Email`, `Store_Access`, `Report_Access`, `Reason`.
- Leave a cell empty to keep the rule's value for that field.

**Store_Master** (`.csv` / `.xlsx`, optional but recommended)
- Columns: `Store_Code`, `Store_Name`.
- Lets the Rule Book speak in short codes while the UI and exports show friendly names.
  When a store is renamed or closed, update this file — not the rules.

**Access_Audit** (`.csv` / `.xlsx`)
- Columns: `Date`, `Work Email`, `Asset_Name`, `Permission_Level`, `Remark`.
- This is your local stand-in for the Power BI API you don't have: every manually granted
  cloud access gets logged here with a justification in `Remark`.
"""
    )

    st.header("4. Methodology — how each module works")

    st.subheader("🔐 RLS Engine")
    st.markdown(
        """
1. **Match** — each HR row is looked up in the Rule Book on (`Department`, `Position`).
   An exact match wins; otherwise a `Department = *` wildcard row for that position is used.
2. **Override** — if the person's email appears in Exceptions, those values replace the rule's
   (empty cells keep the rule value). The `Source` column records `Rule_Book`, `Exception`, or `NO RULE`.
3. **Explode** — `Store_Access` is split on `:` and exploded, so `A:C` becomes **two rows**.
   Power BI needs one row per user per store, not the word "All".
4. **Resolve names** — store codes are joined to the Store Master to add the friendly `Store_Name`.
5. **Warn** — anyone with no matching rule is kept as a visible `NO RULE` row (never silently dropped),
   and any `Department`/`Position` in HR but missing from the Rule Book triggers a red
   *"New Position/Department detected — please update the Rule Book"* warning.
"""
    )

    st.subheader("🔄 Delta Tracking")
    st.markdown(
        """
- **Leavers** — emails in the old list but missing from the new list (anti-join). Shown in **red**:
      revoke their cloud access immediately.
- **Joiners** — emails only in the new list. The app suggests their stores and reports by running
      them through the RLS Engine, so provisioning is one glance.
- **Movers** — same email, but `Department` or `Position` changed. Review whether their access
      still fits their new role.
- All comparisons are on the `Work Email` column exactly — no hidden keys, no fuzzy matching.
"""
    )

    st.subheader("📋 Access Audit & Gap Analysis")
    st.markdown(
        """
- **Audit Register** — append-only log of real grants. The in-app form writes to it; you can also
      load an existing CSV. **Download it before closing the browser** — it lives in memory.
- **Gap Analysis** — builds the *expected* access by expanding every user's `Report_Access`
      into (email, report) pairs, then anti-joins against the *actual* grants in the audit log:
    - **Missing Required Access** (red) — the rules say they should have it, but it's not logged. Grant it.
    - **Excess / Unknown Access** (amber) — logged but not required by any rule. Review or revoke it.
"""
    )

    st.subheader("🔍 Access Query Tool")
    st.markdown(
        """
Needs the RLS Engine to have run at least once (it queries the latest `Final_RLS` in memory).
- **By User** — type an email: see every store they can reach (code + friendly name + whether it
      came from a rule or an exception) and every report grant in the audit register with its remark.
- **By Asset** — type a store code/name or report name: for stores, lists everyone with RLS access;
      for reports, shows *should have* (per rules) next to *actually granted* (per audit) so you can
      spot the difference instantly.
"""
    )

    st.header("5. Tips & troubleshooting")
    st.markdown(
        """
- **Weird characters crash?** Save the file as `.xlsx` and re-upload — Excel sidesteps CSV encoding entirely.
- **HR renamed their columns?** Update the three ⚙️ Schema Mapping fields in the sidebar; don't touch the code.
- **"NO RULE" rows?** Add the missing (`Department`, `Position`) combination to the Rule Book,
      or add a `*` wildcard row for that position.
- **Store renamed or closed?** Update `Store_Master` — the Rule Book and history stay untouched.
- **Lost the audit log?** It only persists if you download `Access_Audit.csv`. Make that part of the monthly routine.
"""
    )


# ============================================================ UI =======
if page == "📖 How to Use":
    render_docs()
    st.stop()

st.title("🛡️ Power BI Security & Governance Command Center")
st.caption("Local-only RLS engine · delta tracking · access audit · query tool. Nothing leaves this machine.")

tab_rls, tab_delta, tab_audit, tab_query = st.tabs(
    ["🔐 RLS Engine", "🔄 Delta Tracking", "📋 Access Audit & Gap Analysis",
     "🔍 Access Query Tool"]
)


# ------------------------------------------------------- TAB 1: RLS ---
with tab_rls:
    st.header("Simulate & Combine → Final_RLS.csv")
    st.caption(
        "Upload the monthly HR Staff List (Excel), the Rule_Book.csv "
        "(Department as Store_Code + Position → Store_Access & report access), "
        "optional Exceptions.csv, and the Store_Master for friendly store names. "
        f"Multiple stores in Store_Access use '{STORE_SEP}' and are exploded into one row per store. "
        "CSV files are read with encoding auto-detection (utf-8-sig → cp1252); "
        "Excel uploads avoid encoding issues entirely."
    )

    with st.container(border=True):
        st.subheader("📤 Inputs")
        c1, c2 = st.columns(2)
        with c1:
            hr_up = st.file_uploader("HR Staff List (.xlsx)", type=["xlsx", "xls"], key="rls_hr")
            rules_up = st.file_uploader("Rule_Book (.csv / .xlsx)", type=["csv", "xlsx", "xls"], key="rls_rules")
        with c2:
            ex_up = st.file_uploader("Exceptions (.csv / .xlsx, optional)", type=["csv", "xlsx", "xls"], key="rls_ex")
            sm_up = st.file_uploader("Store_Master (.csv / .xlsx, optional)", type=["csv", "xlsx", "xls"], key="rls_sm")

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
            st.download_button(
                "Store_Master template",
                sample_store_master().to_csv(index=False).encode("utf-8-sig"),
                "Store_Master_template.csv",
                "text/csv",
            )

        if st.button("▶️ Simulate & Combine", type="primary", key="rls_go"):
            if not hr_up or not rules_up:
                st.error("Please upload both the HR Staff List and the Rule_Book.")
            else:
                try:
                    hr = read_hr_excel(hr_up, schema_mapping)
                    rules = read_table_upload(rules_up)
                    ex = read_table_upload(ex_up) if ex_up else None
                    sm = read_table_upload(sm_up) if sm_up else None
                    new_pos, new_dept = check_unmapped_master_data(hr, rules)
                    warn_unmapped(new_pos, new_dept)
                    final, warns = simulate_rls(hr, rules, ex, sm)
                    st.session_state["final_rls"] = final
                    st.session_state["hr_current"] = hr
                    st.session_state["hr_current_name"] = hr_up.name
                    st.session_state["store_master_current"] = sm
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
        with st.container(border=True):
            st.subheader("Final_RLS.csv preview (one row per user per store)")
            st.dataframe(final, use_container_width=True)
            st.download_button(
                "⬇️ Download Final_RLS.csv",
                final.to_csv(index=False).encode("utf-8-sig"),
                "Final_RLS.csv",
                "text/csv",
            )


# ----------------------------------------------------- TAB 2: DELTA ---
with tab_delta:
    st.header("Personnel Movement — Joiners / Leavers / Movers")
    st.caption(
        "Upload the previous HR list and the new HR list. "
        "Leavers are flagged for access revocation; joiners get suggested access from the Rule_Book. "
        "New Positions/Departments missing from the Rule_Book trigger a bright warning."
    )

    with st.container(border=True):
        st.subheader("📤 Inputs")
        d1, d2, d3 = st.columns(3)
        with d1:
            old_up = st.file_uploader("Previous HR List (.xlsx)", type=["xlsx", "xls"], key="delta_old")
        with d2:
            new_up = st.file_uploader("New HR List (.xlsx)", type=["xlsx", "xls"], key="delta_new")
        with d3:
            delta_rules_up = st.file_uploader("Rule_Book (.csv / .xlsx)", type=["csv", "xlsx", "xls"], key="delta_rules")

        if st.button("🔍 Compare", type="primary", key="delta_go"):
            if not old_up or not new_up:
                st.error("Please upload both the previous and the new HR list.")
            else:
                try:
                    old = read_hr_excel(old_up, schema_mapping)
                    new = read_hr_excel(new_up, schema_mapping)
                    rules = read_table_upload(delta_rules_up) if delta_rules_up else None
                    sm = st.session_state["store_master_current"]
                    if rules is not None:
                        warn_unmapped(*check_unmapped_master_data(new, rules))
                    res = compute_deltas(old, new, rules, sm)
                    st.session_state["delta_res"] = res
                    st.session_state["hr_current"] = new
                    st.session_state["hr_current_name"] = new_up.name
                except ValueError as e:
                    st.error(f"⚠️ {e}")
                except Exception as e:
                    st.error(f"⚠️ Unexpected error: {e}")

    res = st.session_state.get("delta_res")
    if res:
        with st.container(border=True):
            st.subheader("📊 Movement results")
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
                show = [c for c in [EMAIL, DEPT, POS, STORE_ACCESS, STORE_NAME, REPORT_ACCESS, "Source"]
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

    with st.container(border=True):
        st.subheader("📜 Audit log")
        audit = st.session_state["audit_log"]
        if not audit.empty:
            st.dataframe(audit, use_container_width=True)
            c1, c2 = st.columns(2)
            with c1:
                st.download_button(
                    "⬇️ Download Access_Audit.csv",
                    audit.to_csv(index=False).encode("utf-8-sig"),
                    "Access_Audit.csv",
                    "text/csv",
                )
            with c2:
                audit_up = st.file_uploader("…or load an existing Access_Audit (.csv / .xlsx)",
                                            type=["csv", "xlsx", "xls"], key="audit_load")
                if audit_up:
                    try:
                        loaded = read_table_upload(audit_up)
                        _require_cols(loaded, ["Date", EMAIL, "Asset_Name", "Permission_Level"], "Access_Audit")
                        if "Remark" not in loaded.columns:
                            loaded["Remark"] = ""
                        st.session_state["audit_log"] = loaded
                        st.success(f"Loaded {len(loaded)} audit rows.")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"⚠️ {e}")
        else:
            st.markdown(
                "No audit entries yet.\n\n"
                "1. Use the **➕ Log granted access** form above to record each manual grant.\n"
                "2. Or load an existing `Access_Audit` file with the uploader below.\n"
                "3. Download `Access_Audit.csv` before closing — the log lives in memory."
            )

    with st.container(border=True):
        st.subheader("🔎 Gap Analysis")
        g1, g2 = st.columns(2)
        with g1:
            gap_hr_up = st.file_uploader("Current HR List (.xlsx)", type=["xlsx", "xls"], key="gap_hr")
        with g2:
            gap_rules_up = st.file_uploader("Rule_Book (.csv / .xlsx)", type=["csv", "xlsx", "xls"], key="gap_rules")

        # Default to the HR list already in session (from RLS or Delta tabs).
        if st.button("Run Gap Analysis", type="primary", key="gap_go"):
            try:
                hr = read_hr_excel(gap_hr_up, schema_mapping) if gap_hr_up else st.session_state["hr_current"]
                if hr is None:
                    st.error("Upload a current HR list (or run the RLS / Delta tab first).")
                elif not gap_rules_up:
                    st.error("Please upload the Rule_Book.")
                else:
                    rules = read_table_upload(gap_rules_up)
                    sm = st.session_state["store_master_current"]
                    warn_unmapped(*check_unmapped_master_data(hr, rules))
                    expected, warns = simulate_rls(hr, rules, None, sm)
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


# ----------------------------------------------------- TAB 4: QUERY ---
with tab_query:
    st.header("🔍 Access Query Tool — Effective Access Resolver")
    st.caption(
        "Search by user to see their stores (RLS logic) and reports (audit register), "
        "or search by asset to list everyone who can reach it."
    )

    final_q = st.session_state.get("final_rls")
    audit_q = st.session_state["audit_log"]
    if final_q is None:
        with st.container(border=True):
            st.subheader("👆 One step before you can query")
            st.markdown(
                "1. Go to the **🔐 RLS Engine** tab.\n"
                "2. Upload your HR Staff List and Rule_Book, then click **▶️ Simulate & Combine**.\n"
                "3. Come back here — the query tool reads the latest `Final_RLS` from memory."
            )
    else:
        with st.container(border=True):
            mode = st.radio("Search mode", ["By User (Email)", "By Asset (Store / Report)"],
                            horizontal=True, key="query_mode")

            if mode == "By User (Email)":
                q = st.text_input("Work Email", key="query_user").strip().lower()
                if q:
                    user_rows = final_q[final_q[EMAIL].str.strip().str.lower() == q]
                    if user_rows.empty:
                        st.warning(f"No RLS rows found for '{q}'. Check the email spelling.")
                    else:
                        person = user_rows.iloc[0]
                        st.subheader(f"👤 {person[EMAIL]} — {person[DEPT]} / {person[POS]}")
                        st.markdown("**🏬 Stores visible (RLS):**")
                        st.dataframe(
                            user_rows[[STORE_ACCESS, STORE_NAME, "Source"]].drop_duplicates(),
                            use_container_width=True,
                        )
                        st.markdown("**📊 Reports granted (audit register):**")
                        granted = audit_q[audit_q[EMAIL].str.strip().str.lower() == q] \
                            if not audit_q.empty else audit_q
                        if not granted.empty:
                            st.dataframe(
                                granted[["Date", "Asset_Name", "Permission_Level", "Remark"]],
                                use_container_width=True,
                            )
                        else:
                            st.info("No report grants logged for this user yet.")
            else:
                q = st.text_input("Store code / store name / report name", key="query_asset").strip()
                if q:
                    ql = q.lower()
                    # --- store hits (RLS-derived) ---
                    store_hits = final_q[
                        final_q[STORE_ACCESS].str.lower().str.contains(ql, na=False, regex=False)
                        | final_q[STORE_NAME].str.lower().str.contains(ql, na=False, regex=False)
                    ]
                    if not store_hits.empty:
                        st.subheader(f"🏬 Users with RLS access to store '{q}'")
                        st.dataframe(
                            store_hits[[EMAIL, DEPT, POS, STORE_ACCESS, STORE_NAME, "Source"]]
                            .drop_duplicates().sort_values(EMAIL),
                            use_container_width=True,
                        )
                    # --- report hits: expected (rules) vs actual (audit) ---
                    exp_hits = final_q[
                        final_q[REPORT_ACCESS].str.lower().str.contains(ql, na=False, regex=False)
                    ]
                    act_hits = audit_q[
                        audit_q["Asset_Name"].str.lower().str.contains(ql, na=False, regex=False)
                    ] if not audit_q.empty else pd.DataFrame()
                    if not exp_hits.empty or not act_hits.empty:
                        st.subheader(f"📊 Report access for '{q}'")
                        if not exp_hits.empty:
                            st.markdown("*Should have (per RLS rules):*")
                            st.dataframe(
                                exp_hits[[EMAIL, DEPT, POS]].drop_duplicates().sort_values(EMAIL),
                                use_container_width=True,
                            )
                        if not act_hits.empty:
                            st.markdown("*Actually granted (audit register):*")
                            st.dataframe(
                                act_hits[[EMAIL, "Permission_Level", "Date", "Remark"]]
                                .drop_duplicates().sort_values(EMAIL),
                                use_container_width=True,
                            )
                    if store_hits.empty and exp_hits.empty and act_hits.empty:
                        st.warning(f"Nothing found matching '{q}'.")
