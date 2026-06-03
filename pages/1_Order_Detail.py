"""
Order Detail Analytics - Full dashboard with filters, hierarchy, and NL query.
"""
import streamlit as st
import plotly.express as px
from datetime import datetime

from utils.auth import get_access_filter, get_access_display
from utils.data import (
    get_kpis, get_monthly_breakdown, get_top_manufacturers,
    get_distributor_parents, get_parent_stores, get_parent_monthly,
    get_pfg_summary, get_filter_options, get_categories_for_manufacturers,
    get_available_years, PFG_PARENTS,
)
from utils.nl_query import ask_cortex_analyst

st.set_page_config(page_title="Order Detail | Affinity Insights", page_icon="📊",
                   layout="wide", initial_sidebar_state="expanded")

# Auth guard
if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
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


def send_email_via_graph(recipient_email: str, subject: str, body_html: str):
    conn = get_snowflake_connection()
    escaped_email = recipient_email.replace("'", "''")
    escaped_subject = subject.replace("'", "''")
    escaped_body = body_html.replace("'", "''")
    query = f"""CALL OFFICE365.DATA.SEND_EMAIL_VIA_GRAPH(
        '{escaped_email}', '{escaped_subject}', '{escaped_body}')"""
    return conn.cursor().execute(query).fetchone()


def auto_chart(df):
    if df is None or df.empty:
        return None
    cols = df.columns.tolist()
    numeric_cols = df.select_dtypes(include=["number", "float64", "int64"]).columns.tolist()
    non_numeric_cols = [c for c in cols if c not in numeric_cols]
    if not numeric_cols:
        return None
    date_cols = [c for c in cols if "date" in c.lower() or "week" in c.lower()
                 or "month" in c.lower() or "year" in c.lower()]
    if date_cols and numeric_cols:
        return px.line(df, x=date_cols[0], y=numeric_cols[0],
                       title=f"{numeric_cols[0]} over {date_cols[0]}")
    if non_numeric_cols and numeric_cols:
        return px.bar(df.head(15), x=non_numeric_cols[0], y=numeric_cols[0],
                      title=f"{numeric_cols[0]} by {non_numeric_cols[0]}")
    return None


def format_dollars(val):
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:,.0f}"


conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# =====================================================
# SIDEBAR
# =====================================================

with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    if st.button("🏠 Home", use_container_width=True, key="nav_home"):
        st.switch_page("app.py")
    if st.button("⚖️ Manufacturer Compare", use_container_width=True, key="nav_compare"):
        st.switch_page("pages/2_Manufacturer_Compare.py")
    if st.button("📅 Period Compare", use_container_width=True, key="nav_period"):
        st.switch_page("pages/3_Period_Compare.py")
    st.markdown("---")

    st.markdown("#### Filters")

    # Year selector
    available_years = get_available_years(conn, territory_filter)
    current_year = datetime.now().year
    default_idx = available_years.index(current_year) if current_year in available_years else 0
    selected_year = st.selectbox("Year", options=available_years if available_years else [current_year],
                                 index=default_idx)

    options = get_filter_options(conn, territory_filter, selected_year)

    # Manufacturer filter
    manufacturer_filter = st.multiselect("Manufacturer", options=options["manufacturers"],
                                         default=[], placeholder="All manufacturers")

    # Category filter
    category_filter = []
    if manufacturer_filter:
        categories = get_categories_for_manufacturers(conn, territory_filter, manufacturer_filter)
        if categories:
            category_filter = st.multiselect("Item Category", options=categories,
                                             default=[], placeholder="All categories")

    # Distributor hierarchy
    st.markdown("#### Distributor")
    parent_options = ["All Distributors", "PFG (Performance Food Group)"]
    for p in options.get("parents", []):
        if p["name"] not in ["Independent"] and p["name"] not in PFG_PARENTS:
            parent_options.append(f"{p['name']} ({p['stores']})")
    parent_options.append("Independent")

    selected_parent = st.selectbox("Parent Distributor", options=parent_options, index=0)

    parent_filter = None
    selected_parent_name = None
    store_name = None

    if selected_parent == "All Distributors":
        pass
    elif selected_parent == "PFG (Performance Food Group)":
        parent_filter = "PFG"
        selected_parent_name = "PFG"
        pfg_sub_options = ["All PFG Companies"] + PFG_PARENTS
        selected_sub = st.selectbox("Sub-Distributor", options=pfg_sub_options, index=0)
        if selected_sub != "All PFG Companies":
            parent_filter = selected_sub
            selected_parent_name = selected_sub
            stores_df = get_parent_stores(conn, territory_filter, selected_sub,
                                          manufacturer_filter, selected_year)
            if not stores_df.empty:
                store_options = ["All Locations"] + stores_df["Store"].tolist()
                selected_store = st.selectbox("Location", options=store_options, index=0)
                if selected_store != "All Locations":
                    store_name = selected_store
                    selected_parent_name = selected_store
    elif selected_parent == "Independent":
        parent_filter = "Independent"
        selected_parent_name = "Independent"
    else:
        parent_name = selected_parent.rsplit(" (", 1)[0]
        parent_filter = parent_name
        selected_parent_name = parent_name
        stores_df = get_parent_stores(conn, territory_filter, parent_name,
                                      manufacturer_filter, selected_year)
        if not stores_df.empty:
            store_options = ["All Locations"] + stores_df["Store"].tolist()
            selected_store = st.selectbox("Location", options=store_options, index=0)
            if selected_store != "All Locations":
                store_name = selected_store
                selected_parent_name = selected_store

    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# =====================================================
