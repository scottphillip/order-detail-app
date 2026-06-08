"""
Contract Intelligence - Upload, parse, and compare manufacturer commission contracts.
Features: Contract library, rate viewer, and new-vs-old contract comparison with
commission projections based on actual historical sales data.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, date

from utils.auth import get_access_filter, get_access_display
from utils.connection import get_nxt_connection
from utils.contracts import (
    upload_contract_file, extract_rates_with_ai, save_extracted_rates,
    get_contracts, get_contract_rates, get_contract_manufacturers,
    get_historical_sales, calculate_commission, compare_contracts,
    CONTRACTS_TABLE, RATES_TABLE,
)
from utils.export import excel_download_button

st.set_page_config(
    page_title="Contract Intelligence | Affinity Insights",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Auth Guard ───
if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()


def get_snowflake_connection():
    """Get Snowflake connection (delegates to centralized module)."""
    return get_nxt_connection()


conn = get_snowflake_connection()
user = st.session_state.user
territory_filter = get_access_filter(user)

# Header
st.markdown("""
<div style="background: #2D2D2D; padding: 12px 20px; border-radius: 8px; margin-bottom: 15px;">
    <span style="color: #F5921E; font-size: 18px; font-weight: bold;">CONTRACT INTELLIGENCE</span>
    <span style="color: #AAAAAA; font-size: 13px; margin-left: 12px;">Upload, parse, and compare manufacturer contracts</span>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    if st.button("← Back to Home", use_container_width=True):
        st.switch_page("app.py")

