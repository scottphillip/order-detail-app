"""
Reconciliation - Compare internal NXT order data against manufacturer scorecard reports.
Identifies gaps, discrepancies, and missing data between what you report and what they report.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from utils.auth import get_access_filter, get_access_display
from utils.connection import get_nxt_connection, get_csm_connection
from utils.export import excel_download_button

st.set_page_config(
    page_title="Reconciliation | Affinity Insights",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Auth Guard
if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()

conn_nxt = get_nxt_connection()
conn_csm = get_csm_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# Header
st.markdown("""
<div style="background: #2D2D2D; padding: 12px 20px; border-radius: 8px; margin-bottom: 15px;">
    <span style="color: #2196F3; font-size: 18px; font-weight: bold;">RECONCILIATION</span>
    <span style="color: #AAAAAA; font-size: 13px; margin-left: 12px;">Internal Orders vs Manufacturer Scorecard</span>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    if st.button("← Back to Home", use_container_width=True):
        st.switch_page("app.py")

# ─── Find Overlapping Manufacturers ───

ORDER_VIEW = "DB_NXT.SCH_NXT.VW_MYORDERDETAIL_ALL"
SCORECARD_TABLE = "DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT"
PARSE_DATE = "COALESCE(TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY'), TRY_TO_DATE(ORDERDATE, 'YYYY-MM-DD'))"


@st.cache_data(ttl=600, show_spinner=False)
def get_overlapping_manufacturers(_conn_nxt, _conn_csm, territory_filter: str) -> list:
    """Get manufacturers that exist in BOTH NXT and Scorecard data."""
    nxt_query = f"""
        SELECT DISTINCT UPPER(TRIM(MANUFACTURERNAME)) AS MFR
        FROM {ORDER_VIEW}
        WHERE {territory_filter} AND MANUFACTURERNAME IS NOT NULL
    """
    sc_query = f"""
        SELECT DISTINCT UPPER(TRIM(CLIENT_NAME)) AS MFR
        FROM {SCORECARD_TABLE}
        WHERE CLIENT_NAME IS NOT NULL
    """
    nxt_df = _conn_nxt.cursor().execute(nxt_query).fetch_pandas_all()
    sc_df = _conn_csm.cursor().execute(sc_query).fetch_pandas_all()

    if nxt_df.empty or sc_df.empty:
        return []

    overlap = set(nxt_df["MFR"].tolist()) & set(sc_df["MFR"].tolist())
    # Get proper casing from NXT
    proper_names = _conn_nxt.cursor().execute(f"""
        SELECT DISTINCT MANUFACTURERNAME
        FROM {ORDER_VIEW}
        WHERE UPPER(TRIM(MANUFACTURERNAME)) IN ({','.join([f"'{m}'" for m in list(overlap)[:60]])})
        ORDER BY MANUFACTURERNAME
    """).fetch_pandas_all()
    return proper_names["MANUFACTURERNAME"].tolist() if not proper_names.empty else sorted(overlap)


@st.cache_data(ttl=600, show_spinner=False)
def get_reconciliation_data(_conn_nxt, _conn_csm, manufacturer: str,
                            territory_filter: str, year: int) -> pd.DataFrame:
    """Compare monthly NXT vs Scorecard data for a manufacturer."""
    safe_mfr = manufacturer.replace("'", "''")

    nxt_query = f"""
        SELECT
            MONTH({PARSE_DATE}) AS DATA_MONTH,
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS NXT_DOLLARS,
            ROUND(SUM(TRY_TO_DOUBLE(QTY)), 0) AS NXT_CASES
        FROM {ORDER_VIEW}
        WHERE MANUFACTURERNAME = '{safe_mfr}'
          AND {territory_filter}
          AND YEAR({PARSE_DATE}) = {year}
          AND {PARSE_DATE} IS NOT NULL
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
        GROUP BY DATA_MONTH
    """

    sc_query = f"""
        SELECT
            DATA_MONTH,
            ROUND(SUM(DOLLARS), 0) AS SC_DOLLARS,
            SUM(CASES) AS SC_CASES
        FROM {SCORECARD_TABLE}
        WHERE CLIENT_NAME = '{safe_mfr}'
          AND DATA_YEAR = {year}
        GROUP BY DATA_MONTH
    """

    nxt_df = _conn_nxt.cursor().execute(nxt_query).fetch_pandas_all()
    sc_df = _conn_csm.cursor().execute(sc_query).fetch_pandas_all()

    # Full outer join on month
    months = pd.DataFrame({"DATA_MONTH": range(1, 13)})

    result = months.merge(nxt_df, on="DATA_MONTH", how="left")
    result = result.merge(sc_df, on="DATA_MONTH", how="left")

    # Calculate deltas
    result["DOLLAR_DELTA"] = result["NXT_DOLLARS"].fillna(0) - result["SC_DOLLARS"].fillna(0)
    result["CASE_DELTA"] = result["NXT_CASES"].fillna(0) - result["SC_CASES"].fillna(0)

    # Percent difference (NXT as baseline)
    result["CASE_PCT_DIFF"] = result.apply(
        lambda r: round(((r["NXT_CASES"] - r["SC_CASES"]) / r["SC_CASES"]) * 100, 1)
        if pd.notnull(r["SC_CASES"]) and r["SC_CASES"] > 0 and pd.notnull(r["NXT_CASES"])
        else None, axis=1
    )

    # Month names
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    result["MONTH_NAME"] = result["DATA_MONTH"].apply(lambda m: month_names[int(m) - 1])

    # Only return months that have data in at least one source
    result = result[
        result["NXT_DOLLARS"].notna() | result["SC_DOLLARS"].notna() |
        result["NXT_CASES"].notna() | result["SC_CASES"].notna()
    ]

    return result


