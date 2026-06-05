"""
Scorecard Analytics Hub - Deep analytics across all manufacturer clients.
Features: Executive dashboard, trend analysis with forecasting,
item/category performance, customer analysis, comparative intelligence,
and Cortex Analyst chatbot.
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
    get_client_market_share, get_state_breakdown, get_max_data_month,
    get_client_month_discrepancies,
    SCORECARD_TABLE,
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
GREEN = "#4CAF50"

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

    # Metric Toggle - Cases is the default
    metric_choice = st.radio(
        "Primary Metric",
        options=["Cases", "Dollars", "LBS"],
        index=0,
        horizontal=True,
        key="metric_toggle"
    )
    METRIC_COL = {"Cases": "CASES", "Dollars": "DOLLARS", "LBS": "LBS"}[metric_choice]
    METRIC_FMT = {"Cases": ",.0f", "Dollars": "$,.0f", "LBS": ",.0f"}[metric_choice]
    METRIC_PREFIX = {"Cases": "", "Dollars": "$", "LBS": ""}[metric_choice]

    st.markdown("---")

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


# ─── Helper: format metric value ───
def fmt_metric(val):
    """Format a metric value based on the selected metric."""
    if val is None:
        return f"{METRIC_PREFIX}0"
    if METRIC_COL == "DOLLARS":
        return f"${val:,.0f}"
    return f"{val:,.0f}"


# ─── Header ───
st.markdown(f"""
<div style="background: {CHARCOAL}; padding: 12px 25px; border-radius: 10px; margin-bottom: 15px;">
    <span style="color: {ORANGE}; font-size: 22px; font-weight: bold;">SCORECARD</span>
    <span style="color: #FFFFFF; font-size: 22px; font-weight: 300;"> ANALYTICS</span>
    <span style="color: #888; font-size: 13px; margin-left: 20px;">57 Clients | {selected_year} | Metric: {metric_choice}</span>
