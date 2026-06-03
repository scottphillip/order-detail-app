"""
Affinity Group - Order Detail Analytics
External Streamlit app with role-based access control, monthly breakdowns,
distributor hierarchy, and natural language querying.
Uses VW_MYORDERDETAIL_ALL which has PARENT_DISTRIBUTOR pre-joined.
"""
import streamlit as st
import snowflake.connector
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from utils.auth import authenticate_user, get_access_filter, get_access_display
from utils.data import (
    get_kpis, get_monthly_breakdown, get_top_manufacturers, get_sales_trend,
    get_distributor_parents, get_parent_stores, get_parent_monthly,
    get_pfg_summary, get_filter_options, get_categories_for_manufacturers,
    get_available_years, PFG_PARENTS,
)
from utils.nl_query import ask_cortex_analyst

# Page config
st.set_page_config(
    page_title="Affinity Order Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)


@st.cache_resource
def get_snowflake_connection():
    """Create a Snowflake connection using secrets."""
    return snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        role=st.secrets["snowflake"]["role"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database="DB_NXT",
    )


def send_email_via_graph(recipient_email: str, subject: str, body_html: str):
    """Send email using Microsoft Graph API via Snowflake procedure."""
    conn = get_snowflake_connection()
    escaped_email = recipient_email.replace("'", "''")
    escaped_subject = subject.replace("'", "''")
    escaped_body = body_html.replace("'", "''")
    query = f"""
        CALL OFFICE365.DATA.SEND_EMAIL_VIA_GRAPH(
            '{escaped_email}', '{escaped_subject}', '{escaped_body}'
        )
    """
    return conn.cursor().execute(query).fetchone()


def auto_chart(df):
    """Auto-generate a chart based on the DataFrame structure."""
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
        fig = px.line(df, x=date_cols[0], y=numeric_cols[0],
                      title=f"{numeric_cols[0]} over {date_cols[0]}")
        return fig
    if non_numeric_cols and numeric_cols:
        plot_df = df.head(15)
        fig = px.bar(plot_df, x=non_numeric_cols[0], y=numeric_cols[0],
                     title=f"{numeric_cols[0]} by {non_numeric_cols[0]}")
        fig.update_layout(xaxis_tickangle=-45)
        return fig
    return None


def format_dollars(val):
    """Format dollar amounts."""
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:,.0f}"


# =====================================================
# LOGIN
# =====================================================

if "user" not in st.session_state:
    st.title("Affinity Order Analytics")
    st.markdown("---")
    st.markdown("### Sign in with your Affinity email")
    st.markdown("Enter your @affinitysales.com email to access the dashboard.")

    col1, col2 = st.columns([2, 1])
    with col1:
        email = st.text_input("Email address", placeholder="your.name@affinitysales.com")

    if st.button("Sign In", type="primary"):
        if not email:
            st.error("Please enter your email address.")
        elif not email.strip().lower().endswith("@affinitysales.com"):
            st.error("Only @affinitysales.com email addresses are authorized.")
        else:
            with st.spinner("Verifying..."):
                conn = get_snowflake_connection()
                user = authenticate_user(email, conn)
                if user:
                    st.session_state.user = user
                    st.rerun()
                else:
                    st.error("Email not found in the Affinity directory.")
    st.stop()


# =====================================================
# AUTHENTICATED - MAIN APP
# =====================================================

conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# =====================================================
# SIDEBAR
# =====================================================

with st.sidebar:
    st.markdown(f"### Welcome, {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")

    st.markdown("#### Filters")

    # Year selector
    available_years = get_available_years(conn, territory_filter)
    current_year = datetime.now().year
    if current_year in available_years:
        default_idx = available_years.index(current_year)
    else:
        default_idx = 0
    selected_year = st.selectbox(
        "Year",
        options=available_years if available_years else [current_year],
        index=default_idx,
    )

    # Get filter options scoped to year
    options = get_filter_options(conn, territory_filter, selected_year)

    # Manufacturer filter
    manufacturer_filter = st.multiselect(
        "Manufacturer",
        options=options["manufacturers"],
        default=[],
        placeholder="All manufacturers"
    )

    # Category filter (appears when manufacturer selected)
    category_filter = []
    if manufacturer_filter:
        categories = get_categories_for_manufacturers(conn, territory_filter, manufacturer_filter)
        if categories:
            category_filter = st.multiselect(
                "Item Category",
                options=categories,
                default=[],
                placeholder="All categories"
            )

    # Distributor hierarchy filter: Parent → Sub-distributor → Location
    st.markdown("#### Distributor")

    # Level 1: Parent Distributor
    parent_options = ["All Distributors", "PFG (Performance Food Group)"]
    for p in options.get("parents", []):
        if p["name"] not in ["Independent"] and p["name"] not in PFG_PARENTS:
            parent_options.append(f"{p['name']} ({p['stores']})")
    parent_options.append("Independent")

    selected_parent = st.selectbox(
        "Parent Distributor",
        options=parent_options,
        index=0,
    )

    # Determine parent filter (string-based, no more dist codes)
    parent_filter = None
    selected_parent_name = None
    store_name = None

    if selected_parent == "All Distributors":
        parent_filter = None
    elif selected_parent == "PFG (Performance Food Group)":
        parent_filter = "PFG"
        selected_parent_name = "PFG"

        # Level 2: PFG Sub-distributor
        pfg_sub_options = ["All PFG Companies"] + PFG_PARENTS
        selected_sub = st.selectbox("Sub-Distributor", options=pfg_sub_options, index=0)

        if selected_sub != "All PFG Companies":
            parent_filter = selected_sub
            selected_parent_name = selected_sub

            # Level 3: Individual Location
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
        # Regular parent (e.g., Restaurant Depot, Sysco, US Foods)
        parent_name = selected_parent.rsplit(" (", 1)[0]
        parent_filter = parent_name
        selected_parent_name = parent_name

        # Level 2: Individual Location under this parent
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
# HEADER
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

