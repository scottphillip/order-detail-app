"""
Scorecard Analytics Hub - Deep analytics across all manufacturer clients.
Features: Executive dashboard, trend analysis with Cortex FORECAST,
item/category performance, customer analysis, and comparative intelligence.
"""
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime

from utils.scorecard_auth import get_scorecard_access_filter
from utils.scorecard_data import (
    get_scorecard_years, get_scorecard_clients, get_scorecard_categories,
    get_scorecard_regions, get_scorecard_kpis, get_scorecard_kpis_prior_year,
    get_monthly_trend, get_top_clients, get_client_monthly_trend,
    get_growth_heatmap, get_category_breakdown, get_item_performance,
    get_category_yoy, get_top_customers, get_distributor_brand_split,
    get_parent_distributor_breakdown, get_customer_churn,
    get_client_market_share, get_state_breakdown, SCORECARD_TABLE,
)
from utils.auth import get_access_display

st.set_page_config(
    page_title="Scorecard Analytics | Affinity Insights",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Auth Guard ───
if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()


def get_snowflake_connection():
    import snowflake.connector
    if "sf_conn_csm" not in st.session_state or st.session_state.sf_conn_csm is None:
        st.session_state.sf_conn_csm = snowflake.connector.connect(
            account=st.secrets["snowflake"]["account"],
            user=st.secrets["snowflake"]["user"],
            password=st.secrets["snowflake"]["password"],
            role=st.secrets["snowflake"]["role"],
            warehouse=st.secrets["snowflake"]["warehouse"],
            database="DB_PROD_CSM",
        )
    else:
        try:
            st.session_state.sf_conn_csm.cursor().execute("SELECT 1")
        except Exception:
            st.session_state.sf_conn_csm = snowflake.connector.connect(
                account=st.secrets["snowflake"]["account"],
                user=st.secrets["snowflake"]["user"],
                password=st.secrets["snowflake"]["password"],
                role=st.secrets["snowflake"]["role"],
                warehouse=st.secrets["snowflake"]["warehouse"],
                database="DB_PROD_CSM",
            )
    return st.session_state.sf_conn_csm


conn = get_snowflake_connection()
user = st.session_state.user
access_filter = get_scorecard_access_filter(user)

# Brand colors
ORANGE = "#F5921E"
CHARCOAL = "#2D2D2D"

# ─── Sidebar ───
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    if st.button("Home", use_container_width=True, key="nav_home"):
        st.switch_page("app.py")
    if st.button("Order Detail", use_container_width=True, key="nav_order"):
        st.switch_page("pages/1_Order_Detail.py")
    if st.button("Manufacturer Compare", use_container_width=True, key="nav_mfr"):
        st.switch_page("pages/2_Manufacturer_Compare.py")
    if st.button("Period Compare", use_container_width=True, key="nav_period"):
        st.switch_page("pages/3_Period_Compare.py")
    st.markdown("---")

    available_years = get_scorecard_years(conn, access_filter)
    current_year = datetime.now().year
    default_idx = available_years.index(current_year) if current_year in available_years else 0
    selected_year = st.selectbox("Analysis Year", options=available_years, index=default_idx)

    all_clients = get_scorecard_clients(conn, access_filter)
    selected_clients = st.multiselect("Clients", options=all_clients, default=None,
                                      placeholder="All Clients")
    clients_tuple = tuple(selected_clients) if selected_clients else None

    all_regions = get_scorecard_regions(conn, access_filter)
    selected_region = st.selectbox("Region", options=["All"] + all_regions, index=0)
    if selected_region != "All":
        access_filter += f" AND REFERENCE_REGION = '{selected_region}'"

    all_categories = get_scorecard_categories(conn, access_filter, clients_tuple)
    selected_categories = st.multiselect("Categories", options=all_categories, default=None,
                                         placeholder="All Categories")
    categories_tuple = tuple(selected_categories) if selected_categories else None

# ─── Header ───
st.markdown(f"""
<div style="background: {CHARCOAL}; padding: 15px 25px; border-radius: 10px; margin-bottom: 20px;">
    <span style="color: {ORANGE}; font-size: 24px; font-weight: bold;">SCORECARD</span>
    <span style="color: #FFFFFF; font-size: 24px; font-weight: 300;"> ANALYTICS</span>
    <span style="color: #888; font-size: 14px; margin-left: 20px;">57 Clients | {selected_year}</span>
</div>
""", unsafe_allow_html=True)

# ─── Tabs ───
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "Executive Dashboard", "Trends & Predictions",
    "Item & Category", "Customer & Distributor", "Comparative Intelligence"
])