@st.cache_data(ttl=600, show_spinner=False)
def get_category_reconciliation(_conn_nxt, _conn_csm, manufacturer: str,
                                territory_filter: str, year: int) -> pd.DataFrame:
    """Compare by category — where do the numbers diverge?"""
    safe_mfr = manufacturer.replace("'", "''")

    nxt_query = f"""
        SELECT
            CATEGORY,
            ROUND(SUM(TRY_TO_DOUBLE(QTY)), 0) AS NXT_CASES,
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS NXT_DOLLARS
        FROM {ORDER_VIEW}
        WHERE MANUFACTURERNAME = '{safe_mfr}'
          AND {territory_filter}
          AND YEAR({PARSE_DATE}) = {year}
          AND {PARSE_DATE} IS NOT NULL
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
        GROUP BY CATEGORY
        HAVING SUM(TRY_TO_DOUBLE(DOLLARS)) > 0
    """

    sc_query = f"""
        SELECT
            ITEM_CATEGORY AS CATEGORY,
            SUM(CASES) AS SC_CASES,
            ROUND(SUM(DOLLARS), 0) AS SC_DOLLARS
        FROM {SCORECARD_TABLE}
        WHERE CLIENT_NAME = '{safe_mfr}'
          AND DATA_YEAR = {year}
        GROUP BY ITEM_CATEGORY
        HAVING SUM(CASES) > 0
    """

    nxt_df = _conn_nxt.cursor().execute(nxt_query).fetch_pandas_all()
    sc_df = _conn_csm.cursor().execute(sc_query).fetch_pandas_all()

    if nxt_df.empty and sc_df.empty:
        return pd.DataFrame()

    # Full outer join on category (case-insensitive)
    if not nxt_df.empty:
        nxt_df["JOIN_KEY"] = nxt_df["CATEGORY"].str.upper().str.strip()
    if not sc_df.empty:
        sc_df["JOIN_KEY"] = sc_df["CATEGORY"].str.upper().str.strip()

    if not nxt_df.empty and not sc_df.empty:
        result = nxt_df.merge(sc_df, on="JOIN_KEY", how="outer", suffixes=("_NXT", "_SC"))
        result["CATEGORY"] = result["CATEGORY_NXT"].fillna(result["CATEGORY_SC"])
    elif not nxt_df.empty:
        result = nxt_df.copy()
        result["SC_CASES"] = None
        result["SC_DOLLARS"] = None
    else:
        result = sc_df.copy()
        result["NXT_CASES"] = None
        result["NXT_DOLLARS"] = None

    result["CASE_DELTA"] = result["NXT_CASES"].fillna(0) - result["SC_CASES"].fillna(0)

    return result.sort_values("NXT_CASES", ascending=False, na_position="last")


# ═══════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════

overlapping = get_overlapping_manufacturers(conn_nxt, conn_csm, territory_filter)

if not overlapping:
    st.warning("No manufacturers found in both your internal orders and scorecard data.")
    st.stop()

# Controls
col_mfr, col_year = st.columns([3, 1])
with col_mfr:
    selected_mfr = st.selectbox("Manufacturer", overlapping, key="recon_mfr")
with col_year:
    selected_year = st.selectbox("Year", [2026, 2025, 2024], key="recon_year")

st.markdown("---")

# ─── Monthly Reconciliation ───
st.markdown("### Monthly Comparison")
st.caption("Internal orders (NXT) vs manufacturer scorecard — cases and dollars by month")