# ─── Tabs ───
tab1, tab2, tab3 = st.tabs(["📁 Contract Library", "📊 Rate Viewer", "⚖️ Compare Contracts"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: CONTRACT LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    st.markdown("### Upload & Manage Contracts")
    st.caption("Upload manufacturer contracts (PDF, Excel, Word). AI will extract commission rates automatically.")

    col_upload, col_list = st.columns([1, 2])

    with col_upload:
        st.markdown("#### Upload New Contract")

        with st.form("upload_contract", clear_on_submit=True):
            uploaded_file = st.file_uploader(
                "Contract file",
                type=["pdf", "xlsx", "xls", "docx", "doc"],
                help="Supported: PDF, Excel, Word"
            )
            manufacturer = st.text_input("Manufacturer name", placeholder="e.g., Dole Packaged Foods LLC")
            contract_name = st.text_input("Contract name", placeholder="e.g., 2026 Commission Agreement")
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                effective_date = st.date_input("Effective date", value=None)
            with col_d2:
                expiration_date = st.date_input("Expiration date", value=None)

            submitted = st.form_submit_button("Upload & Extract Rates", type="primary",
                                              use_container_width=True)

            if submitted and uploaded_file and manufacturer:
                with st.spinner("Uploading and extracting..."):
                    try:
                        contract_id = upload_contract_file(
                            conn, uploaded_file, manufacturer, contract_name or uploaded_file.name,
                            effective_date, expiration_date, user.get("EMAIL", "unknown")
                        )
                        st.session_state["last_contract_id"] = contract_id
                        st.session_state["last_manufacturer"] = manufacturer

                        # Extract rates with AI
                        contracts_df = get_contracts(conn, manufacturer)
                        if not contracts_df.empty:
                            latest = contracts_df.iloc[0]
                            # Get extracted text for rate parsing
                            text_query = f"SELECT EXTRACTED_TEXT FROM {CONTRACTS_TABLE} WHERE CONTRACT_ID = {contract_id}"
                            text_df = conn.cursor().execute(text_query).fetch_pandas_all()
                            if not text_df.empty and text_df.iloc[0]["EXTRACTED_TEXT"]:
                                extracted_text = text_df.iloc[0]["EXTRACTED_TEXT"]
                                rates = extract_rates_with_ai(conn, extracted_text, manufacturer)
                                if rates:
                                    st.session_state["pending_rates"] = rates
                                    st.success(f"Contract uploaded! Found {len(rates)} rate(s). Review below.")
                                else:
                                    st.warning("Contract uploaded but no rates auto-detected. You can add rates manually.")
                            else:
                                st.warning("Contract uploaded but text extraction had issues. Add rates manually.")

                        st.cache_data.clear()
                    except Exception as e:
                        st.error(f"Upload failed: {str(e)[:300]}")
            elif submitted:
                st.warning("Please select a file and enter the manufacturer name.")

    # Show pending rates for confirmation
    if "pending_rates" in st.session_state and st.session_state.pending_rates:
        st.markdown("---")
        st.markdown("#### Review Extracted Rates")
        st.caption("AI extracted these rates. Confirm or edit before saving.")

        rates_df = pd.DataFrame(st.session_state.pending_rates)
        edited_rates = st.data_editor(rates_df, num_rows="dynamic", use_container_width=True)

        col_save, col_discard = st.columns(2)
        with col_save:
            if st.button("Save Rates", type="primary", use_container_width=True):
                rates_to_save = edited_rates.to_dict("records")
                save_extracted_rates(
                    conn,
                    st.session_state.get("last_contract_id", 0),
                    st.session_state.get("last_manufacturer", ""),
                    rates_to_save,
                    effective_date
                )
                del st.session_state["pending_rates"]
                st.cache_data.clear()
                st.success("Rates saved!")
                st.rerun()
        with col_discard:
            if st.button("Discard", use_container_width=True):
                del st.session_state["pending_rates"]
                st.rerun()

    with col_list:
        st.markdown("#### Contract Library")
        contracts_df = get_contracts(conn)
        if not contracts_df.empty:
            st.dataframe(
                contracts_df[["MANUFACTURER", "CONTRACT_NAME", "EFFECTIVE_DATE",
                              "EXPIRATION_DATE", "STATUS", "UPLOADED_BY"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "MANUFACTURER": "Manufacturer",
                    "CONTRACT_NAME": "Contract",
                    "EFFECTIVE_DATE": st.column_config.DateColumn("Effective"),
                    "EXPIRATION_DATE": st.column_config.DateColumn("Expires"),
                    "STATUS": "Status",
                    "UPLOADED_BY": "Uploaded By",
                }
            )
        else:
            st.info("No contracts uploaded yet. Use the form on the left to upload your first contract.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: RATE VIEWER
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    st.markdown("### Commission Rates by Manufacturer")
    st.caption("View stored rates and compare against implied rates from actual order data.")

    mfr_list = get_contract_manufacturers(conn)

    if mfr_list:
        selected_mfr = st.selectbox("Select Manufacturer", mfr_list, key="rate_viewer_mfr")

        col_stored, col_actual = st.columns(2)

        with col_stored:
            st.markdown("#### Contracted Rates")
            rates_df = get_contract_rates(conn, manufacturer=selected_mfr)
            if not rates_df.empty:
                display_df = rates_df[["CATEGORY", "RATE_TYPE", "RATE_VALUE", "EFFECTIVE_DATE", "NOTES"]].copy()
                display_df.columns = ["Category", "Type", "Rate", "Effective", "Notes"]
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("No stored rates for this manufacturer.")

        with col_actual:
            st.markdown("#### Actual Implied Rates (from Orders)")
            st.caption("Calculated from actual commission ÷ sales in the last 12 months")
            historical = get_historical_sales(conn, selected_mfr, territory_filter, months=12)
            if not historical.empty:
                historical["IMPLIED_RATE"] = (
                    historical["ACTUAL_COMMISSION"] / historical["TOTAL_DOLLARS"] * 100
                ).round(2)
                display_hist = historical[["CATEGORY", "TOTAL_DOLLARS", "ACTUAL_COMMISSION", "IMPLIED_RATE"]].copy()
                display_hist.columns = ["Category", "Sales $", "Commission $", "Implied Rate %"]
                display_hist["Sales $"] = display_hist["Sales $"].apply(lambda x: f"${x:,.0f}")
                display_hist["Commission $"] = display_hist["Commission $"].apply(lambda x: f"${x:,.0f}")
                st.dataframe(display_hist, use_container_width=True, hide_index=True)
            else:
                st.info("No order data found for this manufacturer in your territory.")

        # Discrepancy analysis
        if not rates_df.empty and not historical.empty:
            st.markdown("---")
            st.markdown("#### Rate Discrepancies")
            st.caption("Categories where contracted rate differs from what's actually being paid")

            # Compare
            rate_lookup = {}
            for _, r in rates_df.iterrows():
                cat = (r["CATEGORY"] or "ALL").upper()
                rate_lookup[cat] = float(r["RATE_VALUE"])

            flat_rate = rate_lookup.get("ALL", None)
            discrepancies = []
            for _, row in historical.iterrows():
                cat = (row["CATEGORY"] or "Unknown").upper()
                contracted = rate_lookup.get(cat, flat_rate)
                implied = row.get("IMPLIED_RATE", 0) if pd.notnull(row.get("IMPLIED_RATE")) else 0
                if contracted is not None and abs(contracted - implied) > 0.1:
                    discrepancies.append({
                        "Category": row["CATEGORY"],
                        "Contracted %": contracted,
                        "Actual %": implied,
                        "Difference": round(implied - contracted, 2),
                    })

            if discrepancies:
                disc_df = pd.DataFrame(discrepancies)
                st.dataframe(disc_df, use_container_width=True, hide_index=True)
            else:
                st.success("No significant discrepancies found.")
    else:
        st.info("No contracts uploaded yet. Upload a contract in the Contract Library tab to get started.")

    # Manual rate entry section
    st.markdown("---")
    st.markdown("#### Add Rates Manually")
    st.caption("Enter rates directly if you don't have a digital contract to upload.")

    with st.form("manual_rates"):
        # Get all manufacturers from order data for the dropdown
        all_mfr_query = f"""
            SELECT DISTINCT MANUFACTURERNAME 
            FROM {ORDER_VIEW} 
            WHERE {territory_filter} AND MANUFACTURERNAME IS NOT NULL
            ORDER BY MANUFACTURERNAME
        """
        all_mfr_df = conn.cursor().execute(all_mfr_query).fetch_pandas_all()
        all_manufacturers = all_mfr_df["MANUFACTURERNAME"].tolist() if not all_mfr_df.empty else []

        manual_mfr = st.selectbox("Manufacturer", all_manufacturers, key="manual_mfr")
        manual_category = st.text_input("Category (or 'ALL' for flat rate)", value="ALL")
        col_rt, col_rv = st.columns(2)
        with col_rt:
            manual_rate_type = st.selectbox("Rate Type", ["PERCENTAGE", "FLAT_PER_CASE", "FLAT_PER_LB"])
        with col_rv:
            manual_rate_value = st.number_input("Rate Value", min_value=0.0, max_value=100.0,
                                                value=2.0, step=0.25)
        manual_eff_date = st.date_input("Effective Date", value=date.today(), key="manual_eff")

        if st.form_submit_button("Save Rate", use_container_width=True):
            # Create a contract record if none exists for this manufacturer
            existing = get_contracts(conn, manual_mfr)
            if existing.empty:
                safe_mfr = manual_mfr.replace("'", "''")
                conn.cursor().execute(f"""
                    INSERT INTO {CONTRACTS_TABLE} (MANUFACTURER, CONTRACT_NAME, STATUS, UPLOADED_BY)
                    VALUES ('{safe_mfr}', 'Manual Entry', 'ACTIVE', '{user.get("EMAIL", "unknown")}')
                """)
                contract_id_df = conn.cursor().execute(
                    f"SELECT MAX(CONTRACT_ID) AS CID FROM {CONTRACTS_TABLE}"
                ).fetch_pandas_all()
                contract_id = int(contract_id_df.iloc[0]["CID"])
            else:
                contract_id = int(existing.iloc[0]["CONTRACT_ID"])

            save_extracted_rates(conn, contract_id, manual_mfr, [{
                "category": manual_category,
                "rate_type": manual_rate_type,
                "rate_value": manual_rate_value,
                "volume_min": None,
                "volume_max": None,
                "notes": "Manual entry",
            }], manual_eff_date)
            st.cache_data.clear()
            st.success(f"Rate saved: {manual_mfr} / {manual_category} = {manual_rate_value}%")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: COMPARE CONTRACTS
# ═══════════════════════════════════════════════════════════════════════════════

with tab3:
    st.markdown("### Commission Impact Comparison")
    st.caption("Compare old vs new contract rates using real historical sales to project commission changes.")

    # Get manufacturers that have both contracts and order data
    all_mfr_query = f"""
        SELECT DISTINCT MANUFACTURERNAME 
        FROM {ORDER_VIEW} 
        WHERE {territory_filter} 
          AND MANUFACTURERNAME IS NOT NULL
          AND TRY_TO_DOUBLE(COMM) > 0
        ORDER BY MANUFACTURERNAME
    """
    compare_mfr_df = conn.cursor().execute(all_mfr_query).fetch_pandas_all()
    compare_manufacturers = compare_mfr_df["MANUFACTURERNAME"].tolist() if not compare_mfr_df.empty else []

    if compare_manufacturers:
        col_config, col_whatif = st.columns([2, 1])

        with col_config:
            compare_mfr = st.selectbox("Manufacturer", compare_manufacturers, key="compare_mfr")
            period_option = st.selectbox("Sales Period", [
                "Rolling 12 Months",
                "Rolling 6 Months",
                "Year to Date (2026)",
                "Full Year 2025",
            ])

        with col_whatif:
            st.markdown("#### What-If Scenario")
            volume_change = st.slider("Sales Volume Change", min_value=-50, max_value=50,
                                      value=0, step=5, format="%d%%",
                                      help="Adjust assumed sales volume to model growth/decline")
            volume_multiplier = 1.0 + (volume_change / 100)

        # Determine months for period
        months_map = {
            "Rolling 12 Months": 12,
            "Rolling 6 Months": 6,
            "Year to Date (2026)": 6,  # approximate
            "Full Year 2025": 12,
        }
        period_months = months_map.get(period_option, 12)

        # Get historical sales
        historical = get_historical_sales(conn, compare_mfr, territory_filter, months=period_months)

        if not historical.empty:
            st.markdown("---")

            # Old rates: from stored contract or implied from data
            stored_rates = get_contract_rates(conn, manufacturer=compare_mfr)
            if not stored_rates.empty:
                old_rates = stored_rates.to_dict("records")
                # Normalize keys for the calculate function
                old_rates = [{
                    "category": r.get("CATEGORY", "ALL"),
                    "rate_type": r.get("RATE_TYPE", "PERCENTAGE"),
                    "rate_value": float(r.get("RATE_VALUE", 0)),
                    "volume_min": r.get("VOLUME_TIER_MIN"),
                    "volume_max": r.get("VOLUME_TIER_MAX"),
                } for r in old_rates]
                rate_source = "Stored Contract"
            else:
                # Use implied rates from actual data
                old_rates = []
                for _, row in historical.iterrows():
                    if row["TOTAL_DOLLARS"] and row["TOTAL_DOLLARS"] > 0:
                        implied = (row["ACTUAL_COMMISSION"] / row["TOTAL_DOLLARS"]) * 100
                        old_rates.append({
                            "category": row["CATEGORY"],
                            "rate_type": "PERCENTAGE",
                            "rate_value": round(implied, 2),
                            "volume_min": None,
                            "volume_max": None,
                        })
                rate_source = "Implied from Actual Orders"

            st.markdown(f"**Current Rates Source:** {rate_source}")

            # New rates input
            st.markdown("#### Enter New Proposed Rates")
            st.caption("Edit the rate values below to see projected impact.")

            # Create editable dataframe from old rates
            new_rates_default = []
            for r in old_rates:
                new_rates_default.append({
                    "Category": r.get("category", "ALL"),
                    "Rate Type": r.get("rate_type", "PERCENTAGE"),
                    "New Rate": float(r.get("rate_value", 0)),
                })

            if new_rates_default:
                new_rates_df = pd.DataFrame(new_rates_default)
                edited_new = st.data_editor(
                    new_rates_df, num_rows="dynamic", use_container_width=True,
                    column_config={
                        "Category": st.column_config.TextColumn("Category"),
                        "Rate Type": st.column_config.SelectboxColumn(
                            "Rate Type", options=["PERCENTAGE", "FLAT_PER_CASE", "FLAT_PER_LB"]
                        ),
                        "New Rate": st.column_config.NumberColumn("New Rate", min_value=0, max_value=100, step=0.25),
                    }
                )

                # Convert edited rates to comparison format
                new_rates = [{
                    "category": row["Category"],
                    "rate_type": row["Rate Type"],
                    "rate_value": row["New Rate"],
                    "volume_min": None,
                    "volume_max": None,
                } for _, row in edited_new.iterrows()]

                # Run comparison
                comparison = compare_contracts(historical, old_rates, new_rates, volume_multiplier)

                if not comparison.empty:
                    st.markdown("---")
                    st.markdown("#### Projected Commission Impact")

                    if volume_change != 0:
                        st.info(f"Projections assume sales volume changes by {volume_change:+d}%")

                    # Summary KPIs
                    total_old = comparison["Old Commission"].sum()
                    total_new = comparison["New Commission"].sum()
                    total_delta = total_new - total_old

                    kpi1, kpi2, kpi3 = st.columns(3)
                    kpi1.metric("Old Commission (projected)", f"${total_old:,.0f}")
                    kpi2.metric("New Commission (projected)", f"${total_new:,.0f}")
                    kpi3.metric("Net Change", f"${total_delta:+,.0f}",
                                delta=f"{(total_delta/total_old*100):+.1f}%" if total_old > 0 else "N/A")

                    # Detail table
                    display_comp = comparison[["Category", "Sales $", "Old Rate %", "New Rate %",
                                               "Old Commission", "New Commission", "Delta $"]].copy()
                    display_comp["Sales $"] = display_comp["Sales $"].apply(lambda x: f"${x:,.0f}" if pd.notnull(x) else "$0")
                    display_comp["Old Commission"] = display_comp["Old Commission"].apply(lambda x: f"${x:,.0f}" if pd.notnull(x) else "$0")
                    display_comp["New Commission"] = display_comp["New Commission"].apply(lambda x: f"${x:,.0f}" if pd.notnull(x) else "$0")
                    display_comp["Delta $"] = display_comp["Delta $"].apply(
                        lambda x: f"${x:+,.0f}" if pd.notnull(x) else "$0"
                    )
                    display_comp["Old Rate %"] = display_comp["Old Rate %"].apply(
                        lambda x: f"{x:.2f}%" if pd.notnull(x) else "—"
                    )
                    display_comp["New Rate %"] = display_comp["New Rate %"].apply(
                        lambda x: f"{x:.2f}%" if pd.notnull(x) else "—"
                    )
                    st.dataframe(display_comp, use_container_width=True, hide_index=True)

                    # Chart
                    chart_data = comparison[["Category", "Old Commission", "New Commission"]].head(10)
                    chart_melted = chart_data.melt(id_vars="Category", var_name="Contract", value_name="Commission")
                    fig = px.bar(chart_melted, x="Category", y="Commission", color="Contract",
                                 barmode="group", color_discrete_map={
                                     "Old Commission": "#888888", "New Commission": "#F5921E"
                                 })
                    fig.update_layout(height=350, xaxis_tickangle=-45,
                                     yaxis_tickformat="$,.0f", xaxis_title="", yaxis_title="Commission ($)")
                    st.plotly_chart(fig, use_container_width=True)

                    # Export
                    excel_download_button(comparison, f"contract_comparison_{compare_mfr}",
                                          "Download Comparison Report")
            else:
                st.info("No rate data available. Upload a contract or enter rates manually in the Rate Viewer tab.")
        else:
            st.warning(f"No order data found for {compare_mfr} in your territory for the selected period.")
    else:
        st.info("No manufacturers with commission data found in your territory.")

st.markdown("---")
st.caption("Contract Intelligence | Affinity Group | Powered by Snowflake + Cortex AI")