# =====================================================
# KPI ROW
# =====================================================

kpis = get_kpis(conn, territory_filter, manufacturer_filter, parent_filter,
                category_filter, selected_year, store_name)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("YTD Sales", f"${kpis['dollars']:,.0f}")
col2.metric("Total Orders", f"{kpis['orders']:,}")
col3.metric("Total Cases", f"{kpis['qty']:,.0f}")
col4.metric("Commission", f"${kpis['comm']:,.0f}")
col5.metric("Avg Line Value", f"${kpis['avg_order']:,.2f}")

st.markdown("---")

# =====================================================
# MONTHLY BREAKDOWN (DEFAULT VIEW)
# =====================================================

st.markdown("### 📅 Monthly Sales Breakdown")

monthly_df = get_monthly_breakdown(conn, territory_filter, manufacturer_filter,
                                   parent_filter, category_filter, selected_year, store_name)

if not monthly_df.empty:
    fig = px.bar(
        monthly_df, x="Month Name", y="Total Dollars",
        text_auto="$.2s",
        color_discrete_sequence=["#1B4F72"],
    )
    fig.update_layout(
        height=350,
        xaxis_title="",
        yaxis_title="Sales ($)",
        xaxis_tickangle=0,
    )
    fig.update_traces(textposition="outside")
    st.plotly_chart(fig, use_container_width=True)

    # Monthly detail table
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

# =====================================================
# NATURAL LANGUAGE QUERY
# =====================================================

st.markdown("### 💬 Ask a Question About Your Data")
st.caption("Type a question in plain English and get results with charts.")

question = st.text_input(
    "Your question",
    placeholder="e.g., What are the top 5 manufacturers by total dollars this month?",
    label_visibility="collapsed"
)

if question:
    with st.spinner("Analyzing your question..."):
        result_df, sql_or_error = ask_cortex_analyst(conn, question, territory_filter)

    if result_df is not None and not result_df.empty:
        chart = auto_chart(result_df)
        if chart:
            st.plotly_chart(chart, use_container_width=True)
        st.dataframe(result_df, use_container_width=True, hide_index=True)
        with st.expander("View generated SQL"):
            st.code(sql_or_error, language="sql")
    elif result_df is not None and result_df.empty:
        st.info("Query returned no results. Try a different question.")
    else:
        st.error(sql_or_error)

st.markdown("---")

# =====================================================
# TOP MANUFACTURERS + DISTRIBUTOR PARENTS
# =====================================================

st.markdown("### 📈 Overview")

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.markdown("#### Top 10 Manufacturers")
    mfr_df = get_top_manufacturers(conn, territory_filter, parent_filter,
                                   category_filter, selected_year)
    if not mfr_df.empty:
        fig = px.bar(
            mfr_df, x="Manufacturer", y="Total Dollars",
            color_discrete_sequence=["#1B4F72"]
        )
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No manufacturer data available.")

with chart_col2:
    st.markdown("#### Top Distributor Parents")
    parents_df = get_distributor_parents(conn, territory_filter, manufacturer_filter, selected_year)
    if not parents_df.empty:
        top_parents = parents_df.head(10)
        fig = px.bar(
            top_parents, x="Parent", y="Total Dollars",
            color_discrete_sequence=["#148F77"]
        )
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No distributor data available.")

st.markdown("---")

# =====================================================
# DISTRIBUTOR HIERARCHY DRILL-DOWN
# =====================================================

st.markdown("### 🏢 Distributor Hierarchy")

# PFG Summary always shown first
pfg_data = get_pfg_summary(conn, territory_filter, manufacturer_filter, selected_year)
if pfg_data["total_dollars"] > 0:
    with st.expander(
        f"**PFG (Performance Food Group)** — {format_dollars(pfg_data['total_dollars'])} | {pfg_data['total_stores']} stores",
        expanded=(parent_filter == "PFG")
    ):
        if not pfg_data["breakdown"].empty:
            for _, row in pfg_data["breakdown"].iterrows():
                pname = row["Parent"]
                st.markdown(f"**{pname}** — {format_dollars(row['Total Dollars'])} | {int(row['Store Count'])} stores")

                stores_df = get_parent_stores(conn, territory_filter, pname,
                                              manufacturer_filter, selected_year)
                if not stores_df.empty:
                    display_stores = stores_df[["Store", "Total Dollars", "Total Qty", "Total Comm", "Orders"]].copy()
                    display_stores["Total Dollars"] = display_stores["Total Dollars"].apply(lambda x: f"${x:,.0f}")
                    display_stores["Total Comm"] = display_stores["Total Comm"].apply(lambda x: f"${x:,.0f}")
                    display_stores.columns = ["Store", "Dollars", "Cases", "Commission", "Orders"]
                    st.dataframe(display_stores, use_container_width=True, hide_index=True, height=200)