# MAIN CONTENT
# =====================================================

st.title("📊 Order Detail Analytics")
subtitle_parts = [f"{selected_year} YTD"]
if manufacturer_filter:
    subtitle_parts.append(f"Mfr: {', '.join(manufacturer_filter[:3])}")
if category_filter:
    subtitle_parts.append(f"Cat: {', '.join(category_filter[:3])}")
if selected_parent_name:
    subtitle_parts.append(f"Dist: {selected_parent_name}")
st.caption(" | ".join(subtitle_parts) + f" | {user['DEPARTMENT']} - {user.get('OFFICE_LOCATION', 'All')}")

# KPIs
kpis = get_kpis(conn, territory_filter, manufacturer_filter, parent_filter,
                category_filter, selected_year, store_name)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("YTD Sales", f"${kpis['dollars']:,.0f}")
col2.metric("Total Orders", f"{kpis['orders']:,}")
col3.metric("Total Cases", f"{kpis['qty']:,.0f}")
col4.metric("Commission", f"${kpis['comm']:,.0f}")
col5.metric("Avg Line Value", f"${kpis['avg_order']:,.2f}")

st.markdown("---")

# Monthly Breakdown
st.markdown("### 📅 Monthly Sales Breakdown")
monthly_df = get_monthly_breakdown(conn, territory_filter, manufacturer_filter,
                                   parent_filter, category_filter, selected_year, store_name)

if not monthly_df.empty:
    fig = px.bar(monthly_df, x="Month Name", y="Total Dollars", text_auto="$.2s",
                 color_discrete_sequence=["#1B4F72"])
    fig.update_layout(height=350, xaxis_title="", yaxis_title="Sales ($)", xaxis_tickangle=0)
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)
    with st.expander("Monthly detail"):
        display_df = monthly_df[["Month Name", "Total Dollars", "Total Qty", "Total Comm", "Orders"]].copy()
        display_df["Total Dollars"] = display_df["Total Dollars"].apply(lambda x: f"${x:,.0f}")
        display_df["Total Qty"] = display_df["Total Qty"].apply(lambda x: f"{x:,.0f}")
        display_df["Total Comm"] = display_df["Total Comm"].apply(lambda x: f"${x:,.0f}")
        display_df.columns = ["Month", "Dollars", "Cases", "Commission", "Orders"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)
else:
    st.info("No data available for the selected filters.")

st.markdown("---")

# NL Query
st.markdown("### 💬 Ask a Question About Your Data")
question = st.text_input("Your question",
                         placeholder="e.g., What are the top 5 manufacturers by total dollars?",
                         label_visibility="collapsed")
if question:
    with st.spinner("Analyzing..."):
        result_df, sql_or_error = ask_cortex_analyst(conn, question, territory_filter)
    if result_df is not None and not result_df.empty:
        chart = auto_chart(result_df)
        if chart:
            st.plotly_chart(chart, use_container_width=True)
        st.dataframe(result_df, use_container_width=True, hide_index=True)
        with st.expander("View generated SQL"):
            st.code(sql_or_error, language="sql")
    elif result_df is not None:
        st.info("Query returned no results.")
    else:
        st.error(sql_or_error)

st.markdown("---")

# Overview Charts
st.markdown("### 📈 Overview")
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.markdown("#### Top 10 Manufacturers")
    mfr_df = get_top_manufacturers(conn, territory_filter, parent_filter, category_filter, selected_year)
    if not mfr_df.empty:
        fig = px.bar(mfr_df, x="Manufacturer", y="Total Dollars", color_discrete_sequence=["#1B4F72"])
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)

with chart_col2:
    st.markdown("#### Top Distributor Parents")
    parents_df = get_distributor_parents(conn, territory_filter, manufacturer_filter, selected_year)
    if not parents_df.empty:
        fig = px.bar(parents_df.head(10), x="Parent", y="Total Dollars", color_discrete_sequence=["#148F77"])
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)

st.markdown("---")

