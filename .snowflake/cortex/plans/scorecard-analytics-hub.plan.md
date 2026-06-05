# Plan: Scorecard Analytics Hub

## Overview

Add a new **"Scorecard Analytics"** page to the Affinity Insights & Analytics Streamlit app. This page reads from `DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT` (6.4M rows, 57 clients, 78 columns) and provides deep analytical capabilities that don't exist in the current Order Detail pages.

## Data Source

```
DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT
```

Key measures: `DOLLARS`, `CASES`, `LBS`, `STACKED_CASES`
Key dimensions: `CLIENT_NAME`, `MFR_CODE`, `CUSTOMER_NAME`, `ITEM_NUMBER`, `ITEM_DESCRIPTION`, `ITEM_CATEGORY`, `SUB_CATEGORY`, `SEGMENT`, `BRAND`, `REFERENCE_REGION`, `REFERENCE_LOCAL_MARKET`, `REFERENCE_PARENT_DISTRIBUTOR`, `DISTRIBUTOR_BRAND`, `DATA_MONTH`, `DATA_YEAR`
Budget fields: `FY_NET_SALES_BUDGET`, `FY_CASES_BUDGET`, `FY_POUNDS_BUDGET`, `BUD_POUNDS`

## Access Control

Same tiered access as existing pages:
- **Full**: sees all data (`1=1`)
- **Department**: filtered by `REFERENCE_REGION` matching department code (e.g., `ANE` → `Affinity Group Northeast`)
- **Territory**: filtered by `REFERENCE_LOCAL_MARKET` matching `OFFICE_LOCATION`

Map existing department/office to scorecard regions:
- `ANE` → `Affinity Group Northeast`
- `ASE` → `Affinity Group Southeast`  
- `ASW` → `Affinity Group Southwest`
- `AMW` → `Affinity Group Midwest`
- `ACE` → `Affinity Group Midwest` (Central)
- Local market: match `OFFICE_LOCATION` text against `REFERENCE_LOCAL_MARKET` (e.g., "Metro NY" → `ANE - Metro NY`)

## Page Structure: `pages/4_Scorecard_Analytics.py`

### Sidebar Filters
- Client/Manufacturer (multi-select from `CLIENT_NAME`)
- Year selector (for context year)
- Region filter (from `REFERENCE_REGION`)
- Category filter (from `ITEM_CATEGORY`)
- Customer filter (from `CUSTOMER_NAME`)

### Tab Layout (5 analytics tabs)

#### Tab 1: Executive Dashboard
- KPI cards: Total Dollars, Cases, LBS for selected period
- YoY growth % (current year vs prior year)
- Top 10 clients by revenue (bar chart)
- Monthly trend line (current vs prior year overlay)
- Budget vs Actual gauges (where budget data exists)

#### Tab 2: Trend Analysis & Predictions
- Monthly time series by client or category (line chart with multiple series)
- **Cortex FORECAST**: 3-month forward projection on dollars/cases
- Seasonality detection: highlight months that consistently over/underperform
- Growth rate heatmap: client x month showing MoM growth %
- **Python**: Rolling averages, exponential smoothing trend lines

#### Tab 3: Item & Category Performance
- Item-level drill-down table with sparkline trends
- **Failing item detection** (Python): items with 3+ consecutive months of decline
- Category breakdown pie/treemap (dollars by ITEM_CATEGORY)
- Category growth comparison (bar chart: YoY % change per category)
- Discontinued item flagging (`PROD_DISCONTINUED_DATE` is not null)
- DOT vs NON-DOT split analysis (`REFERENCE_DOT_OTHER`)

#### Tab 4: Customer & Distributor Analysis  
- Top/bottom customers by revenue with YoY comparison
- Customer concentration risk (what % of revenue comes from top 5 customers)
- Parent distributor breakdown (branded vs manufacturer branded from `DISTRIBUTOR_BRAND`)
- New vs churned customers (appeared/disappeared this year vs last)
- Geographic heatmap by state (`REFERENCE_STATE`)

#### Tab 5: Comparative Intelligence
- Cross-client comparison (select 2-5 clients, compare trends)
- Market share shifts (client's % of total portfolio over time)
- Peer benchmarking: how does Client X compare to portfolio average growth
- Anomaly detection: months where a client's performance deviates significantly from their norm

## New Files

### `pages/4_Scorecard_Analytics.py`
Main page file with tab structure, filters, and visualizations.

### `utils/scorecard_data.py`
Data query layer for the scorecard BI export table:
- `get_scorecard_kpis()` — aggregate KPIs
- `get_scorecard_monthly_trend()` — monthly time series
- `get_client_rankings()` — top/bottom clients
- `get_item_performance()` — item-level drill-down with trend detection
- `get_category_breakdown()` — category aggregation
- `get_customer_analysis()` — customer concentration and churn
- `get_forecast_data()` — Cortex FORECAST wrapper
- `get_failing_items()` — Python decline detection logic
- `get_anomalies()` — statistical anomaly flagging

### `utils/scorecard_auth.py`
Access control adapter mapping existing user tiers to scorecard data filters using `REFERENCE_REGION` and `REFERENCE_LOCAL_MARKET` instead of `TERRITORYNAME`.

## Technical Approach

### Performance (6.4M rows)
- All queries use aggregations pushed to Snowflake (no full table pulls)
- Aggressive use of `@st.cache_data(ttl=600)` for 10-min caching
- Client/year filters applied in SQL WHERE clauses before aggregation
- For forecasting: aggregate to monthly grain first, then call Cortex

### Cortex ML Integration
```sql
-- Forecast example (run on pre-aggregated monthly data)
SELECT * FROM TABLE(
    SNOWFLAKE.ML.FORECAST(
        INPUT_DATA => SYSTEM$REFERENCE('VIEW', 'monthly_agg_view'),
        TIMESTAMP_COLNAME => 'PERIOD_DATE',
        TARGET_COLNAME => 'DOLLARS',
        CONFIG_OBJECT => {'prediction_interval': 0.95}
    )
);
```

### Python Analytics (in-app)
- Failing items: 3+ month consecutive decline in cases or dollars
- Rolling averages: 3-month and 6-month MA
- Anomaly flagging: Z-score > 2 from client's own rolling mean
- Growth rates: MoM and YoY calculations

### Visualization Library
- **Plotly Express** (consistent with existing pages): line charts, bar charts, treemaps, heatmaps
- **Plotly GO** for dual-axis charts (dollars + cases overlay)
- Streamlit native `st.metric` for KPI cards with delta indicators

## Navigation Integration
- Add "Scorecard Analytics" button to all existing page sidebars
- Add card on landing page (app.py) pointing to the new page
- Icon: chart/analytics themed

## Deployment
- Same Streamlit Community Cloud deployment
- No new secrets needed (uses same Snowflake connection)
- Database context: `DB_PROD_CSM` for queries (different from existing `DB_NXT`)
