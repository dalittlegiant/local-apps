"""Governance rule engine: RLS simulation, delta tracking, gap analysis.

Pure logic — no ``st.*`` calls. Ported from the Power BI Security &
Governance Command Center v4 and reframed platform-agnostic: the engine
maps people (Work Email / Department / Position) to assets via a rule book.
"Assets" were stores in the Power BI incarnation; the column contracts are
unchanged so existing Rule_Book / Exceptions / master files keep working.

Repo conventions applied: joins on real columns only (no temp keys),
anti-joins with ``indicator=True``, unmatched rows stay visible.
"""

import pandas as pd

from .csv_loader import (
    DEPT, EMAIL, POS, REPORT_ACCESS, REPORT_SEP, STORE_ACCESS, STORE_NAME,
    STORE_SEP, _require_cols, split_list,
)


# ---------------------------------------------------------------- samples
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


# ---------------------------------------------------------------- engine
def explode_store_access(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten Store_Access on ':' so one user with 'A:B' becomes two rows.

    Rows with no store keep a single blank row so they stay visible.
    """
    df = df.copy()
    parts = df[STORE_ACCESS].apply(lambda s: split_list(s, STORE_SEP))
    has_store = parts.map(len) > 0

    exploded = df[has_store].copy()
    exploded[STORE_ACCESS] = parts[has_store]
    exploded = exploded.explode(STORE_ACCESS)

    rest = df[~has_store].copy()
    rest[STORE_ACCESS] = ""

    return pd.concat([exploded, rest], ignore_index=True)


def apply_store_master(df: pd.DataFrame,
                       store_master: pd.DataFrame | None) -> pd.DataFrame:
    """Join asset code -> friendly name. Falls back to the code itself when
    no master is provided or a code is unknown."""
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


def simulate_rls(hr: pd.DataFrame,
                 rules: pd.DataFrame,
                 exceptions: pd.DataFrame | None,
                 store_master: pd.DataFrame | None = None,
                 ) -> tuple[pd.DataFrame, list[str]]:
    """Merge HR + Rule_Book (+ Exceptions) into the final access table.

    Rule matching on (Department, Position): exact match first, then the
    ``*`` department wildcard for that position. Per-email exceptions win.
    Store_Access is exploded on ':' into one row per asset, then resolved to
    friendly names via the master. Returns (final_df, warnings).
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

    # Exceptions win per email; empty cells keep the rule value.
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


def check_unmapped_master_data(hr: pd.DataFrame,
                               rules: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Positions/Departments present in HR but missing from the Rule_Book."""
    hr_pos = {p for p in hr[POS].unique() if p}
    hr_dept = {d for d in hr[DEPT].unique() if d}
    rule_pos = set(rules[POS].unique()) if POS in rules.columns else set()
    rule_dept = (set(rules[DEPT].unique()) - {"*"}) if DEPT in rules.columns else set()
    return sorted(hr_pos - rule_pos), sorted(hr_dept - rule_dept)


def compute_deltas(old: pd.DataFrame,
                   new: pd.DataFrame,
                   rules: pd.DataFrame | None,
                   store_master: pd.DataFrame | None = None,
                   ) -> dict[str, pd.DataFrame]:
    """Leavers / Joiners / Movers between two HR snapshots, joined strictly
    on the 'Work Email' column. Joiners get suggested access via simulate_rls.
    """
    leavers = old.merge(new[[EMAIL]], on=EMAIL, how="left", indicator=True)
    leavers = leavers[leavers["_merge"] == "left_only"].drop(columns=["_merge"])

    joiners = new.merge(old[[EMAIL]], on=EMAIL, how="left", indicator=True)
    joiners = joiners[joiners["_merge"] == "left_only"].drop(columns=["_merge"])

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


def gap_analysis(expected: pd.DataFrame,
                 audit: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
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
