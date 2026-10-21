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
import traceback
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


def _sweep_stale_staged_files(max_age_hours: float = 24) -> None:
    """Delete staged upload temp files (`dd5_*` in the OS temp dir) left
    behind by earlier sessions (e.g. the tab was closed without "Clear
    all tables"). Runs once per app start; never touches the repo."""
    import shutil
    from pathlib import Path
    now = time.time()
    base = Path(tempfile.gettempdir())
    for p in base.glob("dd5_*"):
        try:
            if p.is_file() and now - p.stat().st_mtime > max_age_hours * 3600:
                p.unlink(missing_ok=True)
            elif p.is_dir() and now - p.stat().st_mtime > max_age_hours * 3600:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            continue


_sweep_stale_staged_files()


# ------------------------------------------------------------ plumbing
@st.cache_resource(show_spinner=False)
def _con():
    """Single persistent in-memory DuckDB connection for the app.

    Cached as a resource (not per-rerun, not per-session): views created
    at ingest live here, and DuckDB keeps file metadata hot between
    queries. Single-user local app — no cross-thread sharing concerns.
    """
    return duckdb.connect()


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


def _sheet_names_path(path_str: str) -> list:
    key = (P + "sheets", "path", path_str)
    if key not in st.session_state:
        p = Path(path_str)
        if not p.is_file():
            raise ValueError(f"File not found: {path_str}")
        st.session_state[key] = core.excel_sheets(p.read_bytes())
    return st.session_state[key]


def _norm_source(kind: str, raw) -> dict:
    """Normalize an upload or a local path into a source dict.

    kind="upload" → raw is an UploadedFile; kind="path" → raw is a string.
    """
    if kind == "upload":
        return {"kind": "upload", "up": raw, "label": raw.name,
                "key": ("upload", raw.name, raw.size)}
    s = str(raw).strip().strip('"').strip("'")
    p = Path(s)
    return {"kind": "path", "path": str(p), "label": p.name,
            "key": ("path", str(p.resolve()) if p.exists() else s)}


def _ingest_src(src: dict, sheet=None, safe_mode: bool = False) -> str:
    """Stage + register a source exactly once.

    Uploads: parquet/csv staged to the OS temp dir and scanned natively by
    DuckDB (VIEW); xlsx parsed once into a DuckDB TABLE.
    Local paths: parquet/csv are queried IN PLACE — DuckDB reads the file
    directly, bypassing Python memory entirely; xlsx is read once via pandas.
    ``safe_mode`` (CSV only) points the view at
    ``read_csv_auto(..., all_varchar=true)`` so a file whose deep rows
    violate the sniffed types still loads — every column as VARCHAR.
    Flipping it re-creates the view under the same table name.
    Returns the table name. Never re-parses on Streamlit reruns.
    """
    key = src["key"] + (sheet,)
    reg = _registry()
    con = _con()
    if src["kind"] == "upload":
        up = src["up"]
        lname, base, disp = up.name.lower(), core.sanitize_table_name(up.name), up.name
        raw = up.getvalue()
        staged = True
    else:
        p = Path(src["path"])
        if not p.is_file():
            raise ValueError(f"File not found: {src['path']}")
        lname, base, disp = p.name.lower(), core.sanitize_table_name(p.name), p.name
        raw, staged = None, False
    want_safe = bool(safe_mode) and lname.endswith(".csv")
    existing = reg.get(key)
    if existing is not None and existing.get("safe", False) == want_safe:
        return existing["tname"]
    if lname.endswith((".xlsx", ".xls")):
        data = raw if raw is not None else Path(src["path"]).read_bytes()
        df = core.load_upload(disp, data, sheet=sheet)
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
        reg[key] = {"tname": tname, "kind": "table", "path": None,
                    "safe": False}
    elif lname.endswith((".parquet", ".csv")):
        if staged:
            # Only the Safe Mode flag flipped → reuse the staged temp file
            # instead of staging (and leaking) a second copy.
            fpath = (existing or {}).get("path") \
                or core.write_upload_to_temp(disp, raw)
            cleanup = fpath
        else:
            fpath, cleanup = str(Path(src["path"])), None  # DuckDB reads in place
        tname = existing["tname"] if existing else _unique_tname(base)
        clause = core.duckdb_source_clause(fpath, disp, all_varchar=want_safe)
        con.execute(f'CREATE OR REPLACE VIEW "{tname}" AS SELECT * FROM {clause}')
        reg[key] = {"tname": tname, "kind": "view", "path": cleanup,
                    "safe": want_safe}
        # The (re)created view may have a different shape — drop any
        # profile cached against the old definition.
        prof_cache = st.session_state.get(P + "prof_cache")
        if prof_cache is not None:
            prof_cache.pop(tname, None)
    else:
        raise ValueError(f"Unsupported file type: {disp} (use .parquet/.csv/.xlsx)")
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
    st.session_state.pop(P + "prof_cache", None)
    for k in [k for k in st.session_state
              if k == P + "last_res" or (isinstance(k, tuple) and k[0] == P + "sheets")]:
        st.session_state.pop(k, None)


