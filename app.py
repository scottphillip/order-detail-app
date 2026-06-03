"""
Affinity Group - Order Detail Analytics
External Streamlit app with role-based access control and natural language querying.
"""
import streamlit as st
import snowflake.connector
import plotly.express as px
import plotly.graph_objects as go
import requests
import json
from datetime import datetime, timedelta

from utils.auth import authenticate_user, get_access_filter, get_access_display
from utils.data import (
    get_kpis, get_top_manufacturers, get_sales_trend,
    get_distributor_breakdown, get_filter_options
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
        database="DB_PROD_RAW",
    )


def send_email_via_graph(recipient_email: str, subject: str, body_html: str):
    """Send email using Microsoft Graph API via Snowflake procedure."""
    conn = get_snowflake_connection()
    escaped_email = recipient_email.replace("'", "''")
    escaped_subject = subject.replace("'", "''")
    escaped_body = body_html.replace("'", "''")

    query = f"""
        CALL OFFICE365.DATA.SEND_EMAIL_VIA_GRAPH(
            '{escaped_email}',
            '{escaped_subject}',
            '{escaped_body}'
        )
    """
    result = conn.cursor().execute(query).fetchone()
    return result


def auto_chart(df):
    """Auto-generate a chart based on the DataFrame structure."""
    if df is None or df.empty:
        return None

    cols = df.columns.tolist()
    numeric_cols = df.select_dtypes(include=["number", "float64", "int64"]).columns.tolist()
    non_numeric_cols = [c for c in cols if c not in numeric_cols]

    if not numeric_cols:
        return None

    # If we have a date-like column and a numeric column -> line chart
    date_cols = [c for c in cols if "date" in c.lower() or "week" in c.lower() or "month" in c.lower() or "year" in c.lower()]
    if date_cols and numeric_cols:
        fig = px.line(df, x=date_cols[0], y=numeric_cols[0], title=f"{numeric_cols[0]} over {date_cols[0]}")
        return fig

    # If we have a categorical column and a numeric column -> bar chart
    if non_numeric_cols and numeric_cols:
        # Limit to top 15 for readability
        plot_df = df.head(15)
        fig = px.bar(
            plot_df, x=non_numeric_cols[0], y=numeric_cols[0],
            title=f"{numeric_cols[0]} by {non_numeric_cols[0]}"
        )
        fig.update_layout(xaxis_tickangle=-45)
        return fig

    return None


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
                    st.error("Email not found in the Affinity directory. Please check your email address.")

    st.stop()


# =====================================================
# AUTHENTICATED - MAIN APP
# =====================================================

conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# Sidebar
with st.sidebar:
    st.markdown(f"### Welcome, {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")

    # Get filter options scoped to user's access
    options = get_filter_options(conn, territory_filter)

    st.markdown("#### Filters")
    manufacturer_filter = st.multiselect(
        "Manufacturer",
        options=options["manufacturers"],
        default=[],
        placeholder="All manufacturers"
    )
    distributor_filter = st.multiselect(
        "Distributor",
        options=options["distributors"],
        default=[],
        placeholder="All distributors"
    )

    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# Header
st.title("📊 Order Detail Analytics")
st.caption(f"Data from weekly order detail reports | {user['DEPARTMENT']} - {user.get('OFFICE_LOCATION', 'All')}")

# =====================================================
# KPI ROW
# =====================================================

kpis = get_kpis(conn, territory_filter, manufacturer_filter, distributor_filter)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Sales", f"${kpis['dollars']:,.0f}")
col2.metric("Total Orders", f"{kpis['orders']:,}")
col3.metric("Total Quantity", f"{kpis['qty']:,.0f}")
col4.metric("Avg Line Value", f"${kpis['avg_order']:,.2f}")

st.markdown("---")

# =====================================================
# NATURAL LANGUAGE QUERY
# =====================================================

st.markdown("### 💬 Ask a Question About Your Data")
st.caption("Type a question in plain English and get results with charts.")

question = st.text_input(
    "Your question",
    placeholder="e.g., What are the top 5 manufacturers by total dollars?",
    label_visibility="collapsed"
)

if question:
    with st.spinner("Analyzing your question..."):
        result_df, sql_or_error = ask_cortex_analyst(conn, question, territory_filter)

    if result_df is not None and not result_df.empty:
        # Show chart if possible
        chart = auto_chart(result_df)
        if chart:
            st.plotly_chart(chart, use_container_width=True)

        # Show data table
        st.dataframe(result_df, use_container_width=True, hide_index=True)

        with st.expander("View generated SQL"):
            st.code(sql_or_error, language="sql")
    elif result_df is not None and result_df.empty:
        st.info("Query returned no results. Try a different question.")
    else:
        st.error(sql_or_error)

st.markdown("---")

# =====================================================
# DEFAULT CHARTS
# =====================================================

st.markdown("### 📈 Overview")

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.markdown("#### Top 10 Manufacturers by Sales")
    mfr_df = get_top_manufacturers(conn, territory_filter)
    if not mfr_df.empty:
        fig = px.bar(
            mfr_df, x="Manufacturer", y="Total Dollars",
            color_discrete_sequence=["#1B4F72"]
        )
        fig.update_layout(xaxis_tickangle=-45, height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data available for your territory.")

with chart_col2:
    st.markdown("#### Weekly Sales Trend")
    trend_df = get_sales_trend(conn, territory_filter)
    if not trend_df.empty:
        fig = px.line(
            trend_df, x="Week", y="Total Dollars",
            color_discrete_sequence=["#2E86C1"]
        )
        fig.update_layout(height=400)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No trend data available.")

# Distributor breakdown
st.markdown("#### Top 10 Distributors by Sales")
dist_df = get_distributor_breakdown(conn, territory_filter)
if not dist_df.empty:
    fig = px.bar(
        dist_df, x="Distributor", y="Total Dollars",
        color_discrete_sequence=["#148F77"]
    )
    fig.update_layout(xaxis_tickangle=-45, height=400)
    st.plotly_chart(fig, use_container_width=True)

# =====================================================
# EMAIL RESULTS
# =====================================================

st.markdown("---")
st.markdown("### 📧 Email Results")

with st.expander("Send dashboard summary via email"):
    email_recipient = st.text_input(
        "Recipient email",
        value=user["MAIL"],
        key="email_recipient"
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
            # Build HTML summary
            html_body = f"""
            <html>
            <body style="font-family: Arial, sans-serif;">
                <h2>Order Detail Analytics Summary</h2>
                <p>Generated by {user['DISPLAY_NAME']} on {datetime.now().strftime('%m/%d/%Y %I:%M %p')}</p>
                <p><strong>Access Level:</strong> {get_access_display(user)}</p>
                <hr>
                <h3>Key Metrics</h3>
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
                        <td style="padding: 10px; border: 1px solid #ddd;"><strong>Total Quantity</strong></td>
                        <td style="padding: 10px; border: 1px solid #ddd;">{kpis['qty']:,.0f}</td>
                    </tr>
                    <tr>
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
                    result = send_email_via_graph(email_recipient, email_subject, html_body)
                    st.success(f"Email sent to {email_recipient}")
                except Exception as e:
                    st.error(f"Failed to send email: {str(e)}")
