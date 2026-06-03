"""
Data query utilities for Snowflake order detail analytics.
All queries are parameterized with the user's territory filter.
Includes monthly breakdown, manufacturer drill-down, and distributor hierarchy.
"""
import pandas as pd

# Views
ORDER_VIEW = "DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY"
DIST_REF = "DB_PROD_RAW.SCH_RAW_SHAREPOINT.TB_REF_DISTRIBUTORLIST"

# PFG super-parent: Performance Food Group encompasses these parent distributors
PFG_PARENTS = [
    "Performance Foodservice Corporate",
    "Performance Foodservice Vistar Corporate",
    "Reinhart Foodservice Corporate",
]


def _build_where(territory_filter: str, manufacturer_filter: list = None,
                 distributor_codes: list = None, category_filter: list = None,
                 year_filter: bool = True) -> str:
    """Build WHERE clause from filters. Defaults to current year."""
    clauses = [territory_filter]
    if year_filter:
        clauses.append("YEAR(TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY')) = YEAR(CURRENT_DATE())")
    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m.replace(chr(39), chr(39)+chr(39))}'" for m in manufacturer_filter])
        clauses.append(f"MANUFACTURERNAME IN ({mfr_list})")
    if distributor_codes:
        dist_list = ", ".join([f"'{d.replace(chr(39), chr(39)+chr(39))}'" for d in distributor_codes])
        clauses.append(f"DISTRIBUTORCODE IN ({dist_list})")
    if category_filter:
        cat_list = ", ".join([f"'{c.replace(chr(39), chr(39)+chr(39))}'" for c in category_filter])
        clauses.append(f"CATEGORY IN ({cat_list})")
    return " AND ".join(clauses)


def get_categories_for_manufacturers(conn, territory_filter: str,
                                     manufacturer_filter: list) -> list:
    """Get item categories available for selected manufacturers (current year)."""
    where = _build_where(territory_filter, manufacturer_filter)
    query = f"""
        SELECT DISTINCT CATEGORY
        FROM {ORDER_VIEW}
        WHERE {where} AND CATEGORY IS NOT NULL AND CATEGORY != ''
        ORDER BY CATEGORY
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    return df["CATEGORY"].tolist() if not df.empty else []


def get_kpis(conn, territory_filter: str, manufacturer_filter: list = None,
             distributor_codes: list = None, category_filter: list = None) -> dict:
    """Get KPI metrics for the filtered data (defaults to current year)."""
    where = _build_where(territory_filter, manufacturer_filter, distributor_codes, category_filter)
    query = f"""
        SELECT 
            COALESCE(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) AS total_dollars,
            COUNT(DISTINCT ORDERNUMBER) AS total_orders,
            COALESCE(SUM(TRY_TO_DOUBLE(QTY)), 0) AS total_qty,
            CASE WHEN COUNT(*) > 0 
                 THEN COALESCE(SUM(TRY_TO_DOUBLE(DOLLARS)), 0) / COUNT(*)
                 ELSE 0 END AS avg_line_value
        FROM {ORDER_VIEW}
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


