"""
Affinity Insights & Analytics - Landing Page
Sales intelligence hub with navigation to analytics modules.
"""
import streamlit as st
import snowflake.connector
from datetime import datetime

from utils.auth import authenticate_user, get_access_filter, get_access_display
from utils.data import get_kpis, get_available_years

# Page config
st.set_page_config(
    page_title="Affinity Insights & Analytics",
    page_icon="🍴",
    layout="wide",
    initial_sidebar_state="collapsed"
)


def _create_snowflake_connection():
    """Create a fresh Snowflake connection."""
    return snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        role=st.secrets["snowflake"]["role"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database="DB_NXT",
    )


def get_snowflake_connection():
    """Get Snowflake connection with automatic reconnect on token expiry."""
    if "sf_conn" not in st.session_state or st.session_state.sf_conn is None:
        st.session_state.sf_conn = _create_snowflake_connection()
    else:
        try:
            st.session_state.sf_conn.cursor().execute("SELECT 1")
        except Exception:
            st.session_state.sf_conn = _create_snowflake_connection()
    return st.session_state.sf_conn


# =====================================================
# LOGIN
# =====================================================

if "user" not in st.session_state:
    st.markdown("")
    st.markdown("")
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("""
        <div style="text-align: center; margin-bottom: 20px;">
            <div style="background: #2D2D2D; padding: 20px 30px; border-radius: 12px; display: inline-block;">
                <span style="color: #F5921E; font-size: 28px; font-weight: bold;">AFFINITY</span>
                <span style="color: #FFFFFF; font-size: 28px; font-weight: 300;"> GROUP</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("##### Insights & Analytics")
        st.markdown("---")
        st.markdown("**Sign in with your Affinity email to get started.**")

        email = st.text_input("Email address", placeholder="your.name@affinitysales.com",
                              label_visibility="collapsed")

        if st.button("Sign In", type="primary", use_container_width=True):
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

        st.markdown("")
        st.caption("Powered by Snowflake + Cortex AI")
        st.markdown("""
        <style>
            .stButton > button[kind="primary"] {
                background-color: #F5921E;
                border-color: #F5921E;
            }
            .stButton > button[kind="primary"]:hover {
                background-color: #D47D17;
                border-color: #D47D17;
            }
        </style>
        """, unsafe_allow_html=True)
    st.stop()


# =====================================================
# AUTHENTICATED - LANDING PAGE
# =====================================================

conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# Sidebar
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    st.markdown("#### Navigation")
    if st.button("Order Detail", use_container_width=True):
        st.switch_page("pages/1_Order_Detail.py")
    if st.button("Manufacturer Compare", use_container_width=True):
        st.switch_page("pages/2_Manufacturer_Compare.py")
    if st.button("Period Compare", use_container_width=True):
        st.switch_page("pages/3_Period_Compare.py")
    if st.button("Scorecard Analytics", use_container_width=True):
        st.switch_page("pages/4_Scorecard_Analytics.py")
    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# Header
st.markdown("""
<div style="background: #2D2D2D; padding: 15px 25px; border-radius: 8px; margin-bottom: 15px;">
    <span style="color: #F5921E; font-size: 22px; font-weight: bold;">AFFINITY</span>
    <span style="color: #FFFFFF; font-size: 22px; font-weight: 300;"> GROUP</span>
    <span style="color: #AAAAAA; font-size: 14px; margin-left: 15px;">Insights & Analytics</span>
</div>
""", unsafe_allow_html=True)
st.markdown(f"Welcome back, **{user['DISPLAY_NAME']}**")
st.markdown("---")

# Quick YTD KPI summary
current_year = datetime.now().year
kpis = get_kpis(conn, territory_filter, year=current_year)

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric(f"{current_year} YTD Sales", f"${kpis['dollars']:,.0f}")
kpi2.metric("Total Orders", f"{kpis['orders']:,}")
kpi3.metric("Total Cases", f"{kpis['qty']:,.0f}")
kpi4.metric("Commission", f"${kpis['comm']:,.0f}")

st.markdown("---")
st.markdown("### What would you like to explore?")
st.markdown("")

# Navigation cards
col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 30px; border-radius: 12px; 
                color: white; min-height: 200px; border-left: 5px solid #F5921E;">
        <h3 style="color: #F5921E; margin-top: 0;">Order Detail</h3>
        <p style="color: #CCCCCC;">Explore YTD sales by manufacturer, distributor parent, 
        territory, and category. Drill into individual store performance.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Order Detail →", use_container_width=True, key="card_order"):
        st.switch_page("pages/1_Order_Detail.py")

with col2:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 30px; border-radius: 12px; 
                color: white; min-height: 200px; border-left: 5px solid #F5921E;">
        <h3 style="color: #F5921E; margin-top: 0;">Manufacturer Compare</h3>
        <p style="color: #CCCCCC;">Compare two or more manufacturers side by side — 
        dollars, cases, commission, and monthly trends overlaid.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Comparison →", use_container_width=True, key="card_compare"):
        st.switch_page("pages/2_Manufacturer_Compare.py")

col3, col4 = st.columns(2)

with col3:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 30px; border-radius: 12px; 
                color: white; min-height: 200px; border-left: 5px solid #F5921E;">
        <h3 style="color: #F5921E; margin-top: 0;">Period Compare</h3>
        <p style="color: #CCCCCC;">Compare sales across time periods — year over year, 
        month over month, or custom date ranges with change indicators.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Period Compare →", use_container_width=True, key="card_period"):
        st.switch_page("pages/3_Period_Compare.py")

with col4:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 30px; border-radius: 12px; 
                color: white; min-height: 200px; border-left: 5px solid #4CAF50;">
        <h3 style="color: #4CAF50; margin-top: 0;">Scorecard Analytics</h3>
        <p style="color: #CCCCCC;">Deep analytics across all 57 manufacturer clients — 
        trends, predictions, failing item detection, category breakdowns, and anomaly alerts.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open Scorecard Analytics →", use_container_width=True, key="card_scorecard"):
        st.switch_page("pages/4_Scorecard_Analytics.py")

st.markdown("---")
st.caption("Affinity Group | Insights & Analytics | Powered by Snowflake + Cortex AI")