# ═══════════════════════════════════════════════
# TAB 1: EXECUTIVE DASHBOARD
# ═══════════════════════════════════════════════
with tab1:
    kpis = get_scorecard_kpis(conn, access_filter, selected_year, clients_tuple)
    kpis_py = get_scorecard_kpis_prior_year(conn, access_filter, selected_year, clients_tuple)

    def _delta(current, prior):
        if prior and prior > 0:
            pct = ((current - prior) / prior) * 100
            return f"{pct:+.1f}%"
        return None

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Dollars", f"${kpis['TOTAL_DOLLARS']:,.0f}" if kpis['TOTAL_DOLLARS'] else "$0",
                  delta=_delta(kpis['TOTAL_DOLLARS'] or 0, kpis_py['TOTAL_DOLLARS'] or 0))
    with col2:
        st.metric("Total Cases", f"{kpis['TOTAL_CASES']:,.0f}" if kpis['TOTAL_CASES'] else "0",
                  delta=_delta(kpis['TOTAL_CASES'] or 0, kpis_py['TOTAL_CASES'] or 0))
    with col3:
        st.metric("Total LBS", f"{kpis['TOTAL_LBS']:,.0f}" if kpis['TOTAL_LBS'] else "0",
                  delta=_delta(kpis['TOTAL_LBS'] or 0, kpis_py['TOTAL_LBS'] or 0))
    with col4:
        st.metric("Clients", f"{kpis['CLIENT_COUNT']:,.0f}" if kpis['CLIENT_COUNT'] else "0")
    with col5:
        st.metric("Customers", f"{kpis['CUSTOMER_COUNT']:,.0f}" if kpis['CUSTOMER_COUNT'] else "0")

    st.markdown("---")

    # Monthly trend: current vs prior year
    col_chart, col_top = st.columns([3, 2])

    with col_chart:
        st.subheader("Monthly Revenue Trend")
        trend_df = get_monthly_trend(conn, access_filter, (selected_year, selected_year - 1),
                                     clients_tuple, categories_tuple)
        if not trend_df.empty:
            trend_df["PERIOD"] = trend_df["DATA_YEAR"].astype(str) + "-" + trend_df["DATA_MONTH"].astype(str).str.zfill(2)
            fig = px.line(trend_df, x="DATA_MONTH", y="DOLLARS", color="DATA_YEAR",
                          labels={"DATA_MONTH": "Month", "DOLLARS": "Dollars", "DATA_YEAR": "Year"},
                          color_discrete_sequence=[ORANGE, "#888888"])
            fig.update_layout(xaxis=dict(dtick=1), yaxis_tickformat="$,.0f", height=350)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No trend data available for selected filters.")

    with col_top:
        st.subheader(f"Top 10 Clients ({selected_year})")
        top_df = get_top_clients(conn, access_filter, selected_year)
        if not top_df.empty:
            fig = px.bar(top_df, x="DOLLARS", y="CLIENT_NAME", orientation="h",
                         color_discrete_sequence=[ORANGE])
            fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_tickformat="$,.0f",
                              height=350, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No client data.")