# Distributor Hierarchy
st.markdown("### 🏢 Distributor Hierarchy")
pfg_data = get_pfg_summary(conn, territory_filter, manufacturer_filter, selected_year)
if pfg_data["total_dollars"] > 0:
    with st.expander(f"**PFG** — {format_dollars(pfg_data['total_dollars'])} | {pfg_data['total_stores']} stores",
                     expanded=(parent_filter == "PFG")):
        if not pfg_data["breakdown"].empty:
            for _, row in pfg_data["breakdown"].iterrows():
                pname = row["Parent"]
                st.markdown(f"**{pname}** — {format_dollars(row['Total Dollars'])} | {int(row['Store Count'])} stores")
                sdf = get_parent_stores(conn, territory_filter, pname, manufacturer_filter, selected_year)
                if not sdf.empty:
                    d = sdf[["Store", "Total Dollars", "Total Qty", "Total Comm", "Orders"]].copy()
                    d["Total Dollars"] = d["Total Dollars"].apply(lambda x: f"${x:,.0f}")
                    d["Total Comm"] = d["Total Comm"].apply(lambda x: f"${x:,.0f}")
                    d.columns = ["Store", "Dollars", "Cases", "Commission", "Orders"]
                    st.dataframe(d, use_container_width=True, hide_index=True, height=200)

if "parents_df" in dir() and not parents_df.empty:
    non_pfg = parents_df[~parents_df["Parent"].isin(PFG_PARENTS + ["Independent"])].head(15)
    for _, row in non_pfg.iterrows():
        pname = row["Parent"]
        with st.expander(f"**{pname}** — {format_dollars(row['Total Dollars'])} | {int(row['Store Count'])} stores",
                         expanded=(parent_filter == pname)):
            pm = get_parent_monthly(conn, territory_filter, pname, manufacturer_filter, selected_year)
            if not pm.empty:
                fig = px.bar(pm, x="Month Name", y="Total Dollars", color_discrete_sequence=["#148F77"])
                fig.update_layout(height=250, xaxis_title="", yaxis_title="Sales ($)")
                st.plotly_chart(fig, use_container_width=True)
            sdf = get_parent_stores(conn, territory_filter, pname, manufacturer_filter, selected_year)
            if not sdf.empty:
                d = sdf[["Store", "Total Dollars", "Total Qty", "Total Comm", "Orders"]].copy()
                d["Total Dollars"] = d["Total Dollars"].apply(lambda x: f"${x:,.0f}")
                d["Total Comm"] = d["Total Comm"].apply(lambda x: f"${x:,.0f}")
                d.columns = ["Store", "Dollars", "Cases", "Commission", "Orders"]
                st.dataframe(d, use_container_width=True, hide_index=True, height=300)

# Email
st.markdown("---")
st.markdown("### 📧 Email Results")
with st.expander("Send dashboard summary via email"):
    email_recipient = st.text_input("Recipient email", value=user["MAIL"], key="email_recipient")
    email_subject = st.text_input("Subject",
                                  value=f"Order Analytics Summary - {datetime.now().strftime('%m/%d/%Y')}",
                                  key="email_subject")
    if st.button("Send Email", type="primary", key="send_email_btn"):
        if email_recipient:
            html_body = f"""<html><body style="font-family:Arial,sans-serif;">
            <h2>Order Detail Analytics</h2>
            <p>Generated by {user['DISPLAY_NAME']} on {datetime.now().strftime('%m/%d/%Y %I:%M %p')}</p>
            <p><b>Access:</b> {get_access_display(user)}</p><hr>
            <h3>{selected_year} YTD</h3>
            <table style="border-collapse:collapse;width:100%;">
            <tr style="background:#f2f2f2;"><td style="padding:10px;border:1px solid #ddd;"><b>Sales</b></td><td style="padding:10px;border:1px solid #ddd;">${kpis['dollars']:,.0f}</td></tr>
            <tr><td style="padding:10px;border:1px solid #ddd;"><b>Orders</b></td><td style="padding:10px;border:1px solid #ddd;">{kpis['orders']:,}</td></tr>
            <tr style="background:#f2f2f2;"><td style="padding:10px;border:1px solid #ddd;"><b>Cases</b></td><td style="padding:10px;border:1px solid #ddd;">{kpis['qty']:,.0f}</td></tr>
            <tr><td style="padding:10px;border:1px solid #ddd;"><b>Commission</b></td><td style="padding:10px;border:1px solid #ddd;">${kpis['comm']:,.0f}</td></tr>
            </table><hr><p style="color:#666;font-size:12px;">Affinity Insights & Analytics</p>
            </body></html>"""
            with st.spinner("Sending..."):
                try:
                    send_email_via_graph(email_recipient, email_subject, html_body)
                    st.success(f"Sent to {email_recipient}")
                except Exception as e:
                    st.error(f"Failed: {str(e)}")
