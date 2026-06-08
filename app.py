"""
Affinity Insights & Analytics - Landing Page
Sales intelligence hub with navigation to analytics modules.
"""
import streamlit as st
from datetime import datetime

from utils.auth import authenticate_user, get_access_filter, get_access_display
from utils.connection import get_nxt_connection
from utils.data import get_kpis, get_available_years, get_data_freshness, get_declining_accounts

# Page config
st.set_page_config(
    page_title="Affinity Insights & Analytics",
    page_icon="🍴",
    layout="wide",
    initial_sidebar_state="collapsed"
)


def get_snowflake_connection():
    """Get Snowflake connection (delegates to centralized module)."""
    return get_nxt_connection()


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
    # Data freshness badge
    freshness = get_data_freshness(conn)
    if freshness:
        st.markdown(
            f'<div style="background:#1B4F72; color:white; padding:6px 12px; '
            f'border-radius:6px; font-size:12px; margin:8px 0;">'
            f'Data through: <strong>{freshness}</strong></div>',
            unsafe_allow_html=True
        )
    st.markdown("---")
    st.markdown("#### Navigation")
    st.caption("Internal Sales")
    if st.button("Order Detail", use_container_width=True):
        st.switch_page("pages/1_Order_Detail.py")
    if st.button("Manufacturer Compare", use_container_width=True):
        st.switch_page("pages/2_Manufacturer_Compare.py")
    if st.button("Period Compare", use_container_width=True):
        st.switch_page("pages/3_Period_Compare.py")
    st.caption("Partner Data")
    if st.button("Scorecard Analytics", use_container_width=True):
        st.switch_page("pages/4_Scorecard_Analytics.py")
    if st.button("Contract Intelligence", use_container_width=True):
        st.switch_page("pages/5_Contract_Intelligence.py")
    st.caption("Cross-Source")
    if st.button("Reconciliation", use_container_width=True):
        st.switch_page("pages/6_Reconciliation.py")
    if st.button("Sales Call Prep", use_container_width=True):
        st.switch_page("pages/7_Sales_Call_Prep.py")
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

# ─── Declining Accounts Alert ───
declining_df = get_declining_accounts(conn, territory_filter)
if not declining_df.empty:
    st.markdown("---")
    st.markdown("### ⚠ Accounts Needing Attention")
    st.caption("Customers with >20% YoY decline (year-to-date vs same period last year)")
    for _, row in declining_df.head(5).iterrows():
        pct = row["PCT_CHANGE"]
        cy = row["CY_DOLLARS"]
        py = row["PY_DOLLARS"]
        name = row["DISTRIBUTORNAME"]
        st.markdown(
            f'<div style="background:#FFF3E0; border-left:4px solid #E65100; '
            f'padding:10px 15px; margin:5px 0; border-radius:4px;">'
            f'<strong>{name}</strong> — '
            f'<span style="color:#E65100;">{pct:+.1f}%</span> '
            f'<span style="color:#666;">(${cy:,.0f} vs ${py:,.0f} last year)</span>'
            f'</div>',
            unsafe_allow_html=True
        )

# ═══════════════════════════════════════════════════════════════
# NAVIGATION — GROUPED BY DATA SOURCE
# ═══════════════════════════════════════════════════════════════

st.markdown("---")

# ─── Section 1: Internal Sales (NXT) ───
st.markdown("""
<div style="margin-bottom: 8px;">
    <span style="color: #F5921E; font-size: 16px; font-weight: 600; letter-spacing: 1px;">YOUR SALES</span>
    <span style="color: #888; font-size: 12px; margin-left: 8px;">From NXT Internal System</span>
</div>
""", unsafe_allow_html=True)

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #F5921E;">
        <h4 style="color: #F5921E; margin-top: 0;">Order Detail</h4>
        <p style="color: #CCCCCC; font-size: 13px;">YTD sales by manufacturer, distributor, 
        territory. Drill into store-level performance.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_order"):
        st.switch_page("pages/1_Order_Detail.py")

with col2:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #F5921E;">
        <h4 style="color: #F5921E; margin-top: 0;">Manufacturer Compare</h4>
        <p style="color: #CCCCCC; font-size: 13px;">Side-by-side comparison — dollars, cases, 
        commission, monthly trends overlaid.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_compare"):
        st.switch_page("pages/2_Manufacturer_Compare.py")

with col3:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #F5921E;">
        <h4 style="color: #F5921E; margin-top: 0;">Period Compare</h4>
        <p style="color: #CCCCCC; font-size: 13px;">Year-over-year, quarter-over-quarter, or 
        custom date range comparisons.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_period"):
        st.switch_page("pages/3_Period_Compare.py")

st.markdown("")

# ─── Section 2: Partner Data (Manufacturer-Shared) ───
st.markdown("""
<div style="margin-bottom: 8px;">
    <span style="color: #4CAF50; font-size: 16px; font-weight: 600; letter-spacing: 1px;">PARTNER DATA</span>
    <span style="color: #888; font-size: 12px; margin-left: 8px;">Manufacturer-Shared Scorecards & Contracts</span>
</div>
""", unsafe_allow_html=True)

col4, col5 = st.columns(2)

with col4:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #4CAF50;">
        <h4 style="color: #4CAF50; margin-top: 0;">Scorecard Analytics</h4>
        <p style="color: #CCCCCC; font-size: 13px;">57 manufacturer clients — trends, predictions, 
        failing items, category breakdowns, anomaly detection.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_scorecard"):
        st.switch_page("pages/4_Scorecard_Analytics.py")

with col5:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #9C27B0;">
        <h4 style="color: #9C27B0; margin-top: 0;">Contract Intelligence</h4>
        <p style="color: #CCCCCC; font-size: 13px;">Upload contracts, extract commission rates with AI, 
        compare old vs new terms against real sales.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_contracts"):
        st.switch_page("pages/5_Contract_Intelligence.py")

st.markdown("")

# ─── Section 3: Cross-Source Insights ───
st.markdown("""
<div style="margin-bottom: 8px;">
    <span style="color: #2196F3; font-size: 16px; font-weight: 600; letter-spacing: 1px;">CROSS-SOURCE INSIGHTS</span>
    <span style="color: #888; font-size: 12px; margin-left: 8px;">Where Internal Meets Partner Data</span>
</div>
""", unsafe_allow_html=True)

col6, col7 = st.columns(2)

with col6:
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #2196F3;">
        <h4 style="color: #2196F3; margin-top: 0;">Reconciliation</h4>
        <p style="color: #CCCCCC; font-size: 13px;">Compare your internal numbers vs manufacturer 
        scorecard reports. Find gaps, missing orders, and discrepancies.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_recon"):
        st.switch_page("pages/6_Reconciliation.py")

with col7:
    # Sales Call Prep - inline quick action
    st.markdown("""
    <div style="background: #2D2D2D; padding: 24px; border-radius: 10px; 
                color: white; min-height: 160px; border-left: 4px solid #FF9800;">
        <h4 style="color: #FF9800; margin-top: 0;">Sales Call Prep</h4>
        <p style="color: #CCCCCC; font-size: 13px;">Quick customer/manufacturer snapshot — 
        YTD sales, trending direction, top items, last order, commission rate.</p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("Open →", use_container_width=True, key="card_prep"):
        st.switch_page("pages/7_Sales_Call_Prep.py")

st.markdown("---")
st.caption("Affinity Group | Insights & Analytics | Powered by Snowflake + Cortex AI")