recon_df = get_reconciliation_data(conn_nxt, conn_csm, selected_mfr, territory_filter, selected_year)

if not recon_df.empty:
    # Summary KPIs
    total_nxt_cases = recon_df["NXT_CASES"].sum()
    total_sc_cases = recon_df["SC_CASES"].sum()
    case_gap = total_nxt_cases - total_sc_cases if pd.notnull(total_sc_cases) else None

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Your Cases (NXT)", f"{total_nxt_cases:,.0f}" if pd.notnull(total_nxt_cases) else "—")
    k2.metric("Their Cases (Scorecard)", f"{total_sc_cases:,.0f}" if pd.notnull(total_sc_cases) else "—")
    if case_gap is not None and total_sc_cases and total_sc_cases > 0:
        gap_pct = (case_gap / total_sc_cases) * 100
        k3.metric("Case Gap", f"{case_gap:+,.0f}", delta=f"{gap_pct:+.1f}%")
    else:
        k3.metric("Case Gap", "—")

    total_nxt_dollars = recon_df["NXT_DOLLARS"].sum()
    k4.metric("Your Dollars (NXT)", f"${total_nxt_dollars:,.0f}" if pd.notnull(total_nxt_dollars) else "—")

    # Chart: side-by-side cases
    chart_df = recon_df[["MONTH_NAME", "NXT_CASES", "SC_CASES"]].copy()
    chart_df = chart_df.rename(columns={"NXT_CASES": "Your Cases (NXT)", "SC_CASES": "Their Cases (Scorecard)"})
    chart_melted = chart_df.melt(id_vars="MONTH_NAME", var_name="Source", value_name="Cases")

    fig = px.bar(chart_melted, x="MONTH_NAME", y="Cases", color="Source", barmode="group",
                 color_discrete_map={"Your Cases (NXT)": "#F5921E", "Their Cases (Scorecard)": "#4CAF50"})
    fig.update_layout(height=350, xaxis_title="", yaxis_title="Cases", yaxis_tickformat=",.0f")
    st.plotly_chart(fig, use_container_width=True)

    # Detail table
    with st.expander("Monthly detail table"):
        display = recon_df[["MONTH_NAME", "NXT_CASES", "SC_CASES", "CASE_DELTA",
                            "NXT_DOLLARS", "SC_DOLLARS", "DOLLAR_DELTA"]].copy()
        display.columns = ["Month", "Your Cases", "Their Cases", "Case Delta",
                           "Your Dollars", "Their Dollars", "Dollar Delta"]
        st.dataframe(display, use_container_width=True, hide_index=True)
        excel_download_button(display, f"reconciliation_{selected_mfr}_{selected_year}", "Export Reconciliation")

    # Flag significant discrepancies
    st.markdown("---")
    st.markdown("### Discrepancy Flags")
    flagged = recon_df[
        (recon_df["CASE_PCT_DIFF"].notna()) & (recon_df["CASE_PCT_DIFF"].abs() > 10)
    ]
    if not flagged.empty:
        for _, row in flagged.iterrows():
            pct = row["CASE_PCT_DIFF"]
            icon = "higher" if pct > 0 else "lower"
            color = "#E65100" if abs(pct) > 25 else "#FF9800"
            st.markdown(
                f'<div style="border-left:4px solid {color}; padding:8px 12px; margin:4px 0; '
                f'border-radius:4px; background:#FFF8E1;">'
                f'<strong>{row["MONTH_NAME"]}</strong>: Your cases are <strong>{abs(pct):.0f}%</strong> '
                f'{icon} than scorecard '
                f'({int(row["NXT_CASES"]):,} vs {int(row["SC_CASES"]):,})'
                f'</div>',
                unsafe_allow_html=True
            )
    else:
        st.success("No significant discrepancies (>10% gap) found for this manufacturer.")

else:
    st.info(f"No data available for {selected_mfr} in {selected_year}.")

# ─── Category Breakdown ───
st.markdown("---")
st.markdown("### Category-Level Comparison")
st.caption("Where do the numbers diverge? Compare by product category.")

cat_df = get_category_reconciliation(conn_nxt, conn_csm, selected_mfr, territory_filter, selected_year)

if not cat_df.empty:
    display_cat = cat_df[["CATEGORY", "NXT_CASES", "SC_CASES", "CASE_DELTA"]].head(20).copy()
    display_cat.columns = ["Category", "Your Cases", "Their Cases", "Delta"]
    st.dataframe(display_cat, use_container_width=True, hide_index=True)
else:
    st.info("No category-level data available for comparison.")

st.markdown("---")
st.caption("Reconciliation | Affinity Group | Powered by Snowflake + Cortex AI")
