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
    page_icon="🔷",
    layout="wide",
    initial_sidebar_state="collapsed"
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


# =====================================================
# LOGIN
# =====================================================

if "user" not in st.session_state:
    st.markdown("")
    st.markdown("")
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.markdown("## 🔷 Affinity Insights & Analytics")
        st.markdown("##### Your Sales Intelligence Hub")
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
    st.page_link("app.py", label="Home", icon="🏠")
    st.page_link("pages/1_Order_Detail.py", label="Order Detail", icon="📊")
    st.page_link("pages/2_Manufacturer_Compare.py", label="Manufacturer Compare", icon="⚖️")
    st.page_link("pages/3_Period_Compare.py", label="Period Compare", icon="📅")
    st.markdown("---")
    if st.button("Sign Out"):
        del st.session_state.user
        st.rerun()

# Header
st.markdown("## 🔷 Affinity Insights & Analytics")
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
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    <div style="background: linear-gradient(135deg, #1B4F72 0%, #2E86C1 100%); 
                padding: 30px; border-radius: 12px; color: white; min-height: 200px;">
        <h3 style="color: white; margin-top: 0;">📊 Order Detail</h3>
        <p style="color: #D6EAF8;">Explore YTD sales by manufacturer, distributor parent, 
        territory, and category. Drill into individual store performance.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/1_Order_Detail.py", label="Open Order Detail →", use_container_width=True)

with col2:
    st.markdown("""
    <div style="background: linear-gradient(135deg, #148F77 0%, #1ABC9C 100%); 
                padding: 30px; border-radius: 12px; color: white; min-height: 200px;">
        <h3 style="color: white; margin-top: 0;">⚖️ Manufacturer Compare</h3>
        <p style="color: #D5F5E3;">Compare two or more manufacturers side by side — 
        dollars, cases, commission, and monthly trends overlaid.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/2_Manufacturer_Compare.py", label="Open Comparison →", use_container_width=True)

with col3:
    st.markdown("""
    <div style="background: linear-gradient(135deg, #6C3483 0%, #A569BD 100%); 
                padding: 30px; border-radius: 12px; color: white; min-height: 200px;">
        <h3 style="color: white; margin-top: 0;">📅 Period Compare</h3>
        <p style="color: #E8DAEF;">Compare sales across time periods — year over year, 
        month over month, or custom date ranges with change indicators.</p>
    </div>
    """, unsafe_allow_html=True)
    st.page_link("pages/3_Period_Compare.py", label="Open Period Compare →", use_container_width=True)

st.markdown("---")
st.caption("Affinity Insights & Analytics | Powered by Snowflake + Cortex AI")
