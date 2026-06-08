"""
Data query utilities for Snowflake order detail analytics.
All queries use VW_MYORDERDETAIL_ALL which has PARENT_DISTRIBUTOR pre-joined.
Includes monthly breakdown, manufacturer drill-down, and distributor hierarchy.
"""
import pandas as pd
import streamlit as st

# Main order view — has PARENT_DISTRIBUTOR already joined
ORDER_VIEW = "DB_NXT.SCH_NXT.VW_MYORDERDETAIL_ALL"

# Date parsing: data has mixed formats (MM/DD/YYYY and YYYY-MM-DD)
PARSE_DATE = "COALESCE(TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY'), TRY_TO_DATE(ORDERDATE, 'YYYY-MM-DD'))"

# PFG super-parent: Performance Food Group encompasses these parent distributors
PFG_PARENTS = [
    "Performance Foodservice Corporate",
    "Performance Foodservice Vistar Corporate",
    "Reinhart Foodservice Corporate",
]


# Max dollar value per line item — filters out corrupted rows with misaligned columns
# (e.g., $1.9B single line items that are clearly data import errors)
MAX_LINE_DOLLARS = 1000000


def _build_where(territory_filter: str, manufacturer_filter: list = None,
                 parent_filter: str = None, category_filter: list = None,
                 year_filter: int = None, month_start: int = None,
                 month_end: int = None) -> str:
    """Build WHERE clause from filters. Defaults to current year if year_filter not specified.
    month_start/month_end filter by MONTH(date) BETWEEN start AND end.
    Includes data quality filter to exclude corrupt dollar values."""
    clauses = [territory_filter]
    # Data quality: exclude rows with unreasonably large dollar values (column misalignment)
    clauses.append(f"(TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < {MAX_LINE_DOLLARS})")
    if year_filter:
        clauses.append(f"YEAR({PARSE_DATE}) = {year_filter}")
    else:
        clauses.append(f"YEAR({PARSE_DATE}) = YEAR(CURRENT_DATE())")
    if month_start and month_end:
        clauses.append(f"MONTH({PARSE_DATE}) BETWEEN {month_start} AND {month_end}")
    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m.replace(chr(39), chr(39)+chr(39))}'" for m in manufacturer_filter])
        clauses.append(f"MANUFACTURERNAME IN ({mfr_list})")
    if parent_filter:
        if parent_filter == "Independent":
            clauses.append("(PARENT_DISTRIBUTOR IS NULL OR PARENT_DISTRIBUTOR = '')")
        elif parent_filter == "PFG":
            pfg_list = ", ".join([f"'{p}'" for p in PFG_PARENTS])
            clauses.append(f"PARENT_DISTRIBUTOR IN ({pfg_list})")
        else:
            safe = parent_filter.replace("'", "''")
            clauses.append(f"PARENT_DISTRIBUTOR = '{safe}'")
    if category_filter:
        cat_list = ", ".join([f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in category_filter])
        clauses.append(f"CATEGORY IN ({cat_list})")
    return " AND ".join(clauses)


def _add_store_filter(where: str, store_name: str = None) -> str:
    """Add individual store filter if specified."""
    if store_name:
        safe = store_name.replace("'", "''")
        return f"{where} AND DISTRIBUTORNAME = '{safe}'"
    return where


@st.cache_data(ttl=600, show_spinner=False)
def get_available_years(_conn, territory_filter: str) -> list:
    """Get distinct years available in the order data."""
    query = f"""
        SELECT DISTINCT YEAR({PARSE_DATE}) AS yr
        FROM {ORDER_VIEW}
        WHERE {territory_filter} AND ORDERDATE IS NOT NULL
          AND {PARSE_DATE} IS NOT NULL
        ORDER BY yr DESC
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    if df.empty:
        return []
    return [int(y) for y in df["YR"].dropna().tolist()]


@st.cache_data(ttl=600, show_spinner=False)
def get_max_month(_conn, territory_filter: str, year: int) -> int:
    """Get the latest month with data for a given year."""
    query = f"""
        SELECT MAX(MONTH({PARSE_DATE})) AS max_mo
        FROM {ORDER_VIEW}
        WHERE {territory_filter}
          AND YEAR({PARSE_DATE}) = {year}
          AND {PARSE_DATE} IS NOT NULL
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    if df.empty or df.iloc[0]["MAX_MO"] is None:
        return 12
    import math
    val = df.iloc[0]["MAX_MO"]
    try:
        v = int(float(val))
        return v if v > 0 else 12
    except (TypeError, ValueError):
        return 12