# Other top parents
if not parents_df.empty:
    non_pfg_parents = parents_df[
        ~parents_df["Parent"].isin(PFG_PARENTS + ["Independent"])
    ].head(15)

    for _, row in non_pfg_parents.iterrows():
        pname = row["Parent"]
        with st.expander(
            f"**{pname}** — {format_dollars(row['Total Dollars'])} | {int(row['Store Count'])} stores",
            expanded=(parent_filter == pname)
        ):
            p_monthly = get_parent_monthly(conn, territory_filter, pname,
                                           manufacturer_filter, selected_year)
            if not p_monthly.empty:
                fig = px.bar(
                    p_monthly, x="Month Name", y="Total Dollars",
                    color_discrete_sequence=["#148F77"],
                )
                fig.update_layout(height=250, xaxis_title="", yaxis_title="Sales ($)")
                st.plotly_chart(fig, use_container_width=True)

            stores_df = get_parent_stores(conn, territory_filter, pname,
                                          manufacturer_filter, selected_year)
            if not stores_df.empty:
                display_stores = stores_df[["Store", "Total Dollars", "Total Qty", "Total Comm", "Orders"]].copy()
                display_stores["Total Dollars"] = display_stores["Total Dollars"].apply(lambda x: f"${x:,.0f}")
                display_stores["Total Comm"] = display_stores["Total Comm"].apply(lambda x: f"${x:,.0f}")
                display_stores.columns = ["Store", "Dollars", "Cases", "Commission", "Orders"]
                st.dataframe(display_stores, use_container_width=True, hide_index=True, height=300)

    # Independent
    ind_row = parents_df[parents_df["Parent"] == "Independent"]
    if not ind_row.empty:
        ind = ind_row.iloc[0]
        with st.expander(
            f"**Independent** — {format_dollars(ind['Total Dollars'])} | {int(ind['Store Count'])} stores"
        ):
            stores_df = get_parent_stores(conn, territory_filter, "Independent",
                                          manufacturer_filter, selected_year)
            if not stores_df.empty:
                display_stores = stores_df[["Store", "Total Dollars", "Total Qty", "Total Comm", "Orders"]].head(50).copy()
                display_stores["Total Dollars"] = display_stores["Total Dollars"].apply(lambda x: f"${x:,.0f}")
                display_stores["Total Comm"] = display_stores["Total Comm"].apply(lambda x: f"${x:,.0f}")
                display_stores.columns = ["Store", "Dollars", "Cases", "Commission", "Orders"]
                st.dataframe(display_stores, use_container_width=True, hide_index=True, height=400)

# =====================================================
# EMAIL RESULTS
# =====================================================

st.markdown("---")
st.markdown("### 📧 Email Results")

with st.expander("Send dashboard summary via email"):
    email_recipient = st.text_input(
        "Recipient email", value=user["MAIL"], key="email_recipient"
    )
    email_subject = st.text_input(
        "Subject",
        value=f"Order Analytics Summary - {datetime.now().strftime('%m/%d/%Y')}",
        key="email_subject"
    )

    if st.button("Send Email", type="primary", key="send_email_btn"):
        if not email_recipient:
            st.error("Please enter a recipient email.")
        else:
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>Order Detail Analytics Summary</h2>
                <p>Generated by {user['DISPLAY_NAME']} on {datetime.now().strftime('%m/%d/%Y %I:%M %p')}</p>
                <p><strong>Access Level:</strong> {get_access_display(user)}</p>
                <hr>
                <h3>{selected_year} YTD Key Metrics</h3>
                <table style="border-collapse: collapse; width: 100%;">
                    <tr style="background-color: #f2f2f2;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Sales</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">${kpis['dollars']:,.0f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Orders</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{kpis['orders']:,}</td>
                    </tr>
                    <tr style="background-color: #f2f2f2;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Cases</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{kpis['qty']:,.0f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Commission</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">${kpis['comm']:,.0f}</td>
                    </tr>
                    <tr style="background-color: #f2f2f2;">
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Avg Line Value</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">${kpis['avg_order']:,.2f}</td>
                    </tr>
                </table>
                <hr>
                <p style="color: #666; font-size: 12px;">
                    This report was generated from the Affinity Order Analytics dashboard.
                </p>
            </body>
            </html>
            """
            with st.spinner("Sending email..."):
                try:
                    send_email_via_graph(email_recipient, email_subject, html_body)
                    st.success(f"Email sent to {email_recipient}")
                except Exception as e:
                    st.error(f"Failed to send email: {str(e)}")
