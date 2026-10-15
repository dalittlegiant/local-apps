"""App 5 — Local Parquet/CSV SQL Sandbox & Dataset Diff Engine.

1. Instant Profiler & DuckDB SQL Runner — drop .parquet/.csv/.xlsx files,
   see schema + null % + memory, query with SQL, export subsets.
2. Dataset Version Diff Engine — old vs new on primary key(s): added /
   deleted rows, schema discrepancies, cell-level old -> new changes.

Pure logic lives in diff_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import io
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

P = "dd5_"


def _con():
    if P + "con" not in st.session_state:
        st.session_state[P + "con"] = duckdb.connect()
    return st.session_state[P + "con"]


def _tables() -> dict:
    return st.session_state.setdefault(P + "tables", {})  # name -> DataFrame


def _export_buttons(df: pd.DataFrame, stem: str, key: str):
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("⬇️ CSV", df.to_csv(index=False).encode("utf-8-sig"),
                           f"{stem}.csv", "text/csv", key=key + "_csv")
    with c2:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="data")
        st.download_button("⬇️ Excel", buf.getvalue(), f"{stem}.xlsx",
                           "application/vnd.openxmlformats-officedocument."
                           "spreadsheetml.sheet", key=key + "_xlsx")
    with c3:
        buf = io.BytesIO()
        df.to_parquet(buf, index=False)
        st.download_button("⬇️ Parquet", buf.getvalue(), f"{stem}.parquet",
                           "application/octet-stream", key=key + "_pq")


st.title("🦆 Local SQL Sandbox & Dataset Diff Engine")
st.caption("Inspect large local datasets and diff file versions — no Excel "
           "freezing, nothing leaves this machine.")

tab_sql, tab_diff = st.tabs(["🔍 Profiler & SQL Runner", "⚖️ Version Diff Engine"])

# ============================================================ TAB 1 ===
with tab_sql:
    st.header("Drop files, query with SQL")
    ups = st.file_uploader("Data files (.parquet / .csv / .xlsx)",
                           type=["parquet", "csv", "xlsx", "xls"],
                           accept_multiple_files=True, key=P + "ups")

    if ups:
        for up in ups:
            raw = up.getvalue()
            base = core.sanitize_table_name(up.name)
            lname = up.name.lower()
            if lname.endswith((".xlsx", ".xls")):
                try:
                    sheets = core.excel_sheets(raw)
                except ValueError as e:
                    st.error(f"⚠️ {up.name}: {e}")
                    continue
                sheet = st.selectbox(f"Sheet for {up.name}", sheets,
                                     key=P + f"sheet_{up.name}")
                tname = f"{base}_{core.sanitize_table_name(str(sheet))}"
                df = core.load_upload(up.name, raw, sheet=sheet)
            else:
                tname, df, sheet = base, core.load_upload(up.name, raw), None
            # de-duplicate table names
            orig, i = tname, 2
            tables = _tables()
            while tname in tables and not tables[tname].equals(df):
                tname = f"{orig}_{i}"
                i += 1
            if tname not in tables:
                tables[tname] = df
                _con().register(tname, df)

        tables = _tables()
        st.success(f"Registered {len(tables)} table(s): "
                   + ", ".join(f"`{t}`" for t in tables))

        with st.expander("📋 Instant profiler (schema, null %, memory)"):
            for tname, df in tables.items():
                prof = core.profile_df(df)
                mb = prof["memory_bytes"] / 1e6
                st.markdown(f"**`{tname}`** — {prof['rows']:,} rows × "
                            f"{prof['cols']} cols · {mb:.1f} MB")
                st.dataframe(core.profile_frame(prof), use_container_width=True,
                             hide_index=True)

        st.subheader("SQL editor")
        default_sql = f"SELECT * FROM {next(iter(tables))} LIMIT 100"
        sql = st.text_area("DuckDB SQL", value=default_sql, height=140,
                           key=P + "sql")
        if st.button("▶️ Run query", type="primary", key=P + "run"):
            try:
                res = core.run_sql(_con(), sql)
                st.session_state[P + "last_res"] = res
                st.success(f"{len(res):,} row(s) × {len(res.columns)} col(s).")
            except ValueError as e:
                st.error(f"⚠️ {e}")
        res = st.session_state.get(P + "last_res")
        if res is not None:
            st.dataframe(res, use_container_width=True)
            _export_buttons(res, "query_result", P + "res")

        if st.button("🗑️ Clear all tables", key=P + "clear"):
            for t in list(_tables()):
                try:
                    _con().execute(f'DROP VIEW IF EXISTS "{t}"')
                except Exception:
                    pass
            st.session_state[P + "tables"] = {}
            st.session_state.pop(P + "last_res", None)
            st.rerun()
    else:
        st.info("👆 Upload .parquet, .csv, or .xlsx files to start.")

# ============================================================ TAB 2 ===
with tab_diff:
    st.header("Compare two dataset versions")
    st.caption("Upload the old and new snapshots, pick the primary key "
               "column(s), and get added/deleted rows, schema discrepancies, "
               "and cell-level old → new changes.")

    c1, c2 = st.columns(2)
    with c1:
        old_up = st.file_uploader("Old version", type=["parquet", "csv", "xlsx", "xls"],
                                  key=P + "old")
    with c2:
        new_up = st.file_uploader("New version", type=["parquet", "csv", "xlsx", "xls"],
                                  key=P + "new")

    if old_up and new_up:
        try:
            old = core.load_upload(old_up.name, old_up.getvalue())
            new = core.load_upload(new_up.name, new_up.getvalue())
        except ValueError as e:
            st.error(f"⚠️ {e}")
            st.stop()
        common_cols = [c for c in old.columns if c in new.columns]
        if not common_cols:
            st.error("The two files share no column names — nothing to diff.")
            st.stop()
        keys = st.multiselect("Primary key column(s)", common_cols,
                              default=[common_cols[0]], key=P + "keys")

        if st.button("⚖️ Run diff", type="primary", key=P + "go"):
            try:
                st.session_state[P + "diff"] = core.diff_datasets(old, new, keys)
            except ValueError as e:
                st.error(f"⚠️ {e}")

        res = st.session_state.get(P + "diff")
        if res:
            s = res["summary"]
            for w in res["warnings"]:
                st.warning(w)
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Old rows", f"{s['old_rows']:,}")
            m2.metric("New rows", f"{s['new_rows']:,}")
            m3.metric("➕ Added", f"{s['added']:,}")
            m4.metric("➖ Deleted", f"{s['deleted']:,}")
            m5.metric("✏️ Changed cells", f"{s['changed_cells']:,}")

            st.subheader("Schema discrepancies")
            if res["schema"].empty:
                st.success("Schemas match. ✅")
            else:
                st.dataframe(res["schema"], use_container_width=True, hide_index=True)

            st.subheader(f"➕ Added rows ({len(res['added']):,})")
            if res["added"].empty:
                st.info("None.")
            else:
                st.dataframe(res["added"].head(500), use_container_width=True)
                _export_buttons(res["added"], "added_rows", P + "added")

            st.subheader(f"➖ Deleted rows ({len(res['deleted']):,})")
            if res["deleted"].empty:
                st.info("None.")
            else:
                st.dataframe(res["deleted"].head(500), use_container_width=True)
                _export_buttons(res["deleted"], "deleted_rows", P + "deleted")

            st.subheader(f"✏️ Cell-level changes ({len(res['changed_cells']):,})")
            if res["changed_cells"].empty:
                st.success("No value changes on the shared keys. ✅")
            else:
                st.dataframe(res["changed_cells"].head(1000), use_container_width=True)
                _export_buttons(res["changed_cells"], "changed_cells", P + "changed")
    else:
        st.info("👆 Upload both versions to compare.")