def _diff_df_src(src: dict, tag):
    """Diff-tab DataFrames, parsed once per source."""
    key = (P + "diffdf", tag) + src["key"]
    if key not in st.session_state:
        if src["kind"] == "upload":
            df = core.load_upload(src["up"].name, src["up"].getvalue())
        else:
            p = Path(src["path"])
            if not p.is_file():
                raise ValueError(f"File not found: {src['path']}")
            df = core.load_upload(p.name, p.read_bytes())
        st.session_state[key] = df
    return st.session_state[key]


# ------------------------------------------------------------ querying
_SELECT_LIKE = ("SELECT", "WITH", "VALUES", "TABLE", "FROM", "PIVOT", "UNPIVOT",
                "DESCRIBE", "EXPLAIN", "SUMMARIZE", "SHOW", "PRAGMA")


def _run_query(sql: str) -> dict:
    """Execute only on explicit form submit. Never runs on stray reruns.

    SELECT previews come back as zero-copy Arrow tables (no pandas
    conversion); Streamlit renders Arrow natively. Returns
    {"sql", "total", "preview", "ms", ...} or {"error": msg}.
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
                f"SELECT * FROM ({clean}) LIMIT {PREVIEW_LIMIT}"
            ).to_arrow_table()
            ms = (time.perf_counter() - t0) * 1000
            return {"sql": clean, "total": int(total), "preview": preview,
                    "ms": ms}
        res = con.execute(clean)
        try:
            preview = res.to_arrow_table()
            if preview.num_rows > PREVIEW_LIMIT:  # non-SELECT with output
                preview = preview.slice(0, PREVIEW_LIMIT)
        except Exception:
            preview = None
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


def _export_buttons(preview, stem: str, key: str):
    """Preview download buttons. Accepts an Arrow table (≤1,000 rows) or
    a pandas DataFrame; converts Arrow via to_pandas (trivial at this
    size). No buttons when there is no preview (e.g. DDL statements)."""
    if preview is None:
        return
    df = preview.to_pandas() if hasattr(preview, "to_pandas") else preview
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
    st.header("Drop files or point at local paths, query with SQL")
    with st.container(border=True):
        src_mode = st.radio("Input method", ("Upload File", "Read from Local Path"),
                            horizontal=True, key=P + "srcmode")
        safe_mode = st.toggle("Enable Safe Mode (Read all as String)",
                              value=False, key=P + "safe_mode")
        st.caption("Safe Mode applies to **CSV** files only: DuckDB reads "
                   "every column as text (`all_varchar=true`), bypassing "
                   "type inference so a file with dirty rows always loads. "
                   "Leave it OFF for normal typed loading — if a CSV fails "
                   "with a type conversion error, the profiler below shows "
                   "the exact line to cleanse, and this toggle is the "
                   "bypass. Parquet keeps its native types; Excel already "
                   "loads as text.")
        sources: list = []
        if src_mode == "Upload File":
            ups = st.file_uploader("Data files (.parquet / .csv / .xlsx)",
                                   type=["parquet", "csv", "xlsx", "xls"],
                                   accept_multiple_files=True, key=P + "ups")
            st.caption("Each file is staged **once** to your OS temp folder "
                       "and scanned natively by DuckDB — no re-parse when "
                       "you click around, and temp files are never inside "
                       "the repo.")
            sources = [_norm_source("upload", up) for up in ups] if ups else []
        else:
            path_txt = st.text_area(
                "Absolute file paths (one per line)",
                placeholder=r"C:\data\sales.parquet" "\n" r"D:\exports\2024.csv",
                key=P + "paths")
            st.caption("Paths are read **directly** by DuckDB — a large "
                       "Parquet/CSV never touches Python memory.")
            sources = [_norm_source("path", p)
                       for p in path_txt.splitlines() if p.strip()]

    if sources:
        tnames = []
        for src in sources:
            label = src["label"]
            try:
                if label.lower().endswith((".xlsx", ".xls")):
                    if src["kind"] == "upload":
                        sheets = _sheet_names(src["up"])
                    else:
                        sheets = _sheet_names_path(src["path"])
                    sheet = st.selectbox(
                        f"Sheet for {label}", sheets,
                        key=P + f"sheet_{src['key'][0]}_{label}")
                    tnames.append(_ingest_src(src, sheet=sheet,
                                              safe_mode=safe_mode))
                else:
                    tnames.append(_ingest_src(src, safe_mode=safe_mode))
            except ValueError as e:
                st.error(f"⚠️ {label}: {e}")

        if tnames:
            st.success(f"Registered {len(tnames)} table(s): "
                       + ", ".join(f"`{t}`" for t in tnames))

            with st.container(border=True):
                st.subheader("📋 Instant profiler")
                st.caption("Runs inside DuckDB — large files are never "
                           "loaded into Python memory.")
                for tname in tnames:
                    with st.expander(f"`{tname}`"):
                        # Profile once per table: the aggregation below scans
                        # the full dataset (COUNT DISTINCT per column), so it
                        # must NOT re-run on every Streamlit rerun — expander
                        # bodies are not lazy.
                        prof_cache = st.session_state.setdefault(
                            P + "prof_cache", {})
                        if tname not in prof_cache:
                            try:
                                with st.spinner(f"Profiling `{tname}`…"):
                                    prof_cache[tname] = core.profile_duckdb(
                                        _con(), tname)
                            except duckdb.Error:
                                # Strict type inference hit dirty data
                                # (e.g. a string deep inside a BIGINT
                                # column). Never crash: keep the raw
                                # traceback visible — it names the exact
                                # file line to cleanse — and point to the
                                # Safe Mode bypass.
                                st.error(
                                    f"⚠️ `{tname}`: DuckDB hit a data type "
                                    "conversion error while scanning this "
                                    "CSV in strict mode. Cleanse the source "
                                    "file at the line shown below, or "
                                    "enable **Safe Mode (Read all as "
                                    "String)** above to force-load the "
                                    "file as text.")
                                with st.expander(
                                        "View Error Details & Line Number"):
                                    st.code(traceback.format_exc(),
                                            language="text")
                                continue
                            except Exception as e:
                                st.error(f"⚠️ Could not profile `{tname}`: {e}")
                                continue
                        prof = prof_cache[tname]
                        st.markdown(f"{prof['rows']:,} rows × {prof['cols']} cols")
                        st.dataframe(core.profile_frame(prof),
                                     use_container_width=True, hide_index=True)

            with st.container(border=True):
                st.subheader("SQL editor")
                default_sql = f"SELECT * FROM {tnames[0]} LIMIT 100"
                st.session_state.setdefault(P + "sql", default_sql)
                with st.form(key=P + "sqlform"):
                    st.text_area("DuckDB SQL", height=140, key=P + "sql")
                    st.caption("⚠️ This box executes **arbitrary DuckDB SQL** "
                               "with full local file access (`COPY TO`, "
                               "`read_csv`, …) — it runs as you, on your "
                               "machine. Only run SQL you trust.")
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
                        preview = res.get("preview")
                        n_prev = preview.num_rows if preview is not None else 0
                        total = res.get("total")
                        if total is not None and total > PREVIEW_LIMIT:
                            st.info(
                                "Showing top 1,000 rows for UI performance. "
                                f"Total rows retrieved: {total:,}. Use the "
                                "export button for the full dataset.")
                        total_note = (f"{total:,} total rows"
                                      if total is not None
                                      else "total row count n/a")
                        st.caption(f"Showing top {n_prev:,} of "
                                   f"{total_note} · {res['ms']:.0f} ms "
                                   f"(Arrow, zero-copy)")
                        if res.get("note"):
                            st.caption(res["note"])
                        if n_prev:
                            st.dataframe(preview, use_container_width=True)
                        else:
                            st.info("Query ran successfully — no rows to preview.")
                        st.markdown("**Download preview** (top "
                                    f"{PREVIEW_LIMIT:,} rows)")
                        _export_buttons(preview, "query_preview",
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
                "1. **Provide data** — *Upload File* for quick files, or "
                "*Read from Local Path* and paste absolute paths (one per "
                "line) for large datasets.\n"
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
        dsrc_mode = st.radio("Input method", ("Upload File", "Read from Local Path"),
                             horizontal=True, key=P + "dsrcmode")
        c1, c2 = st.columns(2)
        old_src = new_src = None
        if dsrc_mode == "Upload File":
            with c1:
                old_up = st.file_uploader("Old version",
                                          type=["parquet", "csv", "xlsx", "xls"],
                                          key=P + "old")
                if old_up:
                    old_src = _norm_source("upload", old_up)
            with c2:
                new_up = st.file_uploader("New version",
                                          type=["parquet", "csv", "xlsx", "xls"],
                                          key=P + "new")
                if new_up:
                    new_src = _norm_source("upload", new_up)
        else:
            with c1:
                old_path = st.text_input("Old version — absolute path",
                                         placeholder=r"C:\data\old.parquet",
                                         key=P + "old_path")
                if old_path.strip():
                    old_src = _norm_source("path", old_path)
            with c2:
                new_path = st.text_input("New version — absolute path",
                                         placeholder=r"C:\data\new.parquet",
                                         key=P + "new_path")
                if new_path.strip():
                    new_src = _norm_source("path", new_path)

    if old_src and new_src:
        try:
            old = _diff_df_src(old_src, "old")
            new = _diff_df_src(new_src, "new")
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
