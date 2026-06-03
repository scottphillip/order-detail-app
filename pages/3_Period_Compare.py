"""
Period Comparison - Compare sales across different time periods.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime

from utils.auth import get_access_filter, get_access_display
from utils.data import (
    get_kpis, get_monthly_breakdown, get_filter_options,
    get_available_years, ORDER_VIEW, PARSE_DATE, _build_where,
)

st.set_page_config(page_title="Period Compare | Affinity Insights", page_icon="📅",
                   layout="wide", initial_sidebar_state="expanded")

if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.page_link("app.py", label="Go to Home", icon="🏠")
    st.stop()


@st.cache_resource
def get_snowflake_connection():
    import snowflake.connector
    return snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        role=st.secrets["snowflake"]["role"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database="DB_NXT",
    )


conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# Sidebar
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    st.page_link("app.py", label="Home", icon="🏠")
    st.page_link("pages/1_Order_Detail.py", label="Order Detail", icon="📊")
    st.page_link("pages/2_Manufacturer_Compare.py", label="Manufacturer Compare", icon="⚖️")
    st.page_link("pages/3_Period_Compare.py", label="Period Compare", icon="📅")
    st.markdown("---")

    available_years = get_available_years(conn, territory_filter)

    st.markdown("#### Period A")
    year_a = st.selectbox("Year A", options=available_years, index=0, key="year_a")

    st.markdown("#### Period B")
    default_b = 1 if len(available_years) > 1 else 0
    year_b = st.selectbox("Year B", options=available_years, index=default_b, key="year_b")

    st.markdown("---")
    options = get_filter_options(conn, territory_filter, year_a)
    manufacturer_filter = st.multiselect("Manufacturer (optional)", options=options["manufacturers"],
                                         default=[], placeholder="All manufacturers")

    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# Main content
st.title("📅 Period Comparison")
st.caption(f"Comparing **{year_a}** vs **{year_b}** | {get_access_display(user)}")

if year_a == year_b:
    st.warning("Select two different years to compare.")
    st.stop()

st.markdown("---")

# KPI comparison
st.markdown("### Key Metrics Comparison")

kpis_a = get_kpis(conn, territory_filter, manufacturer_filter=manufacturer_filter or None, year=year_a)
kpis_b = get_kpis(conn, territory_filter, manufacturer_filter=manufacturer_filter or None, year=year_b)


def calc_delta(a, b):
    if b == 0:
        return None
    return ((a - b) / b) * 100


col1, col2, col3, col4 = st.columns(4)

delta_sales = calc_delta(kpis_a["dollars"], kpis_b["dollars"])
delta_cases = calc_delta(kpis_a["qty"], kpis_b["qty"])
delta_comm = calc_delta(kpis_a["comm"], kpis_b["comm"])
delta_orders = calc_delta(kpis_a["orders"], kpis_b["orders"])

col1.metric(f"Sales ({year_a})", f"${kpis_a['dollars']:,.0f}",
            delta=f"{delta_sales:+.1f}% vs {year_b}" if delta_sales is not None else None)
col2.metric(f"Cases ({year_a})", f"{kpis_a['qty']:,.0f}",
            delta=f"{delta_cases:+.1f}% vs {year_b}" if delta_cases is not None else None)
col3.metric(f"Commission ({year_a})", f"${kpis_a['comm']:,.0f}",
            delta=f"{delta_comm:+.1f}% vs {year_b}" if delta_comm is not None else None)
col4.metric(f"Orders ({year_a})", f"{kpis_a['orders']:,}",
            delta=f"{delta_orders:+.1f}% vs {year_b}" if delta_orders is not None else None)

st.markdown("")

# Period B reference row
ref1, ref2, ref3, ref4 = st.columns(4)
ref1.caption(f"{year_b}: ${kpis_b['dollars']:,.0f}")
ref2.caption(f"{year_b}: {kpis_b['qty']:,.0f}")
ref3.caption(f"{year_b}: ${kpis_b['comm']:,.0f}")
ref4.caption(f"{year_b}: {kpis_b['orders']:,}")

st.markdown("---")

# Monthly trend overlay
st.markdown("### Monthly Sales Overlay")

monthly_a = get_monthly_breakdown(conn, territory_filter,
                                  manufacturer_filter=manufacturer_filter or None, year=year_a)
monthly_b = get_monthly_breakdown(conn, territory_filter,
                                  manufacturer_filter=manufacturer_filter or None, year=year_b)

if not monthly_a.empty or not monthly_b.empty:
    if not monthly_a.empty:
        monthly_a["Period"] = str(year_a)
    if not monthly_b.empty:
        monthly_b["Period"] = str(year_b)

    combined = pd.concat([monthly_a, monthly_b], ignore_index=True)

    fig = px.bar(combined, x="Month Name", y="Total Dollars", color="Period",
                 barmode="group", text_auto="$.2s",
                 color_discrete_map={str(year_a): "#1B4F72", str(year_b): "#A9CCE3"})
    fig.update_layout(height=400, xaxis_title="", yaxis_title="Sales ($)")
    st.plotly_chart(fig, use_container_width=True)

    # Monthly detail table
    with st.expander("Monthly detail table"):
        # Pivot for comparison
        if not monthly_a.empty and not monthly_b.empty:
            merge_df = monthly_a[["Month Name", "Total Dollars", "Total Qty"]].merge(
                monthly_b[["Month Name", "Total Dollars", "Total Qty"]],
                on="Month Name", how="outer", suffixes=(f" ({year_a})", f" ({year_b})"))
            st.dataframe(merge_df, use_container_width=True, hide_index=True)
else:
    st.info("No data available for the selected periods.")

st.markdown("---")

# Top movers
st.markdown("### Top Manufacturers — Period Change")

where_a = _build_where(territory_filter, manufacturer_filter=manufacturer_filter or None, year_filter=year_a)
where_b = _build_where(territory_filter, manufacturer_filter=manufacturer_filter or None, year_filter=year_b)

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
        COALESCE(a.dollars_a, 0) AS "Sales {year_a}",
        COALESCE(b.dollars_b, 0) AS "Sales {year_b}",
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
        fig = px.bar(growers, x="Manufacturer", y=f"Change ($)",
                     color_discrete_sequence=["#27AE60"],
                     title="Top 10 Growing Manufacturers")
        fig.update_layout(xaxis_tickangle=-45, height=350)
        st.plotly_chart(fig, use_container_width=True)

        # Full table
        with st.expander("Full comparison table"):
            st.dataframe(movers_df, use_container_width=True, hide_index=True)
except Exception as e:
    st.error(f"Error: {str(e)[:200]}")
