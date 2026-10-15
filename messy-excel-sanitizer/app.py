"""App 6 — Messy Excel Sanitizer.

1. Batch upload .xlsx/.csv (multi-sheet selector per workbook).
2. Sanitization pipeline: skip title rows, unmerge + forward-fill, strip
   whitespace, standardize headers, unify dates, drop empties/duplicates.
3. Schema validation against expected columns, then concatenate into one
   clean master dataset (xlsx/csv/parquet download).

Pure logic lives in sanitize_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sanitize_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

try:
    st.set_page_config(page_title="Messy Excel Sanitizer",
                       page_icon="🧹", layout="wide")
except Exception:
    pass  # running inside the suite launcher — page config owned by launcher.py

P = "san6_"


def _sources() -> list:
    # [{"name", "raw", "sheets": [...], "picked": [...]}]
    return st.session_state.setdefault(P + "sources", [])


st.title("🧹 Messy Excel Sanitizer")
st.caption("Merge messy human-made workbooks into one clean master dataset — "
           "100% local.")

# ------------------------------------------------------- 1. upload
with st.container(border=True):
    st.header("① Batch upload")
    ups = st.file_uploader("Excel / CSV files", type=["xlsx", "xls", "csv"],
                           accept_multiple_files=True, key=P + "ups")
    if ups:
        known = {s["name"]: s for s in _sources()}
        fresh = []
        for up in ups:
            if up.name in known:
                fresh.append(known[up.name])
                continue
            try:
                raw = up.getvalue()
                sheets: list[str] = []
                if up.name.lower().endswith((".xlsx", ".xls")):
                    import openpyxl
                    wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True,
                                                data_only=True)
                    sheets = wb.sheetnames
                fresh.append({"name": up.name, "raw": raw, "sheets": sheets,
                              "picked": list(sheets)})
            except Exception as e:
                st.error(f"⚠️ Could not read {up.name}: {e}")
        st.session_state[P + "sources"] = fresh

    sources = _sources()
    if not sources:
        st.subheader("Get started")
        st.markdown(
            "1. Upload one or more **.xlsx / .xls / .csv** files above.\n"
            "2. Pick which sheets to include per workbook.\n"
            "3. Tune the sanitization pipeline, then **⚙️ Sanitize & concatenate**."
        )
        st.stop()

    for s in sources:
        if s["sheets"]:
            with st.expander(f"📄 {s['name']} — sheets"):
                s["picked"] = st.multiselect(
                    "Include sheets", s["sheets"], default=s["picked"],
                    key=P + f"sheets_{s['name']}")
        else:
            st.write(f"📄 {s['name']} (csv)")

# ------------------------------------------------------- 2. pipeline
with st.container(border=True):
    st.header("② Sanitization pipeline")
    o1, o2 = st.columns(2)
    with o1:
        skip_rows = st.number_input("Skip top N title rows", 0, 20, 0,
                                    key=P + "skip")
        unmerge = st.checkbox("Unmerge cells + forward-fill down", value=True,
                              key=P + "unmerge",
                              help="Merged store/department labels are unmerged; "
                                   "empty cells inherit the value above.")
        strip_ws = st.checkbox("Strip leading/trailing whitespace", value=True,
                               key=P + "strip")
        header_mode = st.radio("Header standardization",
                               ("strip", "snake_case"), key=P + "headers",
                               help="snake_case: 'Store Name' → 'store_name'.")
    with o2:
        date_unify = st.checkbox("Unify date formats", value=True, key=P + "dates")
        dayfirst = st.checkbox("Day-first dates (DD/MM/YYYY)", value=True,
                               key=P + "dayfirst")
        drop_empty_rows = st.checkbox("Drop fully-empty rows", value=True,
                                      key=P + "der")
        drop_empty_cols = st.checkbox("Drop fully-empty columns", value=True,
                                      key=P + "dec")
        drop_dupes = st.checkbox("Drop duplicate rows", value=False, key=P + "dupes")

    opts = {"ffill": unmerge, "strip_ws": strip_ws, "header_mode": header_mode,
            "date_unify": date_unify, "dayfirst": dayfirst,
            "drop_empty_rows": drop_empty_rows, "drop_empty_cols": drop_empty_cols,
            "drop_dupes": drop_dupes}

with st.container(border=True):
    st.header("③ Schema validation (optional)")
    expected_raw = st.text_area("Expected columns (one per line or comma-separated)",
                                key=P + "expected",
                                placeholder="store_code\nstore_name\nsales_amount")
    expected = [c.strip() for c in expected_raw.replace(",", "\n").splitlines()
                if c.strip()]

# ------------------------------------------------------- 3. run
st.header("④ Run & export")
if st.button("⚙️ Sanitize & concatenate", type="primary", key=P + "go"):
    ok_frames, report, all_notes = [], [], set()
    for s in sources:
        lname = s["name"].lower()
        sheets = s["picked"] if s["sheets"] else [None]
        for sheet in sheets:
            label = f"{s['name']}" + (f" / {sheet}" if sheet else "")
            try:
                df = core.read_source(s["raw"], s["name"], sheet=sheet,
                                      skip_rows=int(skip_rows),
                                      unmerge=unmerge and lname.endswith(
                                          (".xlsx", ".xls")))
                df, notes = core.sanitize_df(df, opts)
                for n in notes:
                    all_notes.add(n)
                missing, extra = core.validate_schema(df, expected) \
                    if expected else ([], [])
                report.append({"source": label, "rows": len(df),
                               "cols": len(df.columns),
                               "missing": ", ".join(missing) or "—",
                               "extra": ", ".join(extra) or "—",
                               "ok": not missing})
                if not missing:
                    ok_frames.append((s["name"], sheet or "", df))
            except ValueError as e:
                report.append({"source": label, "rows": 0, "cols": 0,
                               "missing": f"ERROR: {e}", "extra": "—",
                               "ok": False})
    st.session_state[P + "report"] = report
    st.session_state[P + "ok_frames"] = ok_frames
    st.session_state[P + "notes"] = sorted(all_notes)

report = st.session_state.get(P + "report")
if report:
    with st.container(border=True):
        st.subheader("Validation report")
        rep_df = pd.DataFrame(report)
        st.dataframe(rep_df, use_container_width=True, hide_index=True)
        bad = [r for r in report if not r["ok"]]
        if bad:
            st.error(f"🚨 {len(bad)} source(s) failed validation or errored — "
                     "fix them or they will be excluded below.")
        for n in st.session_state.get(P + "notes", []):
            st.caption("• " + n)

    ok_frames = st.session_state.get(P + "ok_frames", [])
    if ok_frames:
        with st.container(border=True):
            try:
                master = core.concat_sources(ok_frames)
            except Exception as e:
                st.error(f"⚠️ Could not concatenate sources: {e}")
                master = None
            if master is not None:
                st.subheader(f"Master dataset — {len(master):,} rows × "
                             f"{len(master.columns)} cols")
                st.dataframe(master.head(200), use_container_width=True)
                c1, c2, c3 = st.columns(3)
                with c1:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as w:
                        master.to_excel(w, index=False, sheet_name="master")
                    st.download_button("⬇️ Master .xlsx", buf.getvalue(),
                                       "master_dataset.xlsx",
                                       "application/vnd.openxmlformats-officedocument."
                                       "spreadsheetml.sheet", key=P + "dl_xlsx")
                with c2:
                    st.download_button("⬇️ Master .csv",
                                       master.to_csv(index=False).encode("utf-8-sig"),
                                       "master_dataset.csv", "text/csv", key=P + "dl_csv")
                with c3:
                    buf = io.BytesIO()
                    master.to_parquet(buf, index=False)
                    st.download_button("⬇️ Master .parquet", buf.getvalue(),
                                       "master_dataset.parquet",
                                       "application/octet-stream", key=P + "dl_pq")
