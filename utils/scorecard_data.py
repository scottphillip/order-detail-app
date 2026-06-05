"""
Data query layer for Scorecard Analytics.
All queries hit DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT
with aggregation pushed to Snowflake for performance (6.4M rows).
"""
import pandas as pd
import streamlit as st

SCORECARD_TABLE = "DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT"


def _run(conn, sql: str) -> pd.DataFrame:
    """Execute SQL and return a pandas DataFrame."""
    cur = conn.cursor()
    cur.execute(sql)
    return cur.fetch_pandas_all()


# ─────────────────────────────────────────────
# Filter Options
# ─────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_scorecard_years(_conn, access_filter: str) -> list:
    sql = f"""
        SELECT DISTINCT DATA_YEAR
        FROM {SCORECARD_TABLE}
        WHERE {access_filter} AND DATA_YEAR IS NOT NULL
        ORDER BY DATA_YEAR DESC
    """
    df = _run(_conn, sql)
    return df["DATA_YEAR"].tolist() if not df.empty else []


@st.cache_data(ttl=600)
def get_scorecard_clients(_conn, access_filter: str) -> list:
    sql = f"""
        SELECT DISTINCT CLIENT_NAME
        FROM {SCORECARD_TABLE}
        WHERE {access_filter} AND CLIENT_NAME IS NOT NULL
        ORDER BY CLIENT_NAME
    """
    df = _run(_conn, sql)
    return df["CLIENT_NAME"].tolist() if not df.empty else []


@st.cache_data(ttl=600)
def get_scorecard_categories(_conn, access_filter: str, clients: tuple = None) -> list:
    where = access_filter
    if clients:
        cl = ", ".join([f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in clients])
        where += f" AND CLIENT_NAME IN ({cl})"
    sql = f"""
        SELECT DISTINCT ITEM_CATEGORY
        FROM {SCORECARD_TABLE}
        WHERE {where} AND ITEM_CATEGORY IS NOT NULL AND TRIM(ITEM_CATEGORY) != ''
        ORDER BY ITEM_CATEGORY
    """
    df = _run(_conn, sql)
    return df["ITEM_CATEGORY"].tolist() if not df.empty else []


@st.cache_data(ttl=600)
def get_scorecard_regions(_conn, access_filter: str) -> list:
    sql = f"""
        SELECT DISTINCT REFERENCE_REGION
        FROM {SCORECARD_TABLE}
        WHERE {access_filter} AND REFERENCE_REGION IS NOT NULL
        ORDER BY REFERENCE_REGION
    """
    df = _run(_conn, sql)
    return df["REFERENCE_REGION"].tolist() if not df.empty else []


# ─────────────────────────────────────────────
# WHERE builder
# ─────────────────────────────────────────────

def _build_scorecard_where(access_filter: str, years: list = None,
                           clients: list = None, categories: list = None,
                           region: str = None, customer: str = None) -> str:
    clauses = [access_filter]
    if years:
        yr_list = ", ".join(str(y) for y in years)
        clauses.append(f"DATA_YEAR IN ({yr_list})")
    if clients:
        cl = ", ".join([f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in clients])
        clauses.append(f"CLIENT_NAME IN ({cl})")
    if categories:
        ct = ", ".join([f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in categories])
        clauses.append(f"ITEM_CATEGORY IN ({ct})")
    if region:
        clauses.append(f"REFERENCE_REGION = '{region.replace(chr(39), chr(39)+chr(39))}'")
    if customer:
        clauses.append(f"CUSTOMER_NAME LIKE '%{customer.replace(chr(39), chr(39)+chr(39))}%'")
    return " AND ".join(clauses)


