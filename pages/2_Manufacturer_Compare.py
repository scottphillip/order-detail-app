"""
Manufacturer Comparison - Side-by-side analysis of multiple manufacturers.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from utils.auth import get_access_filter, get_access_display
from utils.data import (
    get_kpis, get_monthly_breakdown, get_filter_options,
    get_available_years, get_distributor_parents, ORDER_VIEW, PARSE_DATE, _build_where,
)

st.set_page_config(page_title="Manufacturer Compare | Affinity Insights", page_icon="🍴",
                   layout="wide", initial_sidebar_state="expanded")

if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()


def get_snowflake_connection():
    import snowflake.connector
    if "sf_conn" not in st.session_state or st.session_state.sf_conn is None:
        st.session_state.sf_conn = snowflake.connector.connect(
            account=st.secrets["snowflake"]["account"],
            user=st.secrets["snowflake"]["user"],
            password=st.secrets["snowflake"]["password"],
            role=st.secrets["snowflake"]["role"],
            warehouse=st.secrets["snowflake"]["warehouse"],
            database="DB_NXT",
        )
    else:
        try:
            st.session_state.sf_conn.cursor().execute("SELECT 1")
        except Exception:
            st.session_state.sf_conn = snowflake.connector.connect(
                account=st.secrets["snowflake"]["account"],
                user=st.secrets["snowflake"]["user"],
                password=st.secrets["snowflake"]["password"],
                role=st.secrets["snowflake"]["role"],
                warehouse=st.secrets["snowflake"]["warehouse"],
                database="DB_NXT",
            )
    return st.session_state.sf_conn


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
    if st.button("Period Compare", use_container_width=True, key="nav_period"):
        st.switch_page("pages/3_Period_Compare.py")
    if st.button("Scorecard Analytics", use_container_width=True, key="nav_scorecard"):
        st.switch_page("pages/4_Scorecard_Analytics.py")
    st.markdown("---")

    available_years = get_available_years(conn, territory_filter)
    current_year = datetime.now().year
    default_idx = available_years.index(current_year) if current_year in available_years else 0
    selected_year = st.selectbox("Year", options=available_years if available_years else [current_year],
                                 index=default_idx)

    options = get_filter_options(conn, territory_filter, selected_year)

    st.markdown("#### Select Manufacturers to Compare")
    selected_mfrs = st.multiselect("Manufacturers", options=options["manufacturers"],
                                   default=[], placeholder="Pick 2 or more",
                                   max_selections=6)

    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# Main content
st.title("Manufacturer Comparison")
st.caption(f"{selected_year} YTD | {get_access_display(user)}")

if len(selected_mfrs) < 2:
    st.info("Select **2 or more manufacturers** from the sidebar to compare them side by side.")
    st.stop()

st.markdown("---")

# KPI comparison
st.markdown("### Key Metrics")
cols = st.columns(len(selected_mfrs))
mfr_kpis = {}
for i, mfr in enumerate(selected_mfrs):
    kpis = get_kpis(conn, territory_filter, manufacturer_filter=[mfr], year=selected_year)
    mfr_kpis[mfr] = kpis
    with cols[i]:
        st.markdown(f"**{mfr}**")
        st.metric("Sales", f"${kpis['dollars']:,.0f}")
        st.metric("Cases", f"{kpis['qty']:,.0f}")
        st.metric("Commission", f"${kpis['comm']:,.0f}")
        st.metric("Orders", f"{kpis['orders']:,}")

st.markdown("---")

# Monthly trend overlay
st.markdown("### Monthly Sales Trend")

import pandas as pd
all_monthly = []
for mfr in selected_mfrs:
    df = get_monthly_breakdown(conn, territory_filter, manufacturer_filter=[mfr], year=selected_year)
    if not df.empty:
        df["Manufacturer"] = mfr
        all_monthly.append(df)

if all_monthly:
    combined = pd.concat(all_monthly, ignore_index=True)
    fig = px.bar(combined, x="Month Name", y="Total Dollars", color="Manufacturer",
                 barmode="group", text_auto="$.2s")
    fig.update_layout(height=400, xaxis_title="", yaxis_title="Sales ($)")
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# Distributor breakdown per manufacturer
st.markdown("### Top Distributors by Manufacturer")
for mfr in selected_mfrs:
    with st.expander(f"**{mfr}** — Top Distributors"):
        parents_df = get_distributor_parents(conn, territory_filter, manufacturer_filter=[mfr], year=selected_year)
        if not parents_df.empty:
            fig = px.bar(parents_df.head(10), x="Parent", y="Total Dollars",
                         color_discrete_sequence=["#1B4F72"])
            fig.update_layout(xaxis_tickangle=-45, height=300)
            st.plotly_chart(fig, use_container_width=True)

# Category breakdown
st.markdown("### Category Mix")
cat_data = []
for mfr in selected_mfrs:
    where = _build_where(territory_filter, manufacturer_filter=[mfr], year_filter=selected_year)
    query = f"""
        SELECT CATEGORY, SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Dollars"
        FROM {ORDER_VIEW}
        WHERE {where} AND CATEGORY IS NOT NULL AND CATEGORY != ''
        GROUP BY CATEGORY ORDER BY "Dollars" DESC LIMIT 10
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    if not df.empty:
        df["Manufacturer"] = mfr
        cat_data.append(df)

if cat_data:
    combined_cat = pd.concat(cat_data, ignore_index=True)
    fig = px.bar(combined_cat, x="CATEGORY", y="Dollars", color="Manufacturer",
                 barmode="group")
    fig.update_layout(xaxis_tickangle=-45, height=400, xaxis_title="Category", yaxis_title="Sales ($)")
    st.plotly_chart(fig, use_container_width=True)