</div>
""", unsafe_allow_html=True)

# ─── Tabs ───
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "Executive Dashboard", "Trends & Predictions",
    "Item & Category", "Customer & Distributor", "Comparative Intelligence",
    "Ask Data"
])


# ═══════════════════════════════════════════════
# TAB 1: EXECUTIVE DASHBOARD
# ═══════════════════════════════════════════════
with tab1:
    max_month = get_max_data_month(conn, access_filter, selected_year, clients_tuple)
    kpis = get_scorecard_kpis(conn, access_filter, selected_year, clients_tuple, max_month)
    kpis_py = get_scorecard_kpis_prior_year(conn, access_filter, selected_year, clients_tuple, max_month)

    def _delta(current, prior):
        if prior and prior > 0:
            pct = ((current - prior) / prior) * 100
            return f"{pct:+.1f}%"
        return None

    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    compare_label = f"Jan\u2013{month_names[max_month-1]} {selected_year} vs Same Period {selected_year - 1}"
    st.caption(compare_label)

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("Total Cases", f"{kpis['TOTAL_CASES']:,.0f}" if kpis['TOTAL_CASES'] else "0",
                  delta=_delta(kpis['TOTAL_CASES'] or 0, kpis_py['TOTAL_CASES'] or 0))
    with col2:
        st.metric("Total Dollars", f"${kpis['TOTAL_DOLLARS']:,.0f}" if kpis['TOTAL_DOLLARS'] else "$0",
                  delta=_delta(kpis['TOTAL_DOLLARS'] or 0, kpis_py['TOTAL_DOLLARS'] or 0))
    with col3:
        st.metric("Total LBS", f"{kpis['TOTAL_LBS']:,.0f}" if kpis['TOTAL_LBS'] else "0",
                  delta=_delta(kpis['TOTAL_LBS'] or 0, kpis_py['TOTAL_LBS'] or 0))
    with col4:
        st.metric("Clients", f"{kpis['CLIENT_COUNT']:,.0f}" if kpis['CLIENT_COUNT'] else "0")
    with col5:
        st.metric("Customers", f"{kpis['CUSTOMER_COUNT']:,.0f}" if kpis['CUSTOMER_COUNT'] else "0")

    # Monthly trend: current vs prior year
    col_chart, col_top = st.columns([3, 2])

    with col_chart:
        st.subheader(f"Monthly {metric_choice} Trend")
        trend_df = get_monthly_trend(conn, access_filter, (selected_year, selected_year - 1),
                                     clients_tuple, categories_tuple)
        if not trend_df.empty:
            trend_df = trend_df[trend_df["DATA_MONTH"] <= max_month]
            fig = px.line(trend_df, x="DATA_MONTH", y=METRIC_COL, color="DATA_YEAR",
                          labels={"DATA_MONTH": "Month", METRIC_COL: metric_choice, "DATA_YEAR": "Year"},
                          color_discrete_sequence=[ORANGE, "#888888"])
            fig.update_layout(
                xaxis=dict(dtick=1, tickvals=list(range(1, max_month + 1)),
                           ticktext=month_names[:max_month]),
                yaxis_tickformat=METRIC_FMT, height=340,
                margin=dict(t=10, b=30)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No trend data available for selected filters.")

    with col_top:
        st.subheader(f"Top 10 Clients ({selected_year})")
        top_df = get_top_clients(conn, access_filter, selected_year)
        if not top_df.empty:
            fig = px.bar(top_df, x=METRIC_COL, y="CLIENT_NAME", orientation="h",
                         color_discrete_sequence=[ORANGE])
            fig.update_layout(
                yaxis=dict(autorange="reversed"),
                xaxis_tickformat=METRIC_FMT,
                height=340, showlegend=False,
                margin=dict(t=10, b=30)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No client data.")

    # Client Discrepancy Alerts
    st.markdown("---")
    st.subheader("Client Month-to-Month Discrepancies")
    st.caption("Clients with >40% YoY change in any single month (flagging data gaps or unusual swings)")
    disc_df = get_client_month_discrepancies(conn, access_filter, selected_year, max_month, clients_tuple)
    if not disc_df.empty:
        month_names_short = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        disc_df["MONTH"] = disc_df["DATA_MONTH"].apply(
            lambda m: month_names_short[int(m) - 1] if pd.notnull(m) else "?"
        )
        disc_df["CHANGE"] = disc_df["YOY_PCT"].apply(
            lambda x: f"+{x:.0f}%" if x > 0 else f"{x:.0f}%"
        )
        display_cols = ["CLIENT_NAME", "MONTH", "CY_CASES", "PY_CASES", "CHANGE"]
        st.dataframe(
            disc_df[display_cols].head(20),
            use_container_width=True, hide_index=True,
            column_config={
                "CLIENT_NAME": "Client",
                "MONTH": "Month",
                "CY_CASES": st.column_config.NumberColumn(f"{selected_year} Cases", format="%.0f"),
                "PY_CASES": st.column_config.NumberColumn(f"{selected_year-1} Cases", format="%.0f"),
                "CHANGE": "YoY Change",
            }
        )
    else:
        st.success("No significant month-to-month discrepancies detected.")


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
                client_trend["DATA_YEAR"].astype(str) + "-" +
                client_trend["DATA_MONTH"].astype(str).str.zfill(2) + "-01"
            )
            fig = px.line(client_trend, x="PERIOD", y=METRIC_COL, color="CLIENT_NAME",
                          labels={"PERIOD": "", METRIC_COL: metric_choice},
                          color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(yaxis_tickformat=METRIC_FMT, height=380,
                              margin=dict(t=10, b=30))
            st.plotly_chart(fig, use_container_width=True)

            # Rolling average
            st.markdown(f"**Rolling 3-Month Average ({metric_choice})**")
            for client in trend_clients:
                cdf = client_trend[client_trend["CLIENT_NAME"] == client].copy()
                cdf = cdf.sort_values("PERIOD")
                cdf["MA3"] = cdf[METRIC_COL].rolling(3, min_periods=1).mean()
                client_trend.loc[client_trend["CLIENT_NAME"] == client, "MA3"] = cdf["MA3"].values

            fig2 = px.line(client_trend, x="PERIOD", y="MA3", color="CLIENT_NAME",
                           labels={"PERIOD": "", "MA3": f"3-Mo Avg ({metric_choice})"},
                           color_discrete_sequence=px.colors.qualitative.Set2,
                           line_dash_sequence=["dash"])
            fig2.update_layout(yaxis_tickformat=METRIC_FMT, height=280,
                               margin=dict(t=10, b=30))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No trend data for selected clients.")

    # Forecast Section
    st.markdown("---")
    st.subheader(f"{metric_choice} Forecast (Exponential Smoothing)")
    forecast_client = st.selectbox("Forecast for client:", options=all_clients, key="forecast_client")
    if forecast_client and st.button("Generate 3-Month Forecast", key="btn_forecast"):
        with st.spinner("Calculating forecast..."):
            try:
                escaped_client = forecast_client.replace(chr(39), chr(39)+chr(39))
                forecast_sql = f"""
                    WITH monthly_agg AS (
                        SELECT
                            DATE_FROM_PARTS(DATA_YEAR, DATA_MONTH, 1) AS PERIOD_DATE,
                            SUM({METRIC_COL}) AS METRIC_VALUE
                        FROM {SCORECARD_TABLE}
                        WHERE {access_filter}
                          AND CLIENT_NAME = '{escaped_client}'
                          AND DATA_YEAR >= {selected_year - 2}
                          AND DATA_MONTH IS NOT NULL
                        GROUP BY DATA_YEAR, DATA_MONTH
                        ORDER BY PERIOD_DATE
                    )
                    SELECT PERIOD_DATE, METRIC_VALUE FROM monthly_agg
                """
                cur = conn.cursor()
                cur.execute(forecast_sql)
                hist_df = cur.fetch_pandas_all()

                if len(hist_df) >= 6:
                    hist_df["PERIOD_DATE"] = pd.to_datetime(hist_df["PERIOD_DATE"])
                    hist_df = hist_df.sort_values("PERIOD_DATE")

                    # Exponential smoothing
                    values = hist_df["METRIC_VALUE"].astype(float).values
                    alpha = 0.3
                    smoothed = [values[0]]
                    for v in values[1:]:
                        smoothed.append(alpha * v + (1 - alpha) * smoothed[-1])

                    last_date = hist_df["PERIOD_DATE"].max()
                    forecast_dates = pd.date_range(last_date + pd.offsets.MonthBegin(1), periods=3, freq="MS")
                    trend = (smoothed[-1] - smoothed[-4]) / 3 if len(smoothed) >= 4 else 0
                    forecast_vals = [smoothed[-1] + trend * (i + 1) for i in range(3)]

                    # Build combined df - bridge last actual point into forecast for connected line
                    hist_df["TYPE"] = "Actual"
                    hist_df = hist_df.rename(columns={"METRIC_VALUE": "VALUE"})

                    # Bridge point: last actual appears in both series
                    bridge_row = pd.DataFrame({
                        "PERIOD_DATE": [last_date],
                        "VALUE": [float(values[-1])],
                        "TYPE": ["Forecast"]
                    })
                    forecast_df = pd.DataFrame({
                        "PERIOD_DATE": forecast_dates,
                        "VALUE": forecast_vals,
                        "TYPE": ["Forecast"] * 3
                    })
                    forecast_df = pd.concat([bridge_row, forecast_df], ignore_index=True)

                    combined = pd.concat([hist_df[["PERIOD_DATE", "VALUE", "TYPE"]], forecast_df],
                                         ignore_index=True)

                    fig = px.line(combined, x="PERIOD_DATE", y="VALUE", color="TYPE",
                                  color_discrete_map={"Actual": ORANGE, "Forecast": GREEN},
                                  labels={"PERIOD_DATE": "", "VALUE": metric_choice})
                    fig.update_traces(selector=dict(name="Forecast"), line=dict(dash="dash"))
                    fig.update_layout(yaxis_tickformat=METRIC_FMT, height=350,
                                      margin=dict(t=10, b=30))
                    st.plotly_chart(fig, use_container_width=True)

                    st.markdown(f"**Forecast (next 3 months):**")
                    for d, v in zip(forecast_dates, forecast_vals):
                        st.write(f"- {d.strftime('%B %Y')}: **{fmt_metric(v)}**")
                else:
                    st.warning("Insufficient data for forecasting (need at least 6 months).")
            except Exception as e:
                st.error(f"Forecast error: {e}")

    # Growth heatmap
    st.markdown("---")
    st.subheader(f"YoY {metric_choice} Growth Heatmap by Client")
    heatmap_df = get_growth_heatmap(conn, access_filter, selected_year, clients_tuple)
    if not heatmap_df.empty:
        pivot_cy = heatmap_df[heatmap_df["DATA_YEAR"] == selected_year].pivot_table(
            index="CLIENT_NAME", columns="DATA_MONTH", values="DOLLARS", aggfunc="sum")
        pivot_py = heatmap_df[heatmap_df["DATA_YEAR"] == selected_year - 1].pivot_table(
            index="CLIENT_NAME", columns="DATA_MONTH", values="DOLLARS", aggfunc="sum")

        growth = ((pivot_cy - pivot_py) / pivot_py * 100).round(1)
        growth = growth.dropna(how="all")

        if not growth.empty:
            top_clients_list = growth.mean(axis=1).sort_values(ascending=False).head(15).index
            growth_display = growth.loc[growth.index.isin(top_clients_list)]

            fig = px.imshow(growth_display,
                            labels=dict(x="Month", y="Client", color="YoY %"),
                            color_continuous_scale="RdYlGn", aspect="auto",
                            color_continuous_midpoint=0)
            fig.update_layout(height=450, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Insufficient data for heatmap.")


# ═══════════════════════════════════════════════
# TAB 3: ITEM & CATEGORY PERFORMANCE
# ═══════════════════════════════════════════════
with tab3:
    st.subheader("Category Performance")

    # Manufacturer/Client filter for this tab
    tab3_clients = st.multiselect(
        "Filter by Manufacturer",
        options=all_clients,
        default=None,
        placeholder="All Manufacturers",
        key="tab3_client_filter"
    )
    tab3_clients_tuple = tuple(tab3_clients) if tab3_clients else clients_tuple

    cat_df = get_category_breakdown(conn, access_filter, selected_year, tab3_clients_tuple)
    if not cat_df.empty and METRIC_COL in cat_df.columns:
        col_cat, col_yoy = st.columns([1, 1])

        with col_cat:
            st.markdown(f"**Category Breakdown by {metric_choice}**")
            # Use bar chart instead of treemap for reliability
            display_df = cat_df.head(15).copy()
            display_df = display_df.sort_values(METRIC_COL, ascending=True)
            fig = px.bar(display_df, x=METRIC_COL, y="ITEM_CATEGORY", orientation="h",
                         color=METRIC_COL, color_continuous_scale="Oranges")
            fig.update_layout(
                height=400, showlegend=False,
                xaxis_tickformat=METRIC_FMT,
                yaxis_title="",
                margin=dict(t=10, b=10, l=10)
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_yoy:
            st.markdown("**Category YoY Growth**")
            yoy_df = get_category_yoy(conn, access_filter, selected_year, tab3_clients_tuple)
            if not yoy_df.empty:
                cy_data = yoy_df[yoy_df["DATA_YEAR"] == selected_year].set_index("ITEM_CATEGORY")["CASES"]
                py_data = yoy_df[yoy_df["DATA_YEAR"] == selected_year - 1].set_index("ITEM_CATEGORY")["CASES"]
                growth_s = ((cy_data - py_data) / py_data * 100).dropna().sort_values()

                if not growth_s.empty:
                    gdf = growth_s.reset_index()
                    gdf.columns = ["ITEM_CATEGORY", "YOY_GROWTH"]
                    gdf = gdf.tail(15)
                    fig = px.bar(gdf, x="YOY_GROWTH", y="ITEM_CATEGORY", orientation="h",
                                 color="YOY_GROWTH", color_continuous_scale="RdYlGn",
                                 color_continuous_midpoint=0)
                    fig.update_layout(height=400, xaxis_title="YoY Growth %",
                                      showlegend=False, margin=dict(t=10, b=10, l=10))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No YoY comparison data available.")
            else:
                st.info("No YoY data.")
    else:
        st.info("No category data available for selected filters.")

    # Failing items detection
    st.markdown("---")
    st.subheader(f"Declining Items (3+ Consecutive Months of {metric_choice} Decline)")

    item_df = get_item_performance(conn, access_filter, (selected_year - 1, selected_year), tab3_clients_tuple)
    if not item_df.empty:
        def detect_declining(group):
            """Detect items with 3+ consecutive months of decline."""
            group = group.sort_values(["DATA_YEAR", "DATA_MONTH"])
            vals = group["CASES"].values
            if len(vals) < 4:
                return False
            recent = vals[-6:] if len(vals) >= 6 else vals
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
                total = recent["CASES"].sum() if not recent.empty else 0
                declining_items.append({
                    "CLIENT": name[0], "ITEM": name[1],
                    "DESCRIPTION": name[2], "CATEGORY": name[3],
                    "YTD_CASES": total
                })

        if declining_items:
            decline_df = pd.DataFrame(declining_items).sort_values("YTD_CASES", ascending=False)
            st.dataframe(decline_df.head(30), use_container_width=True, hide_index=True,
                         column_config={"YTD_CASES": st.column_config.NumberColumn(format="%.0f")})
            st.caption(f"Found {len(declining_items)} items with 3+ months of consecutive decline.")
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
            fig = px.bar(cust_df, x=METRIC_COL, y="CUSTOMER_DISPLAY_NAME", orientation="h",
                         color_discrete_sequence=[ORANGE])
            fig.update_layout(
                yaxis=dict(autorange="reversed"), xaxis_tickformat=METRIC_FMT,
                height=480, showlegend=False,
                yaxis_title="", margin=dict(t=10, b=10)
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_dist:
        st.subheader("Parent Distributor Revenue")
        parent_df = get_parent_distributor_breakdown(conn, access_filter, selected_year, clients_tuple)
        if not parent_df.empty:
            fig = px.bar(parent_df, x=METRIC_COL, y="REFERENCE_PARENT_DISTRIBUTOR", orientation="h",
                         color_discrete_sequence=[GREEN])
            fig.update_layout(
                yaxis=dict(autorange="reversed"), xaxis_tickformat=METRIC_FMT,
                height=480, showlegend=False,
                yaxis_title="", margin=dict(t=10, b=10)
            )
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    col_brand, col_churn = st.columns([1, 1])

    with col_brand:
        st.subheader("Distributor Brand Split")
        brand_df = get_distributor_brand_split(conn, access_filter, selected_year, clients_tuple)
        if not brand_df.empty:
            fig = px.pie(brand_df, values=METRIC_COL, names="DISTRIBUTOR_BRAND",
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(height=340, margin=dict(t=10, b=10))
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
        yearly_totals = share_df.groupby("DATA_YEAR")["DOLLARS"].sum().reset_index()
        yearly_totals.columns = ["DATA_YEAR", "YEAR_TOTAL"]
        share_df = share_df.merge(yearly_totals, on="DATA_YEAR")
        share_df["SHARE_PCT"] = (share_df["DOLLARS"] / share_df["YEAR_TOTAL"] * 100).round(2)

        latest_yr = share_df["DATA_YEAR"].max()
        top10 = share_df[share_df["DATA_YEAR"] == latest_yr].nlargest(10, "SHARE_PCT")["CLIENT_NAME"].tolist()
        share_display = share_df[share_df["CLIENT_NAME"].isin(top10)]

        fig = px.bar(share_display, x="DATA_YEAR", y="SHARE_PCT", color="CLIENT_NAME",
                     barmode="group", labels={"SHARE_PCT": "Market Share %", "DATA_YEAR": "Year"},
                     color_discrete_sequence=px.colors.qualitative.Set2)
        fig.update_layout(height=420, xaxis=dict(dtick=1), margin=dict(t=10, b=30))
        st.plotly_chart(fig, use_container_width=True)

    # Anomaly Detection
    st.markdown("---")
    st.subheader("Performance Anomalies")
    st.caption(f"Months where a client's {metric_choice.lower()} deviated significantly from rolling average (Z-score > 2)")

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
                anom_trend["DATA_YEAR"].astype(str) + "-" +
                anom_trend["DATA_MONTH"].astype(str).str.zfill(2) + "-01"
            )
            anomalies = []
            for client in anomaly_clients:
                cdf = anom_trend[anom_trend["CLIENT_NAME"] == client].sort_values("PERIOD").copy()
                if len(cdf) < 4:
                    continue
                cdf["MA6"] = cdf[METRIC_COL].rolling(6, min_periods=3).mean()
                cdf["STD6"] = cdf[METRIC_COL].rolling(6, min_periods=3).std()
                cdf["Z_SCORE"] = (cdf[METRIC_COL] - cdf["MA6"]) / cdf["STD6"]
                outliers = cdf[cdf["Z_SCORE"].abs() > 2]
                for _, row in outliers.iterrows():
                    anomalies.append({
                        "CLIENT": client,
                        "PERIOD": row["PERIOD"].strftime("%b %Y"),
                        metric_choice.upper(): row[METRIC_COL],
                        "EXPECTED": row["MA6"],
                        "Z_SCORE": round(row["Z_SCORE"], 2),
                        "TYPE": "Spike" if row["Z_SCORE"] > 0 else "Drop"
                    })

            if anomalies:
                anom_df = pd.DataFrame(anomalies)
                st.dataframe(anom_df, use_container_width=True, hide_index=True)
            else:
                st.success("No significant anomalies detected for the selected clients.")

    # Geographic view
    st.markdown("---")
    st.subheader(f"{metric_choice} by State")
    state_df = get_state_breakdown(conn, access_filter, selected_year, clients_tuple)
    if not state_df.empty and len(state_df) > 1:
        fig = px.bar(state_df.head(20), x="REFERENCE_STATE", y=METRIC_COL,
                     color_discrete_sequence=[ORANGE],
                     labels={"REFERENCE_STATE": "State", METRIC_COL: metric_choice})
        fig.update_layout(xaxis_tickangle=-45, yaxis_tickformat=METRIC_FMT,
                          height=340, margin=dict(t=10, b=30))
        st.plotly_chart(fig, use_container_width=True)


# ═══════════════════════════════════════════════
# TAB 6: ASK DATA (Cortex Analyst Chatbot)
# ═══════════════════════════════════════════════
with tab6:
    st.subheader("Ask Questions About Your Data")
    st.caption("Powered by Snowflake Cortex | Type or click 🎤 to speak (Chrome/Edge)")

    # Initialize chat history
    if "scorecard_chat" not in st.session_state:
        st.session_state.scorecard_chat = []

    # Voice input section
    import streamlit.components.v1 as components

    voice_col, info_col = st.columns([1, 5])
    with voice_col:
        voice_clicked = st.button("🎤 Speak", key="voice_btn", use_container_width=True)
    with info_col:
        if voice_clicked or st.session_state.get("voice_active", False):
            st.session_state["voice_active"] = True
            st.markdown(
                '<span style="color:#e53e3e; font-size:13px;">● Listening... speak your question</span>',
                unsafe_allow_html=True)

    # Voice recognition component (renders when voice is active)
    voice_question = None
    if st.session_state.get("voice_active", False):
        components.html("""
        <div id="voice-status" style="font-family:sans-serif; font-size:13px; color:#666; padding:4px 0;">
            <span id="vtext">Initializing...</span>
        </div>
        <script>
        (function() {
            const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SR) {
                document.getElementById('vtext').textContent = 'Not supported - use Chrome or Edge';
                return;
            }
            const rec = new SR();
            rec.continuous = false;
            rec.interimResults = true;
            rec.lang = 'en-US';
            rec.onstart = function() {
                document.getElementById('vtext').textContent = 'Listening...';
            };
            rec.onresult = function(event) {
                let t = '';
                let done = false;
                for (let i = event.resultIndex; i < event.results.length; i++) {
                    t += event.results[i][0].transcript;
                    if (event.results[i].isFinal) done = true;
                }
                document.getElementById('vtext').textContent = t;
                if (done) {
                    document.getElementById('vtext').innerHTML =
                        '<span style="color:#4CAF50">&#10003;</span> ' + t;
                    const url = new URL(window.parent.location);
                    url.searchParams.set('voice_q', encodeURIComponent(t));
                    window.parent.history.replaceState({}, '', url);
                    setTimeout(function() { window.parent.location.reload(); }, 600);
                }
            };
            rec.onerror = function(e) {
                document.getElementById('vtext').textContent = 'Error: ' + e.error;
            };
            rec.start();
        })();
        </script>
        """, height=30)

        # Check for voice transcript in query params
        query_params = st.query_params
        if "voice_q" in query_params:
            voice_question = query_params["voice_q"]
            # URL-decode if needed
            from urllib.parse import unquote
            voice_question = unquote(voice_question)
            st.session_state["voice_active"] = False
            del st.query_params["voice_q"]

    # Display chat history
    for msg in st.session_state.scorecard_chat:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if "dataframe" in msg and msg["dataframe"] is not None:
                st.dataframe(msg["dataframe"], use_container_width=True, hide_index=True)
            if "sql" in msg and msg["sql"]:
                with st.expander("View SQL"):
                    st.code(msg["sql"], language="sql")

    # Chat input (keyboard or voice)
    typed_question = st.chat_input("Ask a question about scorecard data...")
    user_question = voice_question or typed_question

    if user_question:
        # Add user message
        st.session_state.scorecard_chat.append({"role": "user", "content": user_question})
        with st.chat_message("user"):
            st.markdown(user_question)

        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Analyzing..."):
                try:
                    escaped_q = user_question.replace("'", "''")
                    # Use Cortex Complete to generate SQL against the scorecard table
                    analyst_sql = f"""
                        SELECT SNOWFLAKE.CORTEX.COMPLETE(
                            'claude-4-sonnet',
                            CONCAT(
                                'You are a SQL expert for Snowflake. Generate a SQL query to answer this question: ',
                                '{escaped_q}',
                                '. Use table DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT. ',
                                'Key columns: CLIENT_NAME, REFERENCE_CUSTOMER_NAME, REFERENCE_PARENT_DISTRIBUTOR, ',
                                'ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY, DATA_YEAR, DATA_MONTH, ',
                                'CASES (integer units sold), DOLLARS (revenue), LBS (weight shipped), ',
                                'REFERENCE_REGION, REFERENCE_LOCAL_MARKET, REFERENCE_STATE, DISTRIBUTOR_BRAND, ',
                                'SALES_REP, BRAND, SUB_CATEGORY. ',
                                'DATA_YEAR is numeric (e.g. 2025, 2026). DATA_MONTH is numeric 1-12. ',
                                'Return ONLY the SQL query with no explanation, no markdown code fences. ',
                                'Always limit results to 50 rows unless counting/aggregating. ',
                                'Round DOLLARS to 2 decimals. Format nicely with aliases.'
                            )
                        ) AS GENERATED_SQL
                    """
                    cur = conn.cursor()
                    cur.execute(analyst_sql)
                    result = cur.fetch_pandas_all()

                    if result.empty:
                        response_msg = "I couldn't generate a response. Try rephrasing your question."
                        st.markdown(response_msg)
                        st.session_state.scorecard_chat.append({
                            "role": "assistant", "content": response_msg
                        })
                    else:
                        generated_sql = result.iloc[0]["GENERATED_SQL"].strip()
                        # Clean markdown code fences if present
                        if generated_sql.startswith("```"):
                            lines = generated_sql.split("\n")
                            lines = [l for l in lines if not l.strip().startswith("```")]
                            generated_sql = "\n".join(lines).strip()

                        # Execute the generated SQL
                        try:
                            df_result = conn.cursor().execute(generated_sql).fetch_pandas_all()
                            if df_result.empty:
                                response_msg = "The query returned no results. Try adjusting your question."
                                st.markdown(response_msg)
                                st.session_state.scorecard_chat.append({
                                    "role": "assistant", "content": response_msg,
                                    "sql": generated_sql
                                })
                            else:
                                response_msg = f"Found **{len(df_result)} rows**:"
                                st.markdown(response_msg)
                                st.dataframe(df_result, use_container_width=True, hide_index=True)
                                with st.expander("View SQL"):
                                    st.code(generated_sql, language="sql")

                                st.session_state.scorecard_chat.append({
                                    "role": "assistant", "content": response_msg,
                                    "dataframe": df_result,
                                    "sql": generated_sql
                                })
                        except Exception as sql_err:
                            err_msg = f"Query execution error: {str(sql_err)[:200]}\n\nTry rephrasing your question."
                            st.error(err_msg)
                            with st.expander("View attempted SQL"):
                                st.code(generated_sql, language="sql")
                            st.session_state.scorecard_chat.append({
                                "role": "assistant", "content": err_msg,
                                "sql": generated_sql
                            })

                except Exception as e:
                    error_msg = f"Error: {str(e)[:300]}"
                    st.error(error_msg)
                    st.session_state.scorecard_chat.append({
                        "role": "assistant", "content": error_msg
                    })

    # Example questions
    if not st.session_state.scorecard_chat:
        st.markdown("**Example questions you can ask:**")
        examples = [
            "What are the top 10 clients by cases this year?",
            "Show monthly cases trend for 2026 vs 2025",
            "Which categories grew the most year over year?",
            "What customers buy from the most clients?",
            "Show me declining items by cases in the Southwest region",
            "What is the total dollars and cases by region for 2026?"
        ]
        for ex in examples:
            st.markdown(f"- _{ex}_")

# ═══════════════════════════════════════════════
# FLOATING CHATBOT WIDGET (bottom-right corner)
# ═══════════════════════════════════════════════
from utils.chatbot_widget import render_floating_chatbot
render_floating_chatbot(conn)
