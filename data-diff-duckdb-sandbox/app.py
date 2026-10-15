"""App 5 — Local Parquet/CSV SQL Sandbox & Dataset Diff Engine.

1. Instant Profiler & DuckDB SQL Runner — drop .parquet/.csv/.xlsx files,
   see schema + null %, query with SQL, export subsets. Large files are
   staged ONCE to the OS temp dir and scanned natively by DuckDB (no pandas
   round-trip, no re-parse on reruns); the SQL form runs only on explicit
   submit; previews are capped at 1,000 rows with full DuckDB-backed export.
2. Dataset Version Diff Engine — old vs new on primary key(s): added /
   deleted rows, schema discrepancies, cell-level old -> new changes.

Pure logic lives in diff_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import io
import os
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import diff_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="DuckDB SQL & Diff Sandbox",
                       page_icon="🦆", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "dd5_"
PREVIEW_LIMIT = 1000


# ------------------------------------------------------------ plumbing
def _con():
    if P + "con" not in st.session_state:
        st.session_state[P + "con"] = duckdb.connect()
    return st.session_state[P + "con"]


def _registry():
    """Ingest-once cache: (name, size[, sheet]) -> {tname, kind, path}."""
    return st.session_state.setdefault(P + "registry", {})


def _unique_tname(base: str) -> str:
    taken = {v["tname"] for v in _registry().values()}
    tname, i = base, 2
    while tname in taken:
        tname = f"{base}_{i}"
        i += 1
    return tname


def _sheet_names(up) -> list:
    key = (P + "sheets", up.name, up.size)
    if key not in st.session_state:
        st.session_state[key] = core.excel_sheets(up.getvalue())
    return st.session_state[key]


def _ingest(up, sheet=None) -> str:
    """Stage + register an upload exactly once per (name, size, sheet).

    parquet/csv → staged to the OS temp dir, scanned natively by DuckDB
    (VIEW — the file never becomes a pandas DataFrame). xlsx → parsed
    once via pandas, materialized as a DuckDB TABLE. Returns the table
    name. Never re-parses on Streamlit reruns.
    """
    key = (up.name, up.size, sheet)
    reg = _registry()
    if key in reg:
        return reg[key]["tname"]
    con = _con()
    base = core.sanitize_table_name(up.name)
    lname = up.name.lower()
    if lname.endswith((".xlsx", ".xls")):
        df = core.load_upload(up.name, up.getvalue(), sheet=sheet)
        tname = _unique_tname(f"{base}_{core.sanitize_table_name(str(sheet))}")
        con.register("__dd5_tmp", df)
        try:
            con.execute(f'CREATE OR REPLACE TABLE "{tname}" '
                        'AS SELECT * FROM "__dd5_tmp"')
        finally:
            try:
                con.unregister("__dd5_tmp")
            except Exception:
                pass
        reg[key] = {"tname": tname, "kind": "table", "path": None}
    else:
        path = core.write_upload_to_temp(up.name, up.getvalue())
        tname = _unique_tname(base)
        clause = core.duckdb_source_clause(path, up.name)
        con.execute(f'CREATE OR REPLACE VIEW "{tname}" AS SELECT * FROM {clause}')
        reg[key] = {"tname": tname, "kind": "view", "path": path}
    return tname


def _drop_all():
    con = _con()
    for meta in _registry().values():
        for kind in ("VIEW", "TABLE"):
            try:
                con.execute(f'DROP {kind} IF EXISTS "{meta["tname"]}"')
            except Exception:
                pass
        if meta.get("path"):
            try:
                Path(meta["path"]).unlink(missing_ok=True)
            except Exception:
                pass
    st.session_state[P + "registry"] = {}
    for k in [k for k in st.session_state
              if k == P + "last_res" or (isinstance(k, tuple) and k[0] == P + "sheets")]:
        st.session_state.pop(k, None)


def _diff_df(up, tag):
    """Diff-tab DataFrames, parsed once per (tag, name, size)."""
    key = (P + "diffdf", tag, up.name, up.size)
    if key not in st.session_state:
        st.session_state[key] = core.load_upload(up.name, up.getvalue())
    return st.session_state[key]


# ------------------------------------------------------------ querying
_SELECT_LIKE = ("SELECT", "WITH", "VALUES", "TABLE", "FROM", "PIVOT", "UNPIVOT",
                "DESCRIBE", "EXPLAIN", "SUMMARIZE", "SHOW", "PRAGMA")


def _run_query(sql: str) -> dict:
    """Execute only on explicit form submit. Never runs on stray reruns.

    Returns {"sql", "total", "preview", "ms", ...} or {"error": msg}.
    """
    con = _con()
    clean = sql.strip().rstrip(";").strip()
    if not clean:
        return {"error": "SQL is empty."}
    first = clean.split(None, 1)[0].upper() if clean.split() else ""
    t0 = time.perf_counter()
    try:
        if first in _SELECT_LIKE:
            total = con.execute(f"SELECT COUNT(*) FROM ({clean})").fetchone()[0]
            preview = con.execute(
                f"SELECT * FROM ({clean}) LIMIT {PREVIEW_LIMIT}").fetchdf()
            ms = (time.perf_counter() - t0) * 1000
            return {"sql": clean, "total": int(total), "preview": preview,
                    "ms": ms}
        res = con.execute(clean)
        try:
            preview = res.fetchdf().head(PREVIEW_LIMIT)
        except Exception:
            preview = pd.DataFrame()
        ms = (time.perf_counter() - t0) * 1000
        return {"sql": clean, "total": None, "preview": preview, "ms": ms,
                "note": "Statement executed."}
    except Exception as exc:
        return {"error": f"SQL error: {exc}"}


def _full_export(sql: str, fmt: str):
    """COPY the full query result to temp via DuckDB (no pandas).

    Returns (filename, bytes, mime). Runs only on explicit button click.
    """
    con = _con()
    suffix = ".csv" if fmt == "csv" else ".parquet"
    fd, path = tempfile.mkstemp(prefix="dd5_full_", suffix=suffix)
    os.close(fd)
    try:
        if fmt == "csv":
            con.execute(f"COPY ({sql}) TO '{path}' (HEADER, DELIMITER ',')")
            mime = "text/csv"
        else:
            con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")
            mime = "application/octet-stream"
        return f"query_result{suffix}", Path(path).read_bytes(), mime
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


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


# ==================================================================== UI
st.title("🦆 Local SQL Sandbox & Dataset Diff Engine")
st.caption("Inspect large local datasets and diff file versions — no Excel "
           "freezing, nothing leaves this machine.")

tab_sql, tab_diff = st.tabs(["🔍 Profiler & SQL Runner", "⚖️ Version Diff Engine"])

# ============================================================ TAB 1 ===
with tab_sql:
    st.header("Drop files, query with SQL")
    with st.container(border=True):
        ups = st.file_uploader("Data files (.parquet / .csv / .xlsx)",
                               type=["parquet", "csv", "xlsx", "xls"],
                               accept_multiple_files=True, key=P + "ups")
        st.caption("Uploads up to 500 MB. Each file is staged **once** to "
                   "your OS temp folder and scanned natively by DuckDB — "
                   "no re-parse when you click around, and temp files are "
                   "never inside the repo.")

    if ups:
        tnames = []
        for up in ups:
            lname = up.name.lower()
            try:
                if lname.endswith((".xlsx", ".xls")):
                    sheets = _sheet_names(up)
                    sheet = st.selectbox(
                        f"Sheet for {up.name}", sheets,
                        key=P + f"sheet_{up.name}_{up.size}")
                    tnames.append(_ingest(up, sheet=sheet))
                else:
                    tnames.append(_ingest(up))
            except ValueError as e:
                st.error(f"⚠️ {up.name}: {e}")

        if tnames:
            st.success(f"Registered {len(tnames)} table(s): "
                       + ", ".join(f"`{t}`" for t in tnames))

            with st.container(border=True):
                st.subheader("📋 Instant profiler")
                st.caption("Runs inside DuckDB — large files are never "
                           "loaded into Python memory.")
                for tname in tnames:
                    with st.expander(f"`{tname}`"):
                        try:
                            prof = core.profile_duckdb(_con(), tname)
                        except Exception as e:
                            st.error(f"⚠️ Could not profile `{tname}`: {e}")
                            continue
                        st.markdown(f"{prof['rows']:,} rows × {prof['cols']} cols")
                        st.dataframe(core.profile_frame(prof),
                                     use_container_width=True, hide_index=True)

            with st.container(border=True):
                st.subheader("SQL editor")
                default_sql = f"SELECT * FROM {tnames[0]} LIMIT 100"
                st.session_state.setdefault(P + "sql", default_sql)
                with st.form(key=P + "sqlform"):
                    st.text_area("DuckDB SQL", height=140, key=P + "sql")
                    run = st.form_submit_button("▶️ Run query", type="primary")
                if run:
                    with st.spinner("Running query…"):
                        st.session_state[P + "last_res"] = _run_query(
                            st.session_state[P + "sql"])

            res = st.session_state.get(P + "last_res")
            if res:
                if res.get("error"):
                    st.error(f"⚠️ {res['error']}")
                else:
                    with st.container(border=True):
                        st.subheader("Results")
                        total_note = (f"{res['total']:,} total rows"
                                      if res["total"] is not None
                                      else "total row count n/a")
                        st.caption(f"Showing top {len(res['preview']):,} of "
                                   f"{total_note} · {res['ms']:.0f} ms")
                        if res.get("note"):
                            st.caption(res["note"])
                        if not res["preview"].empty:
                            st.dataframe(res["preview"], use_container_width=True)
                        else:
                            st.info("Query ran successfully — no rows to preview.")
                        st.markdown("**Download preview** (top "
                                    f"{PREVIEW_LIMIT:,} rows)")
                        _export_buttons(res["preview"], "query_preview",
                                        P + "prev")
                        if res.get("sql"):
                            st.markdown("**Download full result** "
                                        "(DuckDB COPY, no Python memory)")
                            e1, e2 = st.columns(2)
                            with e1:
                                if st.button("⬇️ Full result as CSV",
                                             key=P + "full_csv"):
                                    with st.spinner("Exporting full result…"):
                                        fn, data, mime = _full_export(
                                            res["sql"], "csv")
                                        st.download_button(
                                            "💾 Save query_result.csv", data,
                                            fn, mime, key=P + "dl_csv")
                            with e2:
                                if st.button("⬇️ Full result as Parquet",
                                             key=P + "full_pq"):
                                    with st.spinner("Exporting full result…"):
                                        fn, data, mime = _full_export(
                                            res["sql"], "parquet")
                                        st.download_button(
                                            "💾 Save query_result.parquet",
                                            data, fn, mime, key=P + "dl_pq")

            if st.button("🗑️ Clear all tables", key=P + "clear"):
                _drop_all()
                st.rerun()
    else:
        with st.container(border=True):
            st.subheader("👋 Start by uploading a data file")
            st.markdown(
                "1. **Upload** one or more `.parquet`, `.csv`, or `.xlsx` "
                "files above (up to 500 MB each).\n"
                "2. **Profile** — check schema, null %, and cardinality "
                "without loading the file into memory.\n"
                "3. **Query** — write DuckDB SQL and hit **Run query**. "
                "Only the top 1,000 rows preview; export the full result "
                "with the DuckDB-backed buttons.\n"
                "4. **Diff** — use the *Version Diff Engine* tab to compare "
                "two snapshots on a primary key.\n\n"
                "Everything runs on this machine. Uploaded files are staged "
                "in your OS temp folder and deleted when you clear the "
                "tables — nothing is committed to the repo.")

# ============================================================ TAB 2 ===
with tab_diff:
    st.header("Compare two dataset versions")
    st.caption("Upload the old and new snapshots, pick the primary key "
               "column(s), and get added/deleted rows, schema discrepancies, "
               "and cell-level old → new changes.")

    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            old_up = st.file_uploader("Old version",
                                      type=["parquet", "csv", "xlsx", "xls"],
                                      key=P + "old")
        with c2:
            new_up = st.file_uploader("New version",
                                      type=["parquet", "csv", "xlsx", "xls"],
                                      key=P + "new")

    if old_up and new_up:
        try:
            old = _diff_df(old_up, "old")
            new = _diff_df(new_up, "new")
        except ValueError as e:
            st.error(f"⚠️ {e}")
            st.stop()
        common_cols = [c for c in old.columns if c in new.columns]
        if not common_cols:
            st.error("The two files share no column names — nothing to diff.")
            st.stop()
        with st.container(border=True):
            keys = st.multiselect("Primary key column(s)", common_cols,
                                  default=[common_cols[0]], key=P + "keys")
            if st.button("⚖️ Run diff", type="primary", key=P + "go"):
                try:
                    st.session_state[P + "diff"] = core.diff_datasets(old, new,
                                                                     keys)
                except ValueError as e:
                    st.error(f"⚠️ {e}")

        res = st.session_state.get(P + "diff")
        if res:
            s = res["summary"]
            for w in res["warnings"]:
                st.warning(w)
            with st.container(border=True):
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Old rows", f"{s['old_rows']:,}")
                m2.metric("New rows", f"{s['new_rows']:,}")
                m3.metric("➕ Added", f"{s['added']:,}")
                m4.metric("➖ Deleted", f"{s['deleted']:,}")
                m5.metric("✏️ Changed cells", f"{s['changed_cells']:,}")

            with st.container(border=True):
                st.subheader("Schema discrepancies")
                if res["schema"].empty:
                    st.success("Schemas match. ✅")
                else:
                    st.dataframe(res["schema"], use_container_width=True,
                                 hide_index=True)

            with st.container(border=True):
                st.subheader(f"➕ Added rows ({len(res['added']):,})")
                if res["added"].empty:
                    st.info("None.")
                else:
                    st.dataframe(res["added"].head(500), use_container_width=True)
                    _export_buttons(res["added"], "added_rows", P + "added")

            with st.container(border=True):
                st.subheader(f"➖ Deleted rows ({len(res['deleted']):,})")
                if res["deleted"].empty:
                    st.info("None.")
                else:
                    st.dataframe(res["deleted"].head(500), use_container_width=True)
                    _export_buttons(res["deleted"], "deleted_rows", P + "deleted")

            with st.container(border=True):
                st.subheader(f"✏️ Cell-level changes ({len(res['changed_cells']):,})")
                if res["changed_cells"].empty:
                    st.success("No value changes on the shared keys. ✅")
                else:
                    st.dataframe(res["changed_cells"].head(1000),
                                 use_container_width=True)
                    _export_buttons(res["changed_cells"], "changed_cells",
                                    P + "changed")
    else:
        with st.container(border=True):
            st.subheader("👋 Compare two snapshots")
            st.markdown(
                "1. **Upload** the old version (left) and the new version "
                "(right).\n"
                "2. **Pick** the primary key column(s) they share.\n"
                "3. **Run diff** — see added/deleted rows, schema "
                "discrepancies, and cell-level old → new changes.")