def get_monthly_breakdown(conn, territory_filter: str, manufacturer_filter: list = None,
                          distributor_codes: list = None, category_filter: list = None) -> pd.DataFrame:
    """YTD month-by-month sales breakdown for current year."""
    where = _build_where(territory_filter, manufacturer_filter, distributor_codes, category_filter)
    query = f"""
        SELECT 
            DATE_TRUNC('MONTH', TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY')) AS "Month",
            MONTHNAME(TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY')) AS "Month Name",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            SUM(TRY_TO_DOUBLE(QTY)) AS "Total Qty",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND ORDERDATE IS NOT NULL
        GROUP BY "Month", "Month Name"
        ORDER BY "Month"
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_top_manufacturers(conn, territory_filter: str, distributor_codes: list = None,
                          category_filter: list = None, limit: int = 10) -> pd.DataFrame:
    """Get top manufacturers by dollars (current year)."""
    where = _build_where(territory_filter, distributor_codes=distributor_codes, category_filter=category_filter)
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
    return conn.cursor().execute(query).fetch_pandas_all()


def get_sales_trend(conn, territory_filter: str, manufacturer_filter: list = None,
                    distributor_codes: list = None, category_filter: list = None) -> pd.DataFrame:
    """Get weekly sales trend (current year)."""
    where = _build_where(territory_filter, manufacturer_filter, distributor_codes, category_filter)
    query = f"""
        SELECT 
            DATE_TRUNC('WEEK', TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY')) AS "Week",
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW}
        WHERE {where}
          AND ORDERDATE IS NOT NULL
        GROUP BY "Week"
        ORDER BY "Week"
    """
    return conn.cursor().execute(query).fetch_pandas_all()


# =============================================================================
# DISTRIBUTOR HIERARCHY
# =============================================================================

def get_distributor_parents(conn, territory_filter: str, manufacturer_filter: list = None) -> pd.DataFrame:
    """
    Get distributor parents with rollup totals.
    Joins order data to TB_REF_DISTRIBUTORLIST to get ParentDistributor.
    Returns parent-level aggregates sorted by dollars DESC.
    """
    mfr_clause = ""
    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m.replace(chr(39), chr(39)+chr(39))}'" for m in manufacturer_filter])
        mfr_clause = f"AND o.MANUFACTURERNAME IN ({mfr_list})"

    query = f"""
        SELECT 
            COALESCE(d."ParentDistributor", 'Independent') AS "Parent",
            SUM(TRY_TO_DOUBLE(o.DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT o.ORDERNUMBER) AS "Orders",
            COUNT(DISTINCT o.DISTRIBUTORCODE) AS "Store Count"
        FROM {ORDER_VIEW} o
        LEFT JOIN (
            SELECT DISTINCT "DistCode", "ParentDistributor"
            FROM {DIST_REF}
            WHERE "DistCode" IS NOT NULL AND "DistCode" != ''
        ) d ON o.DISTRIBUTORCODE = d."DistCode"
        WHERE {territory_filter}
          AND YEAR(TRY_TO_DATE(o.ORDERDATE, 'MM/DD/YYYY')) = YEAR(CURRENT_DATE())
          {mfr_clause}
        GROUP BY "Parent"
        ORDER BY "Total Dollars" DESC
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_parent_stores(conn, territory_filter: str, parent_name: str,
                      manufacturer_filter: list = None) -> pd.DataFrame:
    """Get individual store breakdown under a parent distributor."""
    mfr_clause = ""
    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m.replace(chr(39), chr(39)+chr(39))}'" for m in manufacturer_filter])
        mfr_clause = f"AND o.MANUFACTURERNAME IN ({mfr_list})"

    safe_parent = parent_name.replace("'", "''")

    if parent_name == "Independent":
        parent_condition = '(d."ParentDistributor" IS NULL OR d."ParentDistributor" = \'\')'
    else:
        parent_condition = f'd."ParentDistributor" = \'{safe_parent}\''

    query = f"""
        SELECT 
            o.DISTRIBUTORNAME AS "Store",
            o.DISTRIBUTORCODE AS "Code",
            SUM(TRY_TO_DOUBLE(o.DOLLARS)) AS "Total Dollars",
            SUM(TRY_TO_DOUBLE(o.QTY)) AS "Total Qty",
            COUNT(DISTINCT o.ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW} o
        LEFT JOIN (
            SELECT DISTINCT "DistCode", "ParentDistributor"
            FROM {DIST_REF}
            WHERE "DistCode" IS NOT NULL AND "DistCode" != ''
        ) d ON o.DISTRIBUTORCODE = d."DistCode"
        WHERE {territory_filter}
          AND YEAR(TRY_TO_DATE(o.ORDERDATE, 'MM/DD/YYYY')) = YEAR(CURRENT_DATE())
          AND {parent_condition}
          {mfr_clause}
        GROUP BY "Store", "Code"
        ORDER BY "Total Dollars" DESC
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_parent_monthly(conn, territory_filter: str, parent_name: str,
                       manufacturer_filter: list = None) -> pd.DataFrame:
    """Monthly breakdown for a parent distributor's stores."""
    mfr_clause = ""
    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m.replace(chr(39), chr(39)+chr(39))}'" for m in manufacturer_filter])
        mfr_clause = f"AND o.MANUFACTURERNAME IN ({mfr_list})"

    safe_parent = parent_name.replace("'", "''")

    if parent_name == "Independent":
        parent_condition = '(d."ParentDistributor" IS NULL OR d."ParentDistributor" = \'\')'
    else:
        parent_condition = f'd."ParentDistributor" = \'{safe_parent}\''

    query = f"""
        SELECT 
            DATE_TRUNC('MONTH', TRY_TO_DATE(o.ORDERDATE, 'MM/DD/YYYY')) AS "Month",
            MONTHNAME(TRY_TO_DATE(o.ORDERDATE, 'MM/DD/YYYY')) AS "Month Name",
            SUM(TRY_TO_DOUBLE(o.DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT o.ORDERNUMBER) AS "Orders"
        FROM {ORDER_VIEW} o
        LEFT JOIN (
            SELECT DISTINCT "DistCode", "ParentDistributor"
            FROM {DIST_REF}
            WHERE "DistCode" IS NOT NULL AND "DistCode" != ''
        ) d ON o.DISTRIBUTORCODE = d."DistCode"
        WHERE {territory_filter}
          AND YEAR(TRY_TO_DATE(o.ORDERDATE, 'MM/DD/YYYY')) = YEAR(CURRENT_DATE())
          AND {parent_condition}
          AND o.ORDERDATE IS NOT NULL
          {mfr_clause}
        GROUP BY "Month", "Month Name"
        ORDER BY "Month"
    """
    return conn.cursor().execute(query).fetch_pandas_all()