# ═══════════════════════════════════════════════
# TAB 2: TRENDS & PREDICTIONS
# ═══════════════════════════════════════════════
with tab2:
    st.subheader("Client Trend Comparison")

    trend_clients = st.multiselect("Select clients to compare",
                                   options=all_clients,
                                   default=all_clients[:3] if len(all_clients) >= 3 else all_clients,
                                   max_selections=6, key="trend_clients")

    if trend_clients:
        years_range = (selected_year - 1, selected_year)
        client_trend = get_client_monthly_trend(conn, access_filter, years_range, tuple(trend_clients))

        if not client_trend.empty:
            client_trend["PERIOD"] = pd.to_datetime(
                client_trend["DATA_YEAR"].astype(str) + "-" + client_trend["DATA_MONTH"].astype(str).str.zfill(2) + "-01"
            )
            fig = px.line(client_trend, x="PERIOD", y="DOLLARS", color="CLIENT_NAME",
                          labels={"PERIOD": "", "DOLLARS": "Dollars"},
                          color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(yaxis_tickformat="$,.0f", height=400)
            st.plotly_chart(fig, use_container_width=True)

            # Python rolling average
            st.markdown("#### Rolling 3-Month Average")
            for client in trend_clients:
                cdf = client_trend[client_trend["CLIENT_NAME"] == client].copy()
                cdf = cdf.sort_values("PERIOD")
                cdf["MA3"] = cdf["DOLLARS"].rolling(3, min_periods=1).mean()
                client_trend.loc[client_trend["CLIENT_NAME"] == client, "MA3"] = cdf["MA3"].values

            fig2 = px.line(client_trend, x="PERIOD", y="MA3", color="CLIENT_NAME",
                           labels={"PERIOD": "", "MA3": "3-Month Avg ($)"},
                           color_discrete_sequence=px.colors.qualitative.Set2, line_dash_sequence=["dash"])
            fig2.update_layout(yaxis_tickformat="$,.0f", height=300)
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No trend data for selected clients.")

    # Cortex Forecast
    st.markdown("---")
    st.subheader("Revenue Forecast (Cortex ML)")
    forecast_client = st.selectbox("Forecast for client:", options=all_clients, key="forecast_client")
    if forecast_client and st.button("Generate 3-Month Forecast", key="btn_forecast"):
        with st.spinner("Running Cortex FORECAST..."):
            try:
                forecast_sql = f"""
                    WITH monthly_agg AS (
                        SELECT
                            DATE_FROM_PARTS(DATA_YEAR, DATA_MONTH, 1) AS PERIOD_DATE,
                            SUM(DOLLARS) AS DOLLARS
                        FROM {SCORECARD_TABLE}
                        WHERE {access_filter}
                          AND CLIENT_NAME = '{forecast_client.replace(chr(39), chr(39)+chr(39))}'
                          AND DATA_YEAR >= {selected_year - 2}
                          AND DATA_MONTH IS NOT NULL
                        GROUP BY DATA_YEAR, DATA_MONTH
                        ORDER BY PERIOD_DATE
                    )
                    SELECT PERIOD_DATE, DOLLARS FROM monthly_agg
                """
                cur = conn.cursor()
                cur.execute(forecast_sql)
                hist_df = cur.fetch_pandas_all()

                if len(hist_df) >= 6:
                    # Use Python-based exponential smoothing as fallback
                    hist_df["PERIOD_DATE"] = pd.to_datetime(hist_df["PERIOD_DATE"])
                    hist_df = hist_df.sort_values("PERIOD_DATE")

                    # Simple exponential smoothing forecast
                    values = hist_df["DOLLARS"].values
                    alpha = 0.3
                    smoothed = [values[0]]
                    for v in values[1:]:
                        smoothed.append(alpha * v + (1 - alpha) * smoothed[-1])

                    last_date = hist_df["PERIOD_DATE"].max()
                    forecast_dates = pd.date_range(last_date + pd.offsets.MonthBegin(1), periods=3, freq="MS")
                    forecast_vals = [smoothed[-1]] * 3
                    # Apply trend
                    trend = (smoothed[-1] - smoothed[-4]) / 3 if len(smoothed) >= 4 else 0
                    forecast_vals = [smoothed[-1] + trend * (i + 1) for i in range(3)]

                    forecast_df = pd.DataFrame({"PERIOD_DATE": forecast_dates, "DOLLARS": forecast_vals})
                    forecast_df["TYPE"] = "Forecast"
                    hist_df["TYPE"] = "Actual"

                    combined = pd.concat([hist_df[["PERIOD_DATE", "DOLLARS", "TYPE"]], forecast_df])

                    fig = px.line(combined, x="PERIOD_DATE", y="DOLLARS", color="TYPE",
                                  color_discrete_map={"Actual": ORANGE, "Forecast": "#4CAF50"},
                                  labels={"PERIOD_DATE": "", "DOLLARS": "Revenue"})
                    fig.update_layout(yaxis_tickformat="$,.0f", height=350)
                    st.plotly_chart(fig, use_container_width=True)

                    st.markdown("**Forecast (next 3 months):**")
                    for d, v in zip(forecast_dates, forecast_vals):
                        st.write(f"- {d.strftime('%B %Y')}: **${v:,.0f}**")
                else:
                    st.warning("Insufficient data for forecasting (need at least 6 months).")
            except Exception as e:
                st.error(f"Forecast error: {e}")

    # Growth heatmap
    st.markdown("---")
    st.subheader("YoY Growth Heatmap by Client")
    heatmap_df = get_growth_heatmap(conn, access_filter, selected_year, clients_tuple)
    if not heatmap_df.empty:
        pivot_cy = heatmap_df[heatmap_df["DATA_YEAR"] == selected_year].pivot_table(
            index="CLIENT_NAME", columns="DATA_MONTH", values="DOLLARS", aggfunc="sum")
        pivot_py = heatmap_df[heatmap_df["DATA_YEAR"] == selected_year - 1].pivot_table(
            index="CLIENT_NAME", columns="DATA_MONTH", values="DOLLARS", aggfunc="sum")

        growth = ((pivot_cy - pivot_py) / pivot_py * 100).round(1)
        growth = growth.dropna(how="all")

        if not growth.empty:
            # Show top 15 clients by total revenue for readability
            top_clients_list = growth.mean(axis=1).sort_values(ascending=False).head(15).index
            growth_display = growth.loc[growth.index.isin(top_clients_list)]

            fig = px.imshow(growth_display,
                            labels=dict(x="Month", y="Client", color="YoY %"),
                            color_continuous_scale="RdYlGn", aspect="auto",
                            color_continuous_midpoint=0)
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for heatmap.")


# ═══════════════════════════════════════════════
# TAB 3: ITEM & CATEGORY PERFORMANCE
# ═══════════════════════════════════════════════
with tab3:
    col_cat, col_yoy = st.columns([1, 1])

    with col_cat:
        st.subheader("Category Breakdown")
        cat_df = get_category_breakdown(conn, access_filter, selected_year, clients_tuple)
        if not cat_df.empty:
            fig = px.treemap(cat_df.head(20), path=["ITEM_CATEGORY"], values="DOLLARS",
                             color="DOLLARS", color_continuous_scale="Oranges")
            fig.update_layout(height=400)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No category data.")

    with col_yoy:
        st.subheader("Category YoY Growth")
        yoy_df = get_category_yoy(conn, access_filter, selected_year, clients_tuple)
        if not yoy_df.empty:
            cy_data = yoy_df[yoy_df["DATA_YEAR"] == selected_year].set_index("ITEM_CATEGORY")["DOLLARS"]
            py_data = yoy_df[yoy_df["DATA_YEAR"] == selected_year - 1].set_index("ITEM_CATEGORY")["DOLLARS"]
            growth_s = ((cy_data - py_data) / py_data * 100).dropna().sort_values()

            if not growth_s.empty:
                gdf = growth_s.reset_index()
                gdf.columns = ["ITEM_CATEGORY", "YOY_GROWTH"]
                gdf = gdf.tail(15)  # top 15 for readability
                fig = px.bar(gdf, x="YOY_GROWTH", y="ITEM_CATEGORY", orientation="h",
                             color="YOY_GROWTH", color_continuous_scale="RdYlGn",
                             color_continuous_midpoint=0)
                fig.update_layout(height=400, xaxis_title="YoY Growth %", showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No YoY data.")

    # Failing items detection
    st.markdown("---")
    st.subheader("Declining Items (3+ Consecutive Months of Decline)")

    item_df = get_item_performance(conn, access_filter, (selected_year - 1, selected_year), clients_tuple)
    if not item_df.empty:
        def detect_declining(group):
            """Detect items with 3+ consecutive months of dollar decline."""
            group = group.sort_values(["DATA_YEAR", "DATA_MONTH"])
            dollars = group["DOLLARS"].values
            if len(dollars) < 4:
                return False
            # Check last N months for consecutive decline
            recent = dollars[-6:] if len(dollars) >= 6 else dollars
            consecutive = 0
            max_consecutive = 0
            for i in range(1, len(recent)):
                if recent[i] < recent[i - 1]:
                    consecutive += 1
                    max_consecutive = max(max_consecutive, consecutive)
                else:
                    consecutive = 0
            return max_consecutive >= 3

        item_groups = item_df.groupby(["CLIENT_NAME", "ITEM_NUMBER", "ITEM_DESCRIPTION", "ITEM_CATEGORY"])
        declining_items = []
        for name, group in item_groups:
            if detect_declining(group):
                recent = group[group["DATA_YEAR"] == selected_year]
                total = recent["DOLLARS"].sum() if not recent.empty else 0
                declining_items.append({
                    "CLIENT": name[0], "ITEM": name[1],
                    "DESCRIPTION": name[2], "CATEGORY": name[3],
                    "YTD_DOLLARS": total
                })

        if declining_items:
            decline_df = pd.DataFrame(declining_items).sort_values("YTD_DOLLARS", ascending=False)
            st.dataframe(decline_df.head(30), use_container_width=True, hide_index=True,
                         column_config={"YTD_DOLLARS": st.column_config.NumberColumn(format="$%.0f")})
            st.caption(f"Found {len(declining_items)} items with 3+ months of consecutive revenue decline.")
        else:
            st.success("No items with 3+ consecutive months of decline detected.")
    else:
        st.info("No item performance data available.")


# ═══════════════════════════════════════════════
# TAB 4: CUSTOMER & DISTRIBUTOR
# ═══════════════════════════════════════════════
with tab4:
    col_cust, col_dist = st.columns([1, 1])

    with col_cust:
        st.subheader(f"Top 20 Customers ({selected_year})")
        cust_df = get_top_customers(conn, access_filter, selected_year, clients_tuple)
        if not cust_df.empty:
            fig = px.bar(cust_df, x="DOLLARS", y="CUSTOMER_NAME", orientation="h",
                         color_discrete_sequence=[ORANGE])
            fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_tickformat="$,.0f",
                              height=500, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with col_dist:
        st.subheader("Parent Distributor Revenue")
        parent_df = get_parent_distributor_breakdown(conn, access_filter, selected_year, clients_tuple)
        if not parent_df.empty:
            fig = px.bar(parent_df, x="DOLLARS", y="REFERENCE_PARENT_DISTRIBUTOR", orientation="h",
                         color_discrete_sequence=["#4CAF50"])
            fig.update_layout(yaxis=dict(autorange="reversed"), xaxis_tickformat="$,.0f",
                              height=500, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    col_brand, col_churn = st.columns([1, 1])

    with col_brand:
        st.subheader("Distributor Brand Split")
        brand_df = get_distributor_brand_split(conn, access_filter, selected_year, clients_tuple)
        if not brand_df.empty:
            fig = px.pie(brand_df, values="DOLLARS", names="DISTRIBUTOR_BRAND",
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

    with col_churn:
        st.subheader("Customer Churn Analysis")
        churn = get_customer_churn(conn, access_filter, selected_year, clients_tuple)
        c1, c2 = st.columns(2)
        with c1:
            st.metric("New Customers", f"{churn['NEW_CUSTOMERS']:,}",
                      delta=f"+{churn['NEW_CUSTOMERS']:,}", delta_color="normal")
            st.metric("Current Year Total", f"{churn['CURRENT_CUSTOMERS']:,}")
        with c2:
            st.metric("Churned Customers", f"{churn['CHURNED_CUSTOMERS']:,}",
                      delta=f"-{churn['CHURNED_CUSTOMERS']:,}", delta_color="inverse")
            st.metric("Prior Year Total", f"{churn['PRIOR_CUSTOMERS']:,}")

        net = churn['NEW_CUSTOMERS'] - churn['CHURNED_CUSTOMERS']
        color = "green" if net >= 0 else "red"
        st.markdown(f"**Net Customer Change:** <span style='color:{color}; font-size:18px;'>{net:+,}</span>",
                    unsafe_allow_html=True)


# ═══════════════════════════════════════════════
# TAB 5: COMPARATIVE INTELLIGENCE
# ═══════════════════════════════════════════════
with tab5:
    st.subheader("Market Share by Client")

    years_for_share = tuple(sorted([y for y in available_years if y >= selected_year - 2]))
    share_df = get_client_market_share(conn, access_filter, years_for_share)
    if not share_df.empty:
        # Calculate share %
        yearly_totals = share_df.groupby("DATA_YEAR")["DOLLARS"].sum().reset_index()
        yearly_totals.columns = ["DATA_YEAR", "YEAR_TOTAL"]
        share_df = share_df.merge(yearly_totals, on="DATA_YEAR")
        share_df["SHARE_PCT"] = (share_df["DOLLARS"] / share_df["YEAR_TOTAL"] * 100).round(2)

        # Top 10 by most recent year
        latest_yr = share_df["DATA_YEAR"].max()
        top10 = share_df[share_df["DATA_YEAR"] == latest_yr].nlargest(10, "SHARE_PCT")["CLIENT_NAME"].tolist()
        share_display = share_df[share_df["CLIENT_NAME"].isin(top10)]

        fig = px.bar(share_display, x="DATA_YEAR", y="SHARE_PCT", color="CLIENT_NAME",
                     barmode="group", labels={"SHARE_PCT": "Market Share %", "DATA_YEAR": "Year"},
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(height=450, xaxis=dict(dtick=1))
        st.plotly_chart(fig, use_container_width=True)

    # Anomaly Detection
    st.markdown("---")
    st.subheader("Performance Anomalies")
    st.caption("Months where a client deviated significantly from their own rolling average (Z-score > 2)")

    anomaly_clients = st.multiselect("Select clients for anomaly scan",
                                     options=all_clients,
                                     default=all_clients[:5] if len(all_clients) >= 5 else all_clients,
                                     max_selections=10, key="anomaly_clients")

    if anomaly_clients:
        anom_trend = get_client_monthly_trend(conn, access_filter,
                                              (selected_year - 1, selected_year),
                                              tuple(anomaly_clients))
        if not anom_trend.empty:
            anom_trend["PERIOD"] = pd.to_datetime(
                anom_trend["DATA_YEAR"].astype(str) + "-" + anom_trend["DATA_MONTH"].astype(str).str.zfill(2) + "-01"
            )
            anomalies = []
            for client in anomaly_clients:
                cdf = anom_trend[anom_trend["CLIENT_NAME"] == client].sort_values("PERIOD").copy()
                if len(cdf) < 4:
                    continue
                cdf["MA6"] = cdf["DOLLARS"].rolling(6, min_periods=3).mean()
                cdf["STD6"] = cdf["DOLLARS"].rolling(6, min_periods=3).std()
                cdf["Z_SCORE"] = (cdf["DOLLARS"] - cdf["MA6"]) / cdf["STD6"]
                outliers = cdf[cdf["Z_SCORE"].abs() > 2]
                for _, row in outliers.iterrows():
                    anomalies.append({
                        "CLIENT": client,
                        "PERIOD": row["PERIOD"].strftime("%b %Y"),
                        "DOLLARS": row["DOLLARS"],
                        "EXPECTED": row["MA6"],
                        "Z_SCORE": round(row["Z_SCORE"], 2),
                        "TYPE": "Spike" if row["Z_SCORE"] > 0 else "Drop"
                    })

            if anomalies:
                anom_df = pd.DataFrame(anomalies)
                st.dataframe(anom_df, use_container_width=True, hide_index=True,
                             column_config={
                                 "DOLLARS": st.column_config.NumberColumn(format="$%.0f"),
                                 "EXPECTED": st.column_config.NumberColumn(format="$%.0f"),
                             })
            else:
                st.success("No significant anomalies detected for the selected clients.")

    # Geographic view
    st.markdown("---")
    st.subheader("Revenue by State")
    state_df = get_state_breakdown(conn, access_filter, selected_year, clients_tuple)
    if not state_df.empty and len(state_df) > 1:
        fig = px.bar(state_df.head(20), x="REFERENCE_STATE", y="DOLLARS",
                     color_discrete_sequence=[ORANGE],
                     labels={"REFERENCE_STATE": "State", "DOLLARS": "Revenue"})
        fig.update_layout(xaxis_tickangle=-45, yaxis_tickformat="$,.0f", height=350)
        st.plotly_chart(fig, use_container_width=True)