# ─────────────────────────────────────────────
# Executive Dashboard
# ─────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_max_data_month(_conn, access_filter: str, year: int, clients: tuple = None) -> int:
    """Get the last COMPLETE month for fair YoY comparison.
    
    A month is considered complete if it has at least 70% of the client count
    of the peak month that year. This avoids comparing partial months
    (e.g. only 2 clients reported in June vs 50+ in prior months).
    """
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    sql = f"""
        WITH monthly_clients AS (
            SELECT DATA_MONTH, COUNT(DISTINCT CLIENT_NAME) AS CLIENT_COUNT
            FROM {SCORECARD_TABLE}
            WHERE {where} AND DATA_MONTH IS NOT NULL
            GROUP BY DATA_MONTH
        ),
        peak AS (
            SELECT MAX(CLIENT_COUNT) AS PEAK_CLIENTS FROM monthly_clients
        )
        SELECT MAX(mc.DATA_MONTH) AS MAX_MONTH
        FROM monthly_clients mc, peak p
        WHERE mc.CLIENT_COUNT >= p.PEAK_CLIENTS * 0.7
    """
    df = _run(_conn, sql)
    if df.empty or df.iloc[0]["MAX_MONTH"] is None:
        return 12
    return int(df.iloc[0]["MAX_MONTH"])


@st.cache_data(ttl=600)
def get_scorecard_kpis(_conn, access_filter: str, year: int,
                       clients: tuple = None, max_month: int = None) -> dict:
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    if max_month:
        where += f" AND DATA_MONTH <= {max_month}"
    sql = f"""
        SELECT
            SUM(DOLLARS) AS TOTAL_DOLLARS,
            SUM(CASES) AS TOTAL_CASES,
            SUM(LBS) AS TOTAL_LBS,
            COUNT(DISTINCT CLIENT_NAME) AS CLIENT_COUNT,
            COUNT(DISTINCT REFERENCE_CUSTOMER_NAME) AS CUSTOMER_COUNT
        FROM {SCORECARD_TABLE}
        WHERE {where}
    """
    df = _run(_conn, sql)
    if df.empty:
        return {"TOTAL_DOLLARS": 0, "TOTAL_CASES": 0, "TOTAL_LBS": 0,
                "CLIENT_COUNT": 0, "CUSTOMER_COUNT": 0}
    return df.iloc[0].to_dict()


@st.cache_data(ttl=600)
def get_scorecard_kpis_prior_year(_conn, access_filter: str, year: int,
                                  clients: tuple = None, max_month: int = None) -> dict:
    return get_scorecard_kpis(_conn, access_filter, year - 1, clients, max_month)


