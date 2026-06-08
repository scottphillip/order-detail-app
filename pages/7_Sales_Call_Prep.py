"""
Sales Call Prep - Quick snapshot before a meeting.
Pick a customer or manufacturer → instant summary: YTD sales, trend,
top items, last order, how they compare to last year, commission earned.
Designed to be checked in 2 minutes before walking into a meeting.
"""
import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import datetime

from utils.auth import get_access_filter, get_access_display
from utils.connection import get_nxt_connection
from utils.export import excel_download_button

st.set_page_config(
    page_title="Sales Call Prep | Affinity Insights",
    page_icon="📞",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Auth Guard
if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()

conn = get_nxt_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

ORDER_VIEW = "DB_NXT.SCH_NXT.VW_MYORDERDETAIL_ALL"
PARSE_DATE = "COALESCE(TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY'), TRY_TO_DATE(ORDERDATE, 'YYYY-MM-DD'))"

# Header
st.markdown("""
<div style="background: #2D2D2D; padding: 12px 20px; border-radius: 8px; margin-bottom: 15px;">
    <span style="color: #FF9800; font-size: 18px; font-weight: bold;">SALES CALL PREP</span>
    <span style="color: #AAAAAA; font-size: 13px; margin-left: 12px;">2-minute snapshot before your meeting</span>
</div>
""", unsafe_allow_html=True)


# ─── Cached Queries ───

@st.cache_data(ttl=600, show_spinner=False)
def get_customers(_conn, territory_filter: str) -> list:
    query = f"""
        SELECT DISTINCT DISTRIBUTORNAME
        FROM {ORDER_VIEW}
        WHERE {territory_filter} AND DISTRIBUTORNAME IS NOT NULL
          AND YEAR({PARSE_DATE}) >= YEAR(CURRENT_DATE()) - 1
        ORDER BY DISTRIBUTORNAME
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    return df["DISTRIBUTORNAME"].tolist() if not df.empty else []


@st.cache_data(ttl=600, show_spinner=False)
def get_manufacturers(_conn, territory_filter: str) -> list:
    query = f"""
        SELECT DISTINCT MANUFACTURERNAME
        FROM {ORDER_VIEW}
        WHERE {territory_filter} AND MANUFACTURERNAME IS NOT NULL
          AND YEAR({PARSE_DATE}) >= YEAR(CURRENT_DATE()) - 1
        ORDER BY MANUFACTURERNAME
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    return df["MANUFACTURERNAME"].tolist() if not df.empty else []


@st.cache_data(ttl=300, show_spinner=False)
def get_prep_data(_conn, entity_type: str, entity_name: str, territory_filter: str) -> dict:
    """Get all prep data in one batch for speed."""
    safe_name = entity_name.replace("'", "''")
    filter_col = "DISTRIBUTORNAME" if entity_type == "Customer" else "MANUFACTURERNAME"

    current_year = datetime.now().year
    current_month = datetime.now().month

    # YTD this year
    ytd_query = f"""
        SELECT
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 2) AS DOLLARS,
            ROUND(SUM(TRY_TO_DOUBLE(QTY)), 0) AS CASES,
            ROUND(SUM(TRY_TO_DOUBLE(COMM)), 2) AS COMMISSION,
            COUNT(DISTINCT ORDERNUMBER) AS ORDERS,
            MAX({PARSE_DATE}) AS LAST_ORDER_DATE
        FROM {ORDER_VIEW}
        WHERE {filter_col} = '{safe_name}'
          AND {territory_filter}
          AND YEAR({PARSE_DATE}) = {current_year}
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
    """

    # Same period last year
    py_query = f"""
        SELECT
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 2) AS DOLLARS,
            ROUND(SUM(TRY_TO_DOUBLE(QTY)), 0) AS CASES,
            ROUND(SUM(TRY_TO_DOUBLE(COMM)), 2) AS COMMISSION
        FROM {ORDER_VIEW}
        WHERE {filter_col} = '{safe_name}'
          AND {territory_filter}
          AND YEAR({PARSE_DATE}) = {current_year - 1}
          AND MONTH({PARSE_DATE}) <= {current_month}
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
    """

    # Top 5 items (by dollars YTD)
    items_query = f"""
        SELECT
            DESCRIPTION AS ITEM,
            CATEGORY,
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS DOLLARS,
            ROUND(SUM(TRY_TO_DOUBLE(QTY)), 0) AS CASES
        FROM {ORDER_VIEW}
        WHERE {filter_col} = '{safe_name}'
          AND {territory_filter}
          AND YEAR({PARSE_DATE}) = {current_year}
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
          AND DESCRIPTION IS NOT NULL
        GROUP BY DESCRIPTION, CATEGORY
        ORDER BY DOLLARS DESC
        LIMIT 8
    """

    # Monthly trend (last 6 months)
    trend_query = f"""
        SELECT
            MONTH({PARSE_DATE}) AS MO,
            YEAR({PARSE_DATE}) AS YR,
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS DOLLARS
        FROM {ORDER_VIEW}
        WHERE {filter_col} = '{safe_name}'
          AND {territory_filter}
          AND {PARSE_DATE} >= DATEADD('MONTH', -6, CURRENT_DATE())
          AND {PARSE_DATE} IS NOT NULL
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
        GROUP BY MO, YR
        ORDER BY YR, MO
    """

    # For customer: which manufacturers are they buying
    # For manufacturer: which customers are buying from them
    breakdown_col = "MANUFACTURERNAME" if entity_type == "Customer" else "DISTRIBUTORNAME"
    breakdown_query = f"""
        SELECT
            {breakdown_col} AS ENTITY,
            ROUND(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS DOLLARS,
            ROUND(SUM(TRY_TO_DOUBLE(QTY)), 0) AS CASES
        FROM {ORDER_VIEW}
        WHERE {filter_col} = '{safe_name}'
          AND {territory_filter}
          AND YEAR({PARSE_DATE}) = {current_year}
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
          AND {breakdown_col} IS NOT NULL
        GROUP BY {breakdown_col}
        ORDER BY DOLLARS DESC
        LIMIT 10
    """

    ytd_df = _conn.cursor().execute(ytd_query).fetch_pandas_all()
    py_df = _conn.cursor().execute(py_query).fetch_pandas_all()
    items_df = _conn.cursor().execute(items_query).fetch_pandas_all()
    trend_df = _conn.cursor().execute(trend_query).fetch_pandas_all()
    breakdown_df = _conn.cursor().execute(breakdown_query).fetch_pandas_all()

    ytd = ytd_df.iloc[0] if not ytd_df.empty else {}
    py = py_df.iloc[0] if not py_df.empty else {}

    return {
        "ytd_dollars": float(ytd.get("DOLLARS") or 0),
        "ytd_cases": int(ytd.get("CASES") or 0),
        "ytd_commission": float(ytd.get("COMMISSION") or 0),
        "ytd_orders": int(ytd.get("ORDERS") or 0),
        "last_order": ytd.get("LAST_ORDER_DATE"),
        "py_dollars": float(py.get("DOLLARS") or 0),
        "py_cases": int(py.get("CASES") or 0),
        "py_commission": float(py.get("COMMISSION") or 0),
        "top_items": items_df,
        "trend": trend_df,
        "breakdown": breakdown_df,
    }


# ═══════════════════════════════════════════════════════════════
# MAIN UI
# ═══════════════════════════════════════════════════════════════

col_type, col_search = st.columns([1, 3])

with col_type:
    entity_type = st.radio("Lookup by", ["Customer", "Manufacturer"], horizontal=True)

with col_search:
    if entity_type == "Customer":
        options = get_customers(conn, territory_filter)
        selected = st.selectbox("Select customer", options, key="prep_customer",
                                placeholder="Start typing a customer name...")
    else:
        options = get_manufacturers(conn, territory_filter)
        selected = st.selectbox("Select manufacturer", options, key="prep_mfr",
                                placeholder="Start typing a manufacturer name...")

if selected:
    data = get_prep_data(conn, entity_type, selected, territory_filter)

    st.markdown("---")

    # ─── KPI Row ───
    yoy_dollar_change = None
    if data["py_dollars"] > 0:
        yoy_dollar_change = ((data["ytd_dollars"] - data["py_dollars"]) / data["py_dollars"]) * 100

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric(
        "YTD Sales",
        f"${data['ytd_dollars']:,.0f}",
        delta=f"{yoy_dollar_change:+.1f}% vs LY" if yoy_dollar_change else None,
    )
    k2.metric("YTD Cases", f"{data['ytd_cases']:,}")
    k3.metric("Commission", f"${data['ytd_commission']:,.0f}")
    k4.metric("Orders", f"{data['ytd_orders']:,}")

    # Last order freshness
    if data["last_order"]:
        last_date = data["last_order"]
        if hasattr(last_date, "strftime"):
            days_ago = (datetime.now().date() - last_date).days if hasattr(last_date, "days_in_month") else None
            try:
                days_ago = (datetime.now().date() - last_date).days
            except Exception:
                days_ago = None
            k5.metric("Last Order", last_date.strftime("%b %d"), delta=f"{days_ago}d ago" if days_ago else None,
                      delta_color="inverse")
        else:
            k5.metric("Last Order", str(last_date)[:10])
    else:
        k5.metric("Last Order", "—")

    # ─── Two-column layout: Trend + Top Items ───
    col_trend, col_items = st.columns([3, 2])

    with col_trend:
        st.markdown("#### 6-Month Trend")
        if not data["trend"].empty:
            trend_df = data["trend"].copy()
            month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            trend_df["LABEL"] = trend_df.apply(
                lambda r: f"{month_names[int(r['MO'])-1]}", axis=1
            )
            fig = px.bar(trend_df, x="LABEL", y="DOLLARS",
                         color_discrete_sequence=["#F5921E"])
            fig.update_layout(height=250, xaxis_title="", yaxis_title="",
                              yaxis_tickformat="$,.0f", margin=dict(t=5, b=5))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No recent trend data.")

    with col_items:
        st.markdown("#### Top Items")
        if not data["top_items"].empty:
            items = data["top_items"][["ITEM", "DOLLARS", "CASES"]].copy()
            items["DOLLARS"] = items["DOLLARS"].apply(lambda x: f"${x:,.0f}")
            items["CASES"] = items["CASES"].apply(lambda x: f"{x:,.0f}")
            items.columns = ["Item", "$", "Cases"]
            st.dataframe(items, use_container_width=True, hide_index=True, height=250)
        else:
            st.info("No items found.")

    # ─── Breakdown ───
    st.markdown("---")
    breakdown_label = "Manufacturers They Buy" if entity_type == "Customer" else "Top Customers"
    st.markdown(f"#### {breakdown_label}")

    if not data["breakdown"].empty:
        breakdown = data["breakdown"].copy()
        fig = px.bar(breakdown.head(10), x="ENTITY", y="DOLLARS",
                     color_discrete_sequence=["#1B4F72"])
        fig.update_layout(height=280, xaxis_title="", yaxis_title="",
                          yaxis_tickformat="$,.0f", xaxis_tickangle=-45,
                          margin=dict(t=5, b=80))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No breakdown data available.")

    # ─── Quick talking points (AI-generated summary) ───
    st.markdown("---")
    st.markdown("#### Quick Talking Points")
    points = []
    if yoy_dollar_change:
        direction = "up" if yoy_dollar_change > 0 else "down"
        points.append(f"Sales are **{direction} {abs(yoy_dollar_change):.0f}%** vs same period last year")
    if data["ytd_commission"] > 0 and data["ytd_dollars"] > 0:
        rate = (data["ytd_commission"] / data["ytd_dollars"]) * 100
        points.append(f"Effective commission rate: **{rate:.2f}%** (${data['ytd_commission']:,.0f})")
    if data["last_order"]:
        try:
            days = (datetime.now().date() - data["last_order"]).days
            if days > 30:
                points.append(f"Last order was **{days} days ago** — may need a check-in")
            elif days <= 7:
                points.append(f"Active buyer — ordered within the last week")
        except Exception:
            pass
    if not data["top_items"].empty:
        top_item = data["top_items"].iloc[0]["ITEM"]
        points.append(f"Top item: **{top_item}**")

    for p in points:
        st.markdown(f"- {p}")

    if not points:
        st.info("Not enough data to generate talking points.")

else:
    st.markdown("")
    st.markdown("")
    st.markdown(
        '<p style="text-align:center; color:#888; font-size:18px; margin-top:60px;">'
        'Select a customer or manufacturer above to see your meeting prep.</p>',
        unsafe_allow_html=True
    )

st.markdown("---")
st.caption("Sales Call Prep | Affinity Group | Powered by Snowflake + Cortex AI")
