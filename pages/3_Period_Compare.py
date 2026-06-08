"""
Period Comparison - Compare sales across different time periods.
Supports Full Year, Quarter, Trimester, and Month comparisons.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from utils.auth import get_access_filter, get_access_display
from utils.connection import get_nxt_connection
from utils.data import (
    get_kpis, get_monthly_breakdown, get_filter_options,
    get_available_years, get_max_month, ORDER_VIEW, PARSE_DATE, _build_where,
)
from utils.export import excel_download_button

st.set_page_config(page_title="Period Compare | Affinity Insights", page_icon="🍴",
                   layout="wide", initial_sidebar_state="expanded")

if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()


def get_snowflake_connection():
    """Get Snowflake connection (delegates to centralized module)."""
    return get_nxt_connection()


# Period type mappings
PERIOD_TYPES = ["Full Year", "Quarter", "Trimester", "Month"]
QUARTER_MONTHS = {"Q1 (Jan-Mar)": (1, 3), "Q2 (Apr-Jun)": (4, 6),
                  "Q3 (Jul-Sep)": (7, 9), "Q4 (Oct-Dec)": (10, 12)}
TRIMESTER_MONTHS = {"T1 (Jan-Apr)": (1, 4), "T2 (May-Aug)": (5, 8), "T3 (Sep-Dec)": (9, 12)}
MONTH_OPTIONS = {"January": (1, 1), "February": (2, 2), "March": (3, 3),
                 "April": (4, 4), "May": (5, 5), "June": (6, 6),
                 "July": (7, 7), "August": (8, 8), "September": (9, 9),
                 "October": (10, 10), "November": (11, 11), "December": (12, 12)}


def get_period_range(period_type, sub_selection):
    """Returns (month_start, month_end) tuple or (None, None) for full year."""
    if period_type == "Full Year":
        return None, None
    elif period_type == "Quarter":
        return QUARTER_MONTHS[sub_selection]
    elif period_type == "Trimester":
        return TRIMESTER_MONTHS[sub_selection]
    elif period_type == "Month":
        return MONTH_OPTIONS[sub_selection]
    return None, None


def get_period_label(year, period_type, sub_selection):
    """Human-readable label for the period."""
    if period_type == "Full Year":
        return str(year)
    return f"{year} {sub_selection.split(' ')[0]}"


conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# Sidebar
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    if st.button("Home", use_container_width=True, key="nav_home"):
        st.switch_page("app.py")
    if st.button("Order Detail", use_container_width=True, key="nav_order"):
        st.switch_page("pages/1_Order_Detail.py")
    if st.button("Manufacturer Compare", use_container_width=True, key="nav_compare"):
        st.switch_page("pages/2_Manufacturer_Compare.py")
    if st.button("Scorecard Analytics", use_container_width=True, key="nav_scorecard"):
        st.switch_page("pages/4_Scorecard_Analytics.py")
    st.markdown("---")

    available_years = get_available_years(conn, territory_filter)

    # Period A
    st.markdown("#### Period A")
    year_a = st.selectbox("Year A", options=available_years, index=0, key="year_a")
    period_type_a = st.selectbox("Period Type A", options=PERIOD_TYPES, index=0, key="period_type_a")

    sub_a = None
    if period_type_a == "Quarter":
        sub_a = st.selectbox("Quarter A", options=list(QUARTER_MONTHS.keys()), key="sub_a_q")
    elif period_type_a == "Trimester":
        sub_a = st.selectbox("Trimester A", options=list(TRIMESTER_MONTHS.keys()), key="sub_a_t")
    elif period_type_a == "Month":
        sub_a = st.selectbox("Month A", options=list(MONTH_OPTIONS.keys()), key="sub_a_m")

    st.markdown("")

    # Period B
    st.markdown("#### Period B")
    default_b = 1 if len(available_years) > 1 else 0
    year_b = st.selectbox("Year B", options=available_years, index=default_b, key="year_b")
    period_type_b = st.selectbox("Period Type B", options=PERIOD_TYPES, index=0, key="period_type_b")

    sub_b = None
    if period_type_b == "Quarter":
        sub_b = st.selectbox("Quarter B", options=list(QUARTER_MONTHS.keys()), key="sub_b_q")
    elif period_type_b == "Trimester":
        sub_b = st.selectbox("Trimester B", options=list(TRIMESTER_MONTHS.keys()), key="sub_b_t")
    elif period_type_b == "Month":
        sub_b = st.selectbox("Month B", options=list(MONTH_OPTIONS.keys()), key="sub_b_m")

    st.markdown("---")
    options = get_filter_options(conn, territory_filter, year_a)
    manufacturer_filter = st.multiselect("Manufacturer (optional)", options=options["manufacturers"],
                                         default=[], placeholder="All manufacturers")

    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# Derive month ranges
month_start_a, month_end_a = get_period_range(period_type_a, sub_a)
month_start_b, month_end_b = get_period_range(period_type_b, sub_b)

# For "Full Year" comparisons, limit KPIs to overlapping months only
# (e.g., if 2026 only has Jan-May, compare only Jan-May of 2025 too)
kpi_month_start_a, kpi_month_end_a = month_start_a, month_end_a
kpi_month_start_b, kpi_month_end_b = month_start_b, month_end_b

if period_type_a == "Full Year" and period_type_b == "Full Year":
    max_month_a = get_max_month(conn, territory_filter, year_a)
    max_month_b = get_max_month(conn, territory_filter, year_b)
    overlap_end = min(max_month_a, max_month_b)
    kpi_month_start_a, kpi_month_end_a = 1, overlap_end
    kpi_month_start_b, kpi_month_end_b = 1, overlap_end

# Labels
label_a = get_period_label(year_a, period_type_a, sub_a)
label_b = get_period_label(year_b, period_type_b, sub_b)

# Main content
st.title("Period Comparison")
if period_type_a == "Full Year" and period_type_b == "Full Year" and kpi_month_end_a < 12:
    import calendar
    month_name = calendar.month_abbr[kpi_month_end_a]
    st.caption(f"Comparing **{label_a}** vs **{label_b}** (Jan-{month_name} only) | {get_access_display(user)}")
else:
    st.caption(f"Comparing **{label_a}** vs **{label_b}** | {get_access_display(user)}")

if year_a == year_b and period_type_a == period_type_b and sub_a == sub_b:
    st.warning("Select two different periods to compare.")
    st.stop()

st.markdown("---")

# KPI comparison
st.markdown("### Key Metrics Comparison")

kpis_a = get_kpis(conn, territory_filter, manufacturer_filter=manufacturer_filter or None,
                  year=year_a, month_start=kpi_month_start_a, month_end=kpi_month_end_a)
kpis_b = get_kpis(conn, territory_filter, manufacturer_filter=manufacturer_filter or None,
                  year=year_b, month_start=kpi_month_start_b, month_end=kpi_month_end_b)


def calc_delta(a, b):
    if b == 0:
        return None
    return ((a - b) / b) * 100


col1, col2, col3, col4 = st.columns(4)

delta_sales = calc_delta(kpis_a["dollars"], kpis_b["dollars"])
delta_cases = calc_delta(kpis_a["qty"], kpis_b["qty"])
delta_comm = calc_delta(kpis_a["comm"], kpis_b["comm"])
delta_orders = calc_delta(kpis_a["orders"], kpis_b["orders"])

col1.metric(f"Sales ({label_a})", f"${kpis_a['dollars']:,.0f}",
            delta=f"{delta_sales:+.1f}% vs {label_b}" if delta_sales is not None else None)
col2.metric(f"Cases ({label_a})", f"{kpis_a['qty']:,.0f}",
            delta=f"{delta_cases:+.1f}% vs {label_b}" if delta_cases is not None else None)
col3.metric(f"Commission ({label_a})", f"${kpis_a['comm']:,.0f}",
            delta=f"{delta_comm:+.1f}% vs {label_b}" if delta_comm is not None else None)
col4.metric(f"Orders ({label_a})", f"{kpis_a['orders']:,}",
            delta=f"{delta_orders:+.1f}% vs {label_b}" if delta_orders is not None else None)

st.markdown("")

# Period B reference row
ref1, ref2, ref3, ref4 = st.columns(4)
ref1.caption(f"{label_b}: ${kpis_b['dollars']:,.0f}")
ref2.caption(f"{label_b}: {kpis_b['qty']:,.0f}")
ref3.caption(f"{label_b}: ${kpis_b['comm']:,.0f}")
ref4.caption(f"{label_b}: {kpis_b['orders']:,}")

st.markdown("---")

# Monthly trend overlay
st.markdown("### Monthly Sales Overlay")

# Get monthly data for both periods
monthly_a = get_monthly_breakdown(conn, territory_filter,
                                  manufacturer_filter=manufacturer_filter or None,
                                  year=year_a, month_start=month_start_a, month_end=month_end_a)
monthly_b = get_monthly_breakdown(conn, territory_filter,
                                  manufacturer_filter=manufacturer_filter or None,
                                  year=year_b, month_start=month_start_b, month_end=month_end_b)

# ─── Partial Month Fix ───
# For the current month of the current year, PY data should be capped to the same
# day-of-month as the latest CY data so comparisons are apples-to-apples.
current_year_now = datetime.now().year
current_month_now = datetime.now().month

if (not monthly_a.empty and not monthly_b.empty
        and year_a == current_year_now):
    # Find the max date in the CY data for the latest month
    max_date_query = f"""
        SELECT MAX({PARSE_DATE}) AS MAX_DT
        FROM {ORDER_VIEW}
        WHERE {_build_where(territory_filter, manufacturer_filter=manufacturer_filter or None, year_filter=year_a)}
    """
    try:
        max_dt_df = conn.cursor().execute(max_date_query).fetch_pandas_all()
        if not max_dt_df.empty and max_dt_df.iloc[0]["MAX_DT"] is not None:
            max_date = pd.to_datetime(max_dt_df.iloc[0]["MAX_DT"])
            max_day = max_date.day
            max_month = max_date.month

            # If the latest CY month is partial (not month-end), re-query that month for PY
            # using only days <= max_day to make it apples-to-apples
            import calendar
            _, last_day_of_month = calendar.monthrange(max_date.year, max_month)

            if max_day < last_day_of_month:
                # Re-query PY for just that partial month with day cap
                partial_where_b = _build_where(
                    territory_filter, manufacturer_filter=manufacturer_filter or None,
                    year_filter=year_b, month_start=max_month, month_end=max_month)
                partial_query = f"""
                    SELECT
                        DATE_TRUNC('MONTH', {PARSE_DATE}) AS "Month",
                        MONTHNAME({PARSE_DATE}) AS "Month Name",
                        SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
                        SUM(TRY_TO_DOUBLE(QTY)) AS "Total Qty",
                        SUM(TRY_TO_DOUBLE(COMM)) AS "Total Comm",
                        COUNT(DISTINCT ORDERNUMBER) AS "Orders"
                    FROM {ORDER_VIEW}
                    WHERE {partial_where_b}
                      AND {PARSE_DATE} IS NOT NULL
                      AND DAY({PARSE_DATE}) <= {max_day}
                    GROUP BY "Month", "Month Name"
                    ORDER BY "Month"
                """
                partial_b_df = conn.cursor().execute(partial_query).fetch_pandas_all()

                # Replace the full-month PY row with the partial one
                if not partial_b_df.empty:
                    month_name = max_date.strftime("%b")
                    monthly_b = monthly_b[monthly_b["Month Name"] != month_name]
                    monthly_b = pd.concat([monthly_b, partial_b_df], ignore_index=True)

                # Add a note about the partial month
                st.caption(f"Note: {max_date.strftime('%B')} is partial — comparing through day {max_day} for both years.")
    except Exception:
        pass  # If anything fails, just use the full month comparison

if not monthly_a.empty or not monthly_b.empty:
    if not monthly_a.empty:
        monthly_a["Period"] = label_a
    if not monthly_b.empty:
        monthly_b["Period"] = label_b

    combined = pd.concat([monthly_a, monthly_b], ignore_index=True)

    fig = px.bar(combined, x="Month Name", y="Total Dollars", color="Period",
                 barmode="group", text_auto="$.2s",
                 color_discrete_map={label_a: "#1B4F72", label_b: "#A9CCE3"})
    fig.update_layout(height=400, xaxis_title="", yaxis_title="Sales ($)")
    st.plotly_chart(fig, use_container_width=True)

    # Monthly detail table
    with st.expander("Monthly detail table"):
        if not monthly_a.empty and not monthly_b.empty:
            merge_df = monthly_a[["Month Name", "Total Dollars", "Total Qty"]].merge(
                monthly_b[["Month Name", "Total Dollars", "Total Qty"]],
                on="Month Name", how="outer", suffixes=(f" ({label_a})", f" ({label_b})"))
            st.dataframe(merge_df, use_container_width=True, hide_index=True)
            excel_download_button(merge_df, "period_compare", "Export Period Comparison")
else:
    st.info("No data available for the selected periods.")

st.markdown("---")

# Top movers
st.markdown("### Top Manufacturers — Period Change")

where_a = _build_where(territory_filter, manufacturer_filter=manufacturer_filter or None,
                       year_filter=year_a, month_start=kpi_month_start_a, month_end=kpi_month_end_a)
where_b = _build_where(territory_filter, manufacturer_filter=manufacturer_filter or None,
                       year_filter=year_b, month_start=kpi_month_start_b, month_end=kpi_month_end_b)

query = f"""
    WITH period_a AS (
        SELECT MANUFACTURERNAME, SUM(TRY_TO_DOUBLE(DOLLARS)) AS dollars_a
        FROM {ORDER_VIEW}
        WHERE {where_a} AND MANUFACTURERNAME IS NOT NULL
        GROUP BY MANUFACTURERNAME
    ),
    period_b AS (
        SELECT MANUFACTURERNAME, SUM(TRY_TO_DOUBLE(DOLLARS)) AS dollars_b
        FROM {ORDER_VIEW}
        WHERE {where_b} AND MANUFACTURERNAME IS NOT NULL
        GROUP BY MANUFACTURERNAME
    )
    SELECT
        COALESCE(a.MANUFACTURERNAME, b.MANUFACTURERNAME) AS "Manufacturer",
        COALESCE(a.dollars_a, 0) AS "Sales {label_a}",
        COALESCE(b.dollars_b, 0) AS "Sales {label_b}",
        COALESCE(a.dollars_a, 0) - COALESCE(b.dollars_b, 0) AS "Change ($)",
        CASE WHEN COALESCE(b.dollars_b, 0) > 0
             THEN ((COALESCE(a.dollars_a, 0) - b.dollars_b) / b.dollars_b) * 100
             ELSE NULL END AS "Change (%)"
    FROM period_a a
    FULL OUTER JOIN period_b b ON a.MANUFACTURERNAME = b.MANUFACTURERNAME
    ORDER BY "Change ($)" DESC
    LIMIT 20
"""

try:
    movers_df = conn.cursor().execute(query).fetch_pandas_all()
    if not movers_df.empty:
        # Top growers
        growers = movers_df.head(10)
        fig = px.bar(growers, x="Manufacturer", y="Change ($)",
                     color_discrete_sequence=["#27AE60"],
                     title=f"Top 10 Growing Manufacturers ({label_a} vs {label_b})")
        fig.update_layout(xaxis_tickangle=-45, height=350)
        st.plotly_chart(fig, use_container_width=True)

        # Full table
        with st.expander("Full comparison table"):
            st.dataframe(movers_df, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"Error: {str(e)[:200]}")