@st.cache_data(ttl=600)
def get_monthly_trend(_conn, access_filter: str, years: tuple, clients: tuple = None,
                      categories: tuple = None) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=list(years),
                                   clients=list(clients) if clients else None,
                                   categories=list(categories) if categories else None)
    sql = f"""
        SELECT DATA_YEAR, DATA_MONTH,
            SUM(DOLLARS) AS DOLLARS,
            SUM(CASES) AS CASES,
            SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND DATA_MONTH IS NOT NULL
        GROUP BY DATA_YEAR, DATA_MONTH
        ORDER BY DATA_YEAR, DATA_MONTH
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_top_clients(_conn, access_filter: str, year: int, limit: int = 10) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=[year])
    sql = f"""
        SELECT CLIENT_NAME, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES, SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where}
        GROUP BY CLIENT_NAME
        ORDER BY DOLLARS DESC
        LIMIT {limit}
    """
    return _run(_conn, sql)


# ─────────────────────────────────────────────
# Trend Analysis
# ─────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_client_monthly_trend(_conn, access_filter: str, years: tuple,
                             clients: tuple) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=list(years), clients=list(clients))
    sql = f"""
        SELECT CLIENT_NAME, DATA_YEAR, DATA_MONTH,
            SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES, SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND DATA_MONTH IS NOT NULL
        GROUP BY CLIENT_NAME, DATA_YEAR, DATA_MONTH
        ORDER BY CLIENT_NAME, DATA_YEAR, DATA_MONTH
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_growth_heatmap(_conn, access_filter: str, year: int, clients: tuple = None) -> pd.DataFrame:
    """MoM growth % by client for a given year."""
    yrs = [year - 1, year]
    where = _build_scorecard_where(access_filter, years=yrs,
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT CLIENT_NAME, DATA_YEAR, DATA_MONTH, SUM(DOLLARS) AS DOLLARS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND DATA_MONTH IS NOT NULL
        GROUP BY CLIENT_NAME, DATA_YEAR, DATA_MONTH
        ORDER BY CLIENT_NAME, DATA_YEAR, DATA_MONTH
    """
    return _run(_conn, sql)


# ─────────────────────────────────────────────
# Item & Category Performance
# ─────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_category_breakdown(_conn, access_filter: str, year: int,
                           clients: tuple = None) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT ITEM_CATEGORY, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES, SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND ITEM_CATEGORY IS NOT NULL AND TRIM(ITEM_CATEGORY) != ''
        GROUP BY ITEM_CATEGORY
        ORDER BY DOLLARS DESC
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_item_performance(_conn, access_filter: str, years: tuple,
                         clients: tuple = None, limit: int = 200) -> pd.DataFrame:
    """Monthly item-level data for trend/decline detection."""
    where = _build_scorecard_where(access_filter, years=list(years),
                                   clients=list(clients) if clients else None)
    sql = f"""
        WITH item_monthly AS (
            SELECT CLIENT_NAME, ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY,
                DATA_YEAR, DATA_MONTH,
                SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES
            FROM {SCORECARD_TABLE}
            WHERE {where} AND DATA_MONTH IS NOT NULL AND ITEM_NUMBER IS NOT NULL
            GROUP BY CLIENT_NAME, ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY, DATA_YEAR, DATA_MONTH
        ),
        item_totals AS (
            SELECT CLIENT_NAME, ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY,
                SUM(DOLLARS) AS TOTAL_DOLLARS
            FROM item_monthly
            WHERE DATA_YEAR = (SELECT MAX(DATA_YEAR) FROM item_monthly)
            GROUP BY CLIENT_NAME, ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY
            ORDER BY TOTAL_DOLLARS DESC
            LIMIT {limit}
        )
        SELECT m.*
        FROM item_monthly m
        INNER JOIN item_totals t
            ON m.CLIENT_NAME = t.CLIENT_NAME AND m.ITEM_NUMBER = t.ITEM_NUMBER
        ORDER BY m.CLIENT_NAME, m.ITEM_NUMBER, m.DATA_YEAR, m.DATA_MONTH
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_category_yoy(_conn, access_filter: str, year: int,
                     clients: tuple = None) -> pd.DataFrame:
    """YoY comparison by category."""
    yrs = [year - 1, year]
    where = _build_scorecard_where(access_filter, years=yrs,
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT ITEM_CATEGORY, DATA_YEAR, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES, SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND ITEM_CATEGORY IS NOT NULL AND TRIM(ITEM_CATEGORY) != ''
        GROUP BY ITEM_CATEGORY, DATA_YEAR
        ORDER BY ITEM_CATEGORY, DATA_YEAR
    """
    return _run(_conn, sql)


# ─────────────────────────────────────────────
# Customer & Distributor Analysis
# ─────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_top_customers(_conn, access_filter: str, year: int,
                      clients: tuple = None, limit: int = 20) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT REFERENCE_CUSTOMER_NAME, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES,
            SUM(LBS) AS LBS, COUNT(DISTINCT CLIENT_NAME) AS CLIENTS_SERVED
        FROM {SCORECARD_TABLE}
        WHERE {where} AND REFERENCE_CUSTOMER_NAME IS NOT NULL AND TRIM(REFERENCE_CUSTOMER_NAME) != ''
        GROUP BY REFERENCE_CUSTOMER_NAME
        ORDER BY DOLLARS DESC
        LIMIT {limit}
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_distributor_brand_split(_conn, access_filter: str, year: int,
                                clients: tuple = None) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT DISTRIBUTOR_BRAND, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES, SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND DISTRIBUTOR_BRAND IS NOT NULL
        GROUP BY DISTRIBUTOR_BRAND
        ORDER BY DOLLARS DESC
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_parent_distributor_breakdown(_conn, access_filter: str, year: int,
                                     clients: tuple = None, limit: int = 15) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT REFERENCE_PARENT_DISTRIBUTOR, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES,
            SUM(LBS) AS LBS, COUNT(DISTINCT REFERENCE_CUSTOMER_NAME) AS CUSTOMER_COUNT
        FROM {SCORECARD_TABLE}
        WHERE {where} AND REFERENCE_PARENT_DISTRIBUTOR IS NOT NULL
        GROUP BY REFERENCE_PARENT_DISTRIBUTOR
        ORDER BY DOLLARS DESC
        LIMIT {limit}
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_customer_churn(_conn, access_filter: str, current_year: int,
                       clients: tuple = None) -> dict:
    """Find new and churned customers comparing current to prior year."""
    where_cy = _build_scorecard_where(access_filter, years=[current_year],
                                      clients=list(clients) if clients else None)
    where_py = _build_scorecard_where(access_filter, years=[current_year - 1],
                                      clients=list(clients) if clients else None)
    sql = f"""
        WITH cy AS (
            SELECT DISTINCT REFERENCE_CUSTOMER_NAME FROM {SCORECARD_TABLE}
            WHERE {where_cy} AND REFERENCE_CUSTOMER_NAME IS NOT NULL AND TRIM(REFERENCE_CUSTOMER_NAME) != ''
        ),
        py AS (
            SELECT DISTINCT REFERENCE_CUSTOMER_NAME FROM {SCORECARD_TABLE}
            WHERE {where_py} AND REFERENCE_CUSTOMER_NAME IS NOT NULL AND TRIM(REFERENCE_CUSTOMER_NAME) != ''
        )
        SELECT
            (SELECT COUNT(*) FROM cy WHERE REFERENCE_CUSTOMER_NAME NOT IN (SELECT REFERENCE_CUSTOMER_NAME FROM py)) AS NEW_CUSTOMERS,
            (SELECT COUNT(*) FROM py WHERE REFERENCE_CUSTOMER_NAME NOT IN (SELECT REFERENCE_CUSTOMER_NAME FROM cy)) AS CHURNED_CUSTOMERS,
            (SELECT COUNT(*) FROM cy) AS CURRENT_CUSTOMERS,
            (SELECT COUNT(*) FROM py) AS PRIOR_CUSTOMERS
    """
    df = _run(_conn, sql)
    if df.empty:
        return {"NEW_CUSTOMERS": 0, "CHURNED_CUSTOMERS": 0, "CURRENT_CUSTOMERS": 0, "PRIOR_CUSTOMERS": 0}
    return df.iloc[0].to_dict()


# ─────────────────────────────────────────────
# Comparative Intelligence
# ─────────────────────────────────────────────

@st.cache_data(ttl=600)
def get_client_market_share(_conn, access_filter: str, years: tuple) -> pd.DataFrame:
    """Client share of total portfolio dollars by year."""
    where = _build_scorecard_where(access_filter, years=list(years))
    sql = f"""
        SELECT CLIENT_NAME, DATA_YEAR, SUM(DOLLARS) AS DOLLARS
        FROM {SCORECARD_TABLE}
        WHERE {where}
        GROUP BY CLIENT_NAME, DATA_YEAR
        ORDER BY DATA_YEAR, DOLLARS DESC
    """
    return _run(_conn, sql)


@st.cache_data(ttl=600)
def get_state_breakdown(_conn, access_filter: str, year: int,
                        clients: tuple = None) -> pd.DataFrame:
    where = _build_scorecard_where(access_filter, years=[year],
                                   clients=list(clients) if clients else None)
    sql = f"""
        SELECT REFERENCE_STATE, SUM(DOLLARS) AS DOLLARS, SUM(CASES) AS CASES, SUM(LBS) AS LBS
        FROM {SCORECARD_TABLE}
        WHERE {where} AND REFERENCE_STATE IS NOT NULL AND TRIM(REFERENCE_STATE) != ''
        GROUP BY REFERENCE_STATE
        ORDER BY DOLLARS DESC
    """
    return _run(_conn, sql)
