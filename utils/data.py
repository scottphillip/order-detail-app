"""
Data query utilities for Snowflake order detail analytics.
All queries are parameterized with the user's territory filter.
"""
import pandas as pd


def get_kpis(conn, territory_filter: str, manufacturer_filter: list = None,
             distributor_filter: list = None, date_start: str = None, date_end: str = None) -> dict:
    """Get KPI metrics for the filtered data."""
    where_clauses = [territory_filter]

    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m}'" for m in manufacturer_filter])
        where_clauses.append(f"MANUFACTURERNAME IN ({mfr_list})")

    if distributor_filter:
        dist_list = ", ".join([f"'{d}'" for d in distributor_filter])
        where_clauses.append(f"DISTRIBUTORNAME IN ({dist_list})")

    if date_start:
        where_clauses.append(f"TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY') >= '{date_start}'")

    if date_end:
        where_clauses.append(f"TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY') <= '{date_end}'")

    where = " AND ".join(where_clauses)

    query = f"""
        SELECT 
            COALESCE(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS total_dollars,
            COUNT(DISTINCT ORDERNUMBER) AS total_orders,
            COALESCE(SUM(TRY_TO_DOUBLE(QTY)), 0) AS total_qty,
            CASE WHEN COUNT(*) > 0 
                 THEN COALESCE(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) / COUNT(*)
                 ELSE 0 END AS avg_line_value
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY
        WHERE {where}
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    if df.empty:
        return {"dollars": 0, "orders": 0, "qty": 0, "avg_order": 0}

    row = df.iloc[0]
    return {
        "dollars": float(row["TOTAL_DOLLARS"] or 0),
        "orders": int(row["TOTAL_ORDERS"] or 0),
        "qty": float(row["TOTAL_QTY"] or 0),
        "avg_order": float(row["AVG_LINE_VALUE"] or 0),
    }


def get_top_manufacturers(conn, territory_filter: str, limit: int = 10) -> pd.DataFrame:
    """Get top manufacturers by dollars."""
    query = f"""
        SELECT 
            MANUFACTURERNAME AS "Manufacturer",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            SUM(TRY_TO_DOUBLE(QTY)) AS "Total Qty",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY
        WHERE {territory_filter}
          AND MANUFACTURERNAME IS NOT NULL
        GROUP BY MANUFACTURERNAME
        ORDER BY "Total Dollars" DESC
        LIMIT {limit}
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_sales_trend(conn, territory_filter: str) -> pd.DataFrame:
    """Get weekly sales trend."""
    query = f"""
        SELECT 
            DATE_TRUNC('WEEK', TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY')) AS "Week",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY
        WHERE {territory_filter}
          AND ORDERDATE IS NOT NULL
        GROUP BY "Week"
        ORDER BY "Week"
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_distributor_breakdown(conn, territory_filter: str, limit: int = 10) -> pd.DataFrame:
    """Get top distributors by dollars."""
    query = f"""
        SELECT 
            DISTRIBUTORNAME AS "Distributor",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY
        WHERE {territory_filter}
          AND DISTRIBUTORNAME IS NOT NULL
        GROUP BY DISTRIBUTORNAME
        ORDER BY "Total Dollars" DESC
        LIMIT {limit}
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_filter_options(conn, territory_filter: str) -> dict:
    """Get available filter values scoped to user's access."""
    mfr_query = f"""
        SELECT DISTINCT MANUFACTURERNAME 
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY
        WHERE {territory_filter} AND MANUFACTURERNAME IS NOT NULL
        ORDER BY MANUFACTURERNAME
    """
    dist_query = f"""
        SELECT DISTINCT DISTRIBUTORNAME 
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY
        WHERE {territory_filter} AND DISTRIBUTORNAME IS NOT NULL
        ORDER BY DISTRIBUTORNAME
    """
    mfr_df = conn.cursor().execute(mfr_query).fetch_pandas_all()
    dist_df = conn.cursor().execute(dist_query).fetch_pandas_all()

    return {
        "manufacturers": mfr_df["MANUFACTURERNAME"].tolist() if not mfr_df.empty else [],
        "distributors": dist_df["DISTRIBUTORNAME"].tolist() if not dist_df.empty else [],
    }


def run_custom_query(conn, sql: str) -> pd.DataFrame:
    """Execute a custom SQL query and return results as DataFrame."""
    return conn.cursor().execute(sql).fetch_pandas_all()
