"""App 12 — Data Quality Watchdog.

Pre-refresh gatekeeper for raw CSV/Excel/Parquet files: duplicate PKs,
missing columns, null spikes, whitespace issues, numeric outliers
(IQR / Z-score), optional baseline comparison, and a Pass/Warning/Fail
report card with exception-rows CSV export.

Pure logic lives in dq_core.py. Runs standalone
(`streamlit run app.py`) or inside the suite launcher.
"""

import io
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dq_core as core  # noqa: E402

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    raise SystemExit("streamlit is required: pip install -r requirements.txt")

P = "dq12_"
BADGE = {"pass": "✅ PASS", "warning": "⚠️ WARNING", "fail": "🚫 FAIL"}

st.title("🐶 Data Quality Watchdog")
st.caption("Validate raw files before they feed Power BI or your ETL — "
           "catch bad data at the gate, 100% local.")

# ------------------------------------------------------------ inputs
st.header("① Load files")
c1, c2 = st.columns(2)
with c1:
    cur_up = st.file_uploader("Current file *", type=["csv", "xlsx", "xls",
                                                      "parquet"],
                              key=P + "cur")
with c2:
    base_up = st.file_uploader("Baseline file (optional)", type=["csv", "xlsx",
                                                                  "xls",
                                                                  "parquet"],
                               key=P + "base")

if not cur_up:
    st.info("👆 Upload the file to validate.")
    st.stop()

try:
    df = core.load_file(cur_up.name, cur_up.getvalue())
except ValueError as e:
    st.error(f"⚠️ {e}")
    st.stop()
st.success(f"Loaded **{cur_up.name}** — {len(df):,} rows × "
           f"{len(df.columns)} cols.")

base_df = None
if base_up:
    try:
        base_df = core.load_file(base_up.name, base_up.getvalue())
        st.caption(f"Baseline **{base_up.name}** — {len(base_df):,} rows.")
    except ValueError as e:
        st.error(f"⚠️ Baseline: {e}")
        st.stop()

# ------------------------------------------------------------ options
st.header("② Check configuration")
o1, o2 = st.columns(2)
with o1:
    pk_cols = st.multiselect("Primary key column(s)", list(df.columns),
                             key=P + "pk")
    required_raw = st.text_area("Required columns (one per line)",
                                key=P + "req")
    null_thr = st.slider("Null-spike threshold %", 1, 50, 10, key=P + "null")
with o2:
    metric_cols = st.multiselect("Key metric columns (for sums)",
                                 [c for c in df.columns
                                  if pd.api.types.is_numeric_dtype(df[c])],
                                 key=P + "metrics")
    cat_cols = st.multiselect("Category columns (distinct counts)",
                              list(df.columns), key=P + "cats")
    outlier_method = st.radio("Outlier method", ("IQR", "Z-score"),
                              horizontal=True, key=P + "om")
    z_thr = st.slider("Z-score threshold", 2.0, 5.0, 3.0, key=P + "z")
    base_thr = st.slider("Baseline delta alert %", 1, 50, 10, key=P + "bthr")

opts = {"pk_cols": pk_cols,
        "required_cols": [c.strip() for c in required_raw.splitlines()
                          if c.strip()],
        "null_threshold": null_thr, "outlier_method": outlier_method,
        "z_threshold": z_thr}

# ------------------------------------------------------------ run
st.header("③ Report card")
if st.button("🐶 Run health checks", type="primary", key=P + "go"):
    checks = core.run_checks(df, opts)
    flags = []
    if base_df is not None:
        cur_s = core.summarize(df, metric_cols, cat_cols)
        base_s = core.summarize(base_df, metric_cols, cat_cols)
        flags = core.baseline_compare(cur_s, base_s, base_thr)
    st.session_state[P + "result"] = (checks, flags)

res = st.session_state.get(P + "result")
if res:
    checks, flags = res
    overall = core.overall_status(checks, flags)
    if overall == "pass":
        st.success("## ✅ PASS — file looks healthy.")
    elif overall == "warning":
        st.warning("## ⚠️ WARNING — review the flagged items below.")
    else:
        st.error("## 🚫 FAIL — fix the failed checks before refresh.")

    st.subheader("Health checks")
    for name, c in checks.items():
        with st.expander(f"{BADGE[c['status']]} — {name}"):
            st.write(c["summary"])
            if c["exceptions"] is not None and not c["exceptions"].empty:
                st.dataframe(c["exceptions"].head(200),
                             use_container_width=True)
                st.caption(f"{len(c['exceptions'])} exception row(s).")

    if base_df is not None:
        st.subheader("Baseline comparison")
        if not flags:
            st.success("No significant drift vs baseline. ✅")
        else:
            for f in flags:
                icon = "🚫" if f["status"] == "fail" else "⚠️"
                d = (f"{f['delta_pct']:+.1f}%" if f["delta_pct"] is not None
                     else f["note"])
                st.write(f"{icon} **{f['metric']}**: {f['baseline']:,} → "
                         f"{f['current']:,} ({d})")

    exc = core.exceptions_frame(checks)
    if not exc.empty:
        st.subheader(f"Exception rows ({len(exc)})")
        st.dataframe(exc.head(500), use_container_width=True)
        st.download_button("⬇️ Download exceptions CSV",
                           exc.to_csv(index=False).encode("utf-8-sig"),
                           "dq_exceptions.csv", "text/csv",
                           key=P + "dl_exc")
    else:
        st.success("No exception rows — nothing to fix. 🎉")