@st.cache_data(ttl=600, show_spinner=False)
def get_categories_for_manufacturers(_conn, territory_filter: str,
                                     manufacturer_filter: list) -> list:
    """Get item categories available for selected manufacturers (current year)."""
    where = _build_where(territory_filter, manufacturer_filter)
    query = f"""
        SELECT DISTINCT CATEGORY
        FROM {ORDER_VIEW}
        WHERE {where} AND CATEGORY IS NOT NULL AND CATEGORY != ''
        ORDER BY CATEGORY
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    return df["CATEGORY"].tolist() if not df.empty else []


@st.cache_data(ttl=600, show_spinner=False)
def get_kpis(_conn, territory_filter: str, manufacturer_filter: list = None,
             parent_filter: str = None, category_filter: list = None,
             year: int = None, store_name: str = None,
             month_start: int = None, month_end: int = None) -> dict:
    """Get KPI metrics for the filtered data (defaults to current year)."""
    where = _build_where(territory_filter, manufacturer_filter, parent_filter, category_filter, year,
                         month_start=month_start, month_end=month_end)
    where = _add_store_filter(where, store_name)
    query = f"""
        SELECT 
            COALESCE(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS total_dollars,
            COUNT(DISTINCT ORDERNUMBER) AS total_orders,
            COALESCE(SUM(TRY_TO_DOUBLE(QTY)), 0) AS total_qty,
            COALESCE(SUM(TRY_TO_DOUBLE(COMM)), 0) AS total_comm,
            CASE WHEN COUNT(*) > 0 
                 THEN COALESCE(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) / COUNT(*)
                 ELSE 0 END AS avg_line_value
        FROM {ORDER_VIEW}
        WHERE {where}
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    if df.empty:
        return {"dollars": 0, "orders": 0, "qty": 0, "comm": 0, "avg_order": 0}
    row = df.iloc[0]
    import math

    def safe_float(v):
        try:
            f = float(v)
            return 0.0 if math.isnan(f) else f
        except (TypeError, ValueError):
            return 0.0

    def safe_int(v):
        try:
            f = float(v)
            return 0 if math.isnan(f) else int(f)
        except (TypeError, ValueError):
            return 0

    return {
        "dollars": safe_float(row["TOTAL_DOLLARS"]),
        "orders": safe_int(row["TOTAL_ORDERS"]),
        "qty": safe_float(row["TOTAL_QTY"]),
        "comm": safe_float(row["TOTAL_COMM"]),
        "avg_order": safe_float(row["AVG_LINE_VALUE"]),
    }


@st.cache_data(ttl=600, show_spinner=False)
def get_monthly_breakdown(_conn, territory_filter: str, manufacturer_filter: list = None,
                          parent_filter: str = None, category_filter: list = None,
                          year: int = None, store_name: str = None,
                          month_start: int = None, month_end: int = None) -> pd.DataFrame:
    """YTD month-by-month sales breakdown for selected year."""
    where = _build_where(territory_filter, manufacturer_filter, parent_filter, category_filter, year,
                         month_start=month_start, month_end=month_end)
    where = _add_store_filter(where, store_name)
    query = f"""
        SELECT 
            DATE_TRUNC('MONTH', {PARSE_DATE}) AS "Month",
            MONTHNAME({PARSE_DATE}) AS "Month Name",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            SUM(TRY_TO_DOUBLE(QTY)) AS "Total Qty",
            SUM(TRY_TO_DOUBLE(COMM)) AS "Total Comm",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND {PARSE_DATE} IS NOT NULL
        GROUP BY "Month", "Month Name"
        ORDER BY "Month"
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=600, show_spinner=False)
def get_top_manufacturers(_conn, territory_filter: str, parent_filter: str = None,
                          category_filter: list = None, year: int = None,
                          limit: int = 10) -> pd.DataFrame:
    """Get top manufacturers by dollars (selected year)."""
    where = _build_where(territory_filter, parent_filter=parent_filter,
                         category_filter=category_filter, year_filter=year)
    query = f"""
        SELECT 
            MANUFACTURERNAME AS "Manufacturer",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            SUM(TRY_TO_DOUBLE(QTY)) AS "Total Qty",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND MANUFACTURERNAME IS NOT NULL
        GROUP BY MANUFACTURERNAME
        ORDER BY "Total Dollars" DESC
        LIMIT {limit}
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=600, show_spinner=False)
def get_sales_trend(_conn, territory_filter: str, manufacturer_filter: list = None,
                    parent_filter: str = None, category_filter: list = None,
                    year: int = None) -> pd.DataFrame:
    """Get weekly sales trend (selected year)."""
    where = _build_where(territory_filter, manufacturer_filter, parent_filter, category_filter, year)
    query = f"""
        SELECT 
            DATE_TRUNC('WEEK', {PARSE_DATE}) AS "Week",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND {PARSE_DATE} IS NOT NULL
        GROUP BY "Week"
        ORDER BY "Week"
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


# =============================================================================
# DISTRIBUTOR HIERARCHY (uses PARENT_DISTRIBUTOR column directly)
# =============================================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_distributor_parents(_conn, territory_filter: str, manufacturer_filter: list = None,
                            year: int = None) -> pd.DataFrame:
    """Get distributor parents with rollup totals using PARENT_DISTRIBUTOR column."""
    where = _build_where(territory_filter, manufacturer_filter, year_filter=year)
    query = f"""
        SELECT 
            COALESCE(NULLIF(PARENT_DISTRIBUTOR, ''), 'Independent') AS "Parent",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders",
            COUNT(DISTINCT DISTRIBUTORNAME) AS "Store Count"
        FROM {ORDER_VIEW}
        WHERE {where}
        GROUP BY "Parent"
        ORDER BY "Total Dollars" DESC
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=600, show_spinner=False)
def get_parent_stores(_conn, territory_filter: str, parent_name: str,
                      manufacturer_filter: list = None, year: int = None) -> pd.DataFrame:
    """Get individual store breakdown under a parent distributor."""
    where = _build_where(territory_filter, manufacturer_filter, parent_filter=parent_name, year_filter=year)
    query = f"""
        SELECT 
            DISTRIBUTORNAME AS "Store",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            SUM(TRY_TO_DOUBLE(QTY)) AS "Total Qty",
            SUM(TRY_TO_DOUBLE(COMM)) AS "Total Comm",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
        GROUP BY "Store"
        ORDER BY "Total Dollars" DESC
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=600, show_spinner=False)
def get_parent_monthly(_conn, territory_filter: str, parent_name: str,
                       manufacturer_filter: list = None, year: int = None) -> pd.DataFrame:
    """Monthly breakdown for a parent distributor's stores."""
    where = _build_where(territory_filter, manufacturer_filter, parent_filter=parent_name, year_filter=year)
    query = f"""
        SELECT 
            DATE_TRUNC('MONTH', {PARSE_DATE}) AS "Month",
            MONTHNAME({PARSE_DATE}) AS "Month Name",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND {PARSE_DATE} IS NOT NULL
        GROUP BY "Month", "Month Name"
        ORDER BY "Month"
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=600, show_spinner=False)
def get_pfg_summary(_conn, territory_filter: str, manufacturer_filter: list = None,
                    year: int = None) -> dict:
    """
    Get PFG (Performance Food Group) super-parent summary.
    Groups Performance FS Corporate + Vistar + Reinhart together.
    """
    pfg_list = ", ".join([f"'{p}'" for p in PFG_PARENTS])
    where = _build_where(territory_filter, manufacturer_filter, year_filter=year)
    query = f"""
        SELECT 
            PARENT_DISTRIBUTOR AS "Parent",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders",
            COUNT(DISTINCT DISTRIBUTORNAME) AS "Store Count"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND PARENT_DISTRIBUTOR IN ({pfg_list})
        GROUP BY PARENT_DISTRIBUTOR
        ORDER BY "Total Dollars" DESC
    """
    df = _conn.cursor().execute(query).fetch_pandas_all()
    total_dollars = df["Total Dollars"].sum() if not df.empty else 0
    total_stores = df["Store Count"].sum() if not df.empty else 0
    return {
        "total_dollars": float(total_dollars),
        "total_stores": int(total_stores),
        "breakdown": df,
    }


# =============================================================================
# FILTER OPTIONS
# =============================================================================

@st.cache_data(ttl=600, show_spinner=False)
def get_filter_options(_conn, territory_filter: str, year: int = None) -> dict:
    """Get available filter values scoped to user's access."""
    where = _build_where(territory_filter, year_filter=year)

    mfr_query = f"""
        SELECT DISTINCT MANUFACTURERNAME 
        FROM {ORDER_VIEW}
        WHERE {where} AND MANUFACTURERNAME IS NOT NULL
        ORDER BY MANUFACTURERNAME
    """
    mfr_df = _conn.cursor().execute(mfr_query).fetch_pandas_all()

    # Get parent distributors using the PARENT_DISTRIBUTOR column
    parent_query = f"""
        SELECT 
            COALESCE(NULLIF(PARENT_DISTRIBUTOR, ''), 'Independent') AS parent_name,
            COUNT(DISTINCT DISTRIBUTORNAME) AS store_count
        FROM {ORDER_VIEW}
        WHERE {where}
        GROUP BY parent_name
        HAVING SUM(TRY_TO_DOUBLE(DOLLARS)) > 0
        ORDER BY SUM(TRY_TO_DOUBLE(DOLLARS)) DESC
    """
    parent_df = _conn.cursor().execute(parent_query).fetch_pandas_all()

    parents = []
    if not parent_df.empty:
        for _, row in parent_df.iterrows():
            parents.append({
                "name": row["PARENT_NAME"],
                "stores": int(row["STORE_COUNT"]),
            })

    return {
        "manufacturers": mfr_df["MANUFACTURERNAME"].tolist() if not mfr_df.empty else [],
        "parents": parents,
    }