def get_pfg_summary(conn, territory_filter: str, manufacturer_filter: list = None) -> dict:
    """
    Get PFG (Performance Food Group) super-parent summary.
    Groups Performance FS Corporate + Vistar + Reinhart together.
    """
    pfg_list = ", ".join([f"'{p}'" for p in PFG_PARENTS])
    mfr_clause = ""
    if manufacturer_filter:
        mfr_list = ", ".join([f"'{m.replace(chr(39), chr(39)+chr(39))}'" for m in manufacturer_filter])
        mfr_clause = f"AND o.MANUFACTURERNAME IN ({mfr_list})"

    query = f"""
        SELECT 
            d."ParentDistributor" AS "Parent",
            SUM(TRY_TO_DOUBLE(o.DOLLARS)) AS "Total Dollars",
            COUNT(DISTINCT o.ORDERNUMBER) AS "Orders",
            COUNT(DISTINCT o.DISTRIBUTORCODE) AS "Store Count"
        FROM {ORDER_VIEW} o
        INNER JOIN (
            SELECT DISTINCT "DistCode", "ParentDistributor"
            FROM {DIST_REF}
            WHERE "DistCode" IS NOT NULL AND "DistCode" != ''
              AND "ParentDistributor" IN ({pfg_list})
        ) d ON o.DISTRIBUTORCODE = d."DistCode"
        WHERE {territory_filter}
          AND YEAR(TRY_TO_DATE(o.ORDERDATE, 'MM/DD/YYYY')) = YEAR(CURRENT_DATE())
          {mfr_clause}
        GROUP BY d."ParentDistributor"
        ORDER BY "Total Dollars" DESC
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    total_dollars = df["Total Dollars"].sum() if not df.empty else 0
    total_stores = df["Store Count"].sum() if not df.empty else 0
    return {
        "total_dollars": float(total_dollars),
        "total_stores": int(total_stores),
        "breakdown": df,
    }


def get_dist_codes_for_parent(conn, parent_name: str) -> list:
    """Get all DistCodes under a parent distributor for filtering."""
    safe_parent = parent_name.replace("'", "''")
    query = f"""
        SELECT DISTINCT "DistCode"
        FROM {DIST_REF}
        WHERE "ParentDistributor" = '{safe_parent}'
          AND "DistCode" IS NOT NULL AND "DistCode" != ''
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    return df["DistCode"].tolist() if not df.empty else []


def get_dist_codes_for_pfg(conn) -> list:
    """Get all DistCodes under PFG super-parent."""
    pfg_list = ", ".join([f"'{p}'" for p in PFG_PARENTS])
    query = f"""
        SELECT DISTINCT "DistCode"
        FROM {DIST_REF}
        WHERE "ParentDistributor" IN ({pfg_list})
          AND "DistCode" IS NOT NULL AND "DistCode" != ''
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    return df["DistCode"].tolist() if not df.empty else []


# =============================================================================
# FILTER OPTIONS
# =============================================================================

def get_filter_options(conn, territory_filter: str) -> dict:
    """Get available filter values scoped to user's access (current year)."""
    where = _build_where(territory_filter)

    mfr_query = f"""
        SELECT DISTINCT MANUFACTURERNAME 
        FROM {ORDER_VIEW}
        WHERE {where} AND MANUFACTURERNAME IS NOT NULL
        ORDER BY MANUFACTURERNAME
    """
    mfr_df = conn.cursor().execute(mfr_query).fetch_pandas_all()

    # Get parent distributors for the hierarchy filter
    parent_query = f"""
        SELECT 
            COALESCE(d."ParentDistributor", 'Independent') AS parent_name,
            COUNT(DISTINCT o.DISTRIBUTORCODE) AS store_count
        FROM {ORDER_VIEW} o
        LEFT JOIN (
            SELECT DISTINCT "DistCode", "ParentDistributor"
            FROM {DIST_REF}
            WHERE "DistCode" IS NOT NULL AND "DistCode" != ''
        ) d ON o.DISTRIBUTORCODE = d."DistCode"
        WHERE {where}
        GROUP BY parent_name
        HAVING SUM(TRY_TO_DOUBLE(o.DOLLARS)) > 0
        ORDER BY SUM(TRY_TO_DOUBLE(o.DOLLARS)) DESC
    """
    parent_df = conn.cursor().execute(parent_query).fetch_pandas_all()

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