def run_custom_query(conn, sql: str) -> pd.DataFrame:
    """Execute a custom SQL query and return results as DataFrame."""
    return conn.cursor().execute(sql).fetch_pandas_all()


@st.cache_data(ttl=600, show_spinner=False)
def get_declining_accounts(_conn, territory_filter: str, threshold_pct: float = -20.0,
                           min_cases: int = 10000) -> pd.DataFrame:
    """
    Find accounts with significant YoY case decline in the current period.
    Compares current year-to-date vs same period last year.
    Uses UPPER(TRIM(DISTRIBUTORNAME)) to consolidate case-variant duplicates
    (e.g. "C&S Wholesale Grocers" vs "C&S WHOLESALE GROCERS").
    Only includes accounts with at least min_cases last year (avoids noise).

    Returns DataFrame with columns: DISTRIBUTOR, CY_CASES, PY_CASES, PCT_CHANGE, CASE_DELTA
    """
    query = f"""
        WITH current_year AS (
            SELECT
                UPPER(TRIM(DISTRIBUTORNAME)) AS DISTRIBUTOR,
                SUM(TRY_TO_DOUBLE(QTY)) AS CY_CASES
            FROM {ORDER_VIEW}
            WHERE {territory_filter}
              AND YEAR({PARSE_DATE}) = YEAR(CURRENT_DATE())
              AND MONTH({PARSE_DATE}) <= MONTH(CURRENT_DATE())
              AND TRY_TO_DOUBLE(QTY) > 0
            GROUP BY UPPER(TRIM(DISTRIBUTORNAME))
        ),
        prior_year AS (
            SELECT
                UPPER(TRIM(DISTRIBUTORNAME)) AS DISTRIBUTOR,
                SUM(TRY_TO_DOUBLE(QTY)) AS PY_CASES
            FROM {ORDER_VIEW}
            WHERE {territory_filter}
              AND YEAR({PARSE_DATE}) = YEAR(CURRENT_DATE()) - 1
              AND MONTH({PARSE_DATE}) <= MONTH(CURRENT_DATE())
              AND TRY_TO_DOUBLE(QTY) > 0
            GROUP BY UPPER(TRIM(DISTRIBUTORNAME))
        )
        SELECT
            py.DISTRIBUTOR,
            COALESCE(cy.CY_CASES, 0) AS CY_CASES,
            py.PY_CASES,
            ROUND(((COALESCE(cy.CY_CASES, 0) - py.PY_CASES) / py.PY_CASES) * 100, 1) AS PCT_CHANGE,
            COALESCE(cy.CY_CASES, 0) - py.PY_CASES AS CASE_DELTA
        FROM prior_year py
        LEFT JOIN current_year cy ON cy.DISTRIBUTOR = py.DISTRIBUTOR
        WHERE py.PY_CASES >= {min_cases}
          AND ((COALESCE(cy.CY_CASES, 0) - py.PY_CASES) / py.PY_CASES) * 100 <= {threshold_pct}
        ORDER BY (COALESCE(cy.CY_CASES, 0) - py.PY_CASES) ASC
        LIMIT 10
    """
    try:
        return _conn.cursor().execute(query).fetch_pandas_all()
    except Exception:
        return pd.DataFrame()



@st.cache_data(ttl=600, show_spinner=False)
def get_data_freshness(_conn) -> str | None:
    """Get the most recent order date in the data to show freshness."""
    query = f"""
        SELECT MAX({PARSE_DATE}) AS latest_date
        FROM {ORDER_VIEW}
        WHERE {PARSE_DATE} IS NOT NULL
    """
    try:
        df = _conn.cursor().execute(query).fetch_pandas_all()
        if df.empty or df.iloc[0]["LATEST_DATE"] is None:
            return None
        latest = df.iloc[0]["LATEST_DATE"]
        if hasattr(latest, 'strftime'):
            return latest.strftime("%b %d, %Y")
        return str(latest)
    except Exception:
        return None
