"""
Contract management utilities for the Affinity Sales Hub.
Handles contract storage, AI-powered rate extraction, and commission comparison.
"""
import json
import pandas as pd
import streamlit as st
from datetime import datetime, date


# Database references
CONTRACTS_TABLE = "DB_PROD_RAW.SCH_RAW_SHAREPOINT.TB_CONTRACTS"
RATES_TABLE = "DB_PROD_RAW.SCH_RAW_SHAREPOINT.TB_CONTRACT_RATES"
STAGE_PATH = "@DB_PROD_RAW.SCH_RAW_SHAREPOINT.STG_CONTRACTS"
ORDER_VIEW = "DB_NXT.SCH_NXT.VW_MYORDERDETAIL_ALL"
PARSE_DATE = "COALESCE(TRY_TO_DATE(ORDERDATE, 'MM/DD/YYYY'), TRY_TO_DATE(ORDERDATE, 'YYYY-MM-DD'))"


# ─── Contract CRUD ───────────────────────────────────────────────────────────


def upload_contract_file(conn, file_obj, manufacturer: str, contract_name: str,
                         effective_date: date, expiration_date: date,
                         uploaded_by: str) -> int:
    """
    Upload a contract file to Snowflake stage and create a metadata record.
    Returns the new CONTRACT_ID.
    """
    # Generate a unique stage path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_mfr = manufacturer.replace(" ", "_").replace("/", "_")[:50]
    ext = file_obj.name.rsplit(".", 1)[-1] if "." in file_obj.name else "pdf"
    stage_file = f"{safe_mfr}/{timestamp}_{file_obj.name}"

    # Upload file to stage using PUT via stream
    cur = conn.cursor()
    cur.execute(f"PUT file://{file_obj.name} {STAGE_PATH}/{safe_mfr}/ AUTO_COMPRESS=FALSE OVERWRITE=TRUE",
                file_stream=file_obj)

    file_path = f"{STAGE_PATH}/{safe_mfr}/{file_obj.name}"

    # Extract text using AI_PARSE_DOCUMENT
    extracted_text = extract_document_text(conn, file_path)

    # Insert contract record
    eff_str = effective_date.strftime("%Y-%m-%d") if effective_date else "NULL"
    exp_str = expiration_date.strftime("%Y-%m-%d") if expiration_date else "NULL"
    safe_name = contract_name.replace("'", "''")
    safe_mfr_sql = manufacturer.replace("'", "''")
    safe_text = extracted_text.replace("'", "''") if extracted_text else ""
    safe_user = uploaded_by.replace("'", "''")

    insert_sql = f"""
        INSERT INTO {CONTRACTS_TABLE} 
            (MANUFACTURER, CONTRACT_NAME, EFFECTIVE_DATE, EXPIRATION_DATE, 
             FILE_PATH, EXTRACTED_TEXT, STATUS, UPLOADED_BY)
        VALUES (
            '{safe_mfr_sql}', '{safe_name}', 
            {'NULL' if not effective_date else f"'{eff_str}'"}, 
            {'NULL' if not expiration_date else f"'{exp_str}'"}, 
            '{file_path}', '{safe_text}', 'ACTIVE', '{safe_user}'
        )
    """
    cur.execute(insert_sql)

    # Get the new contract ID
    result = cur.execute(f"SELECT MAX(CONTRACT_ID) FROM {CONTRACTS_TABLE}").fetchone()
    return result[0]


def extract_document_text(conn, stage_path: str) -> str:
    """Use AI_PARSE_DOCUMENT to extract text from a staged document."""
    try:
        query = f"""
            SELECT SNOWFLAKE.CORTEX.PARSE_DOCUMENT(
                BUILD_SCOPED_FILE_URL({STAGE_PATH}, '{stage_path.split("/")[-1]}'),
                '{{}}'
            ):content::VARCHAR AS doc_text
        """
        # Fallback: try simpler approach
        query = f"""
            SELECT SNOWFLAKE.CORTEX.PARSE_DOCUMENT(
                '{stage_path}', '{{}}'
            ):content::VARCHAR AS doc_text
        """
        result = conn.cursor().execute(query).fetchone()
        return result[0] if result and result[0] else ""
    except Exception as e:
        # If AI_PARSE_DOCUMENT fails, return empty (user can paste text manually)
        return f"[Extraction failed: {str(e)[:200]}]"


def extract_rates_with_ai(conn, contract_text: str, manufacturer: str) -> list[dict]:
    """
    Use Cortex Complete to extract commission rates from contract text.
    Returns list of rate dicts: [{category, rate_type, rate_value, volume_min, volume_max, notes}]
    """
    if not contract_text or contract_text.startswith("[Extraction failed"):
        return []

    # Truncate to fit context window
    text_chunk = contract_text[:8000]
    escaped_text = text_chunk.replace("'", "''").replace("\\", "\\\\")

    prompt = f"""Extract all commission rate information from this manufacturer contract for {manufacturer}.

Return a JSON array where each element has these fields:
- "category": the product category or "ALL" if flat rate applies to everything
- "rate_type": one of "PERCENTAGE", "FLAT_PER_CASE", "FLAT_PER_LB"
- "rate_value": the numeric rate (e.g., 3.5 for 3.5%, or 0.50 for $0.50/case)
- "volume_min": minimum volume threshold (null if no tier)
- "volume_max": maximum volume threshold (null if no tier)
- "notes": any conditions or special terms

If no commission rates are found, return an empty array [].
Return ONLY valid JSON, no explanation.

Contract text:
{escaped_text}"""

    escaped_prompt = prompt.replace("'", "''")

    query = f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            'claude-4-sonnet',
            '{escaped_prompt}'
        ) AS extracted_rates
    """

    try:
        result = conn.cursor().execute(query).fetchone()
        if not result or not result[0]:
            return []

        response = result[0].strip()
        # Extract JSON from possible markdown code blocks
        if response.startswith("```"):
            lines = response.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response = "\n".join(lines).strip()

        rates = json.loads(response)
        return rates if isinstance(rates, list) else []
    except (json.JSONDecodeError, Exception):
        return []


def save_extracted_rates(conn, contract_id: int, manufacturer: str,
                         rates: list[dict], effective_date: date = None):
    """Save AI-extracted rates to TB_CONTRACT_RATES after user confirmation."""
    cur = conn.cursor()
    for rate in rates:
        category = rate.get("category", "ALL")
        rate_type = rate.get("rate_type", "PERCENTAGE")
        rate_value = rate.get("rate_value", 0)
        vol_min = rate.get("volume_min")
        vol_max = rate.get("volume_max")
        notes = rate.get("notes", "")

        safe_cat = str(category).replace("'", "''") if category else "ALL"
        safe_notes = str(notes).replace("'", "''") if notes else ""
        safe_mfr = manufacturer.replace("'", "''")
        eff_str = f"'{effective_date.strftime('%Y-%m-%d')}'" if effective_date else "NULL"

        insert_sql = f"""
            INSERT INTO {RATES_TABLE}
                (CONTRACT_ID, MANUFACTURER, CATEGORY, RATE_TYPE, RATE_VALUE,
                 VOLUME_TIER_MIN, VOLUME_TIER_MAX, EFFECTIVE_DATE, NOTES)
            VALUES (
                {contract_id}, '{safe_mfr}', '{safe_cat}', '{rate_type}', {rate_value},
                {vol_min if vol_min else 'NULL'}, {vol_max if vol_max else 'NULL'},
                {eff_str}, '{safe_notes}'
            )
        """
        cur.execute(insert_sql)


# ─── Contract Queries ────────────────────────────────────────────────────────


@st.cache_data(ttl=300, show_spinner=False)
def get_contracts(_conn, manufacturer: str = None) -> pd.DataFrame:
    """Get all contracts, optionally filtered by manufacturer."""
    where = "WHERE 1=1"
    if manufacturer:
        safe = manufacturer.replace("'", "''")
        where += f" AND MANUFACTURER = '{safe}'"

    query = f"""
        SELECT CONTRACT_ID, MANUFACTURER, CONTRACT_NAME, EFFECTIVE_DATE,
               EXPIRATION_DATE, STATUS, UPLOADED_BY, UPLOADED_AT
        FROM {CONTRACTS_TABLE}
        {where}
        ORDER BY UPLOADED_AT DESC
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=300, show_spinner=False)
def get_contract_rates(_conn, contract_id: int = None, manufacturer: str = None) -> pd.DataFrame:
    """Get rates for a specific contract or manufacturer."""
    where = "WHERE 1=1"
    if contract_id:
        where += f" AND CONTRACT_ID = {contract_id}"
    if manufacturer:
        safe = manufacturer.replace("'", "''")
        where += f" AND MANUFACTURER = '{safe}'"

    query = f"""
        SELECT RATE_ID, CONTRACT_ID, MANUFACTURER, CATEGORY, RATE_TYPE,
               RATE_VALUE, VOLUME_TIER_MIN, VOLUME_TIER_MAX, EFFECTIVE_DATE, NOTES
        FROM {RATES_TABLE}
        {where}
        ORDER BY MANUFACTURER, CATEGORY
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


@st.cache_data(ttl=300, show_spinner=False)
def get_contract_manufacturers(_conn) -> list:
    """Get distinct manufacturers that have contracts."""
    query = f"SELECT DISTINCT MANUFACTURER FROM {CONTRACTS_TABLE} ORDER BY MANUFACTURER"
    df = _conn.cursor().execute(query).fetch_pandas_all()
    return df["MANUFACTURER"].tolist() if not df.empty else []


# ─── Commission Comparison ───────────────────────────────────────────────────


@st.cache_data(ttl=600, show_spinner=False)
def get_historical_sales(_conn, manufacturer: str, territory_filter: str,
                         months: int = 12) -> pd.DataFrame:
    """
    Get rolling N months of sales by category for a manufacturer.
    Used as the basis for commission projections.
    """
    safe_mfr = manufacturer.replace("'", "''")
    query = f"""
        SELECT
            CATEGORY,
            SUM(TRY_TO_DOUBLE(DOLLARS)) AS TOTAL_DOLLARS,
            SUM(TRY_TO_DOUBLE(QTY)) AS TOTAL_CASES,
            SUM(TRY_TO_DOUBLE(NETWEIGHT)) AS TOTAL_LBS,
            SUM(TRY_TO_DOUBLE(COMM)) AS ACTUAL_COMMISSION,
            COUNT(DISTINCT ORDERNUMBER) AS ORDER_COUNT
        FROM {ORDER_VIEW}
        WHERE MANUFACTURERNAME = '{safe_mfr}'
          AND {territory_filter}
          AND {PARSE_DATE} >= DATEADD('MONTH', -{months}, CURRENT_DATE())
          AND {PARSE_DATE} IS NOT NULL
          AND (TRY_TO_DOUBLE(DOLLARS) IS NULL OR TRY_TO_DOUBLE(DOLLARS) < 1000000)
        GROUP BY CATEGORY
        HAVING SUM(TRY_TO_DOUBLE(DOLLARS)) > 0
        ORDER BY TOTAL_DOLLARS DESC
    """
    return _conn.cursor().execute(query).fetch_pandas_all()


def calculate_commission(sales_df: pd.DataFrame, rates: list[dict],
                         volume_adjustment: float = 1.0) -> pd.DataFrame:
    """
    Apply commission rates to historical sales data to project commission.

    Args:
        sales_df: DataFrame with CATEGORY, TOTAL_DOLLARS, TOTAL_CASES, TOTAL_LBS columns
        rates: list of rate dicts from TB_CONTRACT_RATES or user input
        volume_adjustment: multiplier for what-if (e.g., 1.1 = +10% sales)

    Returns:
        DataFrame with projected commission per category
    """
    if sales_df.empty:
        return pd.DataFrame()

    results = []
    # Build rate lookup: category → rate info
    rate_lookup = {}
    flat_rate = None
    for r in rates:
        cat = r.get("category", "ALL") or "ALL"
        if cat.upper() == "ALL":
            flat_rate = r
        else:
            rate_lookup[cat.upper()] = r

    for _, row in sales_df.iterrows():
        category = row["CATEGORY"] or "Unknown"
        dollars = (row.get("TOTAL_DOLLARS") or 0) * volume_adjustment
        cases = (row.get("TOTAL_CASES") or 0) * volume_adjustment
        lbs = (row.get("TOTAL_LBS") or 0) * volume_adjustment

        # Find applicable rate: exact category match → flat rate → 0
        rate_info = rate_lookup.get(category.upper(), flat_rate)

        if rate_info:
            rate_type = rate_info.get("rate_type", "PERCENTAGE")
            rate_value = float(rate_info.get("rate_value", 0))

            if rate_type == "PERCENTAGE":
                commission = dollars * (rate_value / 100)
            elif rate_type == "FLAT_PER_CASE":
                commission = cases * rate_value
            elif rate_type == "FLAT_PER_LB":
                commission = lbs * rate_value
            else:
                commission = dollars * (rate_value / 100)
        else:
            rate_value = 0
            rate_type = "NONE"
            commission = 0

        results.append({
            "Category": category,
            "Sales $": dollars,
            "Cases": cases,
            "Rate Type": rate_type,
            "Rate %": rate_value if rate_type == "PERCENTAGE" else None,
            "Projected Commission": commission,
        })

    return pd.DataFrame(results)


def compare_contracts(sales_df: pd.DataFrame, old_rates: list[dict],
                      new_rates: list[dict], volume_adjustment: float = 1.0) -> pd.DataFrame:
    """
    Compare commission projections between old and new contract rates.
    Returns DataFrame with per-category comparison.
    """
    old_proj = calculate_commission(sales_df, old_rates, volume_adjustment)
    new_proj = calculate_commission(sales_df, new_rates, volume_adjustment)

    if old_proj.empty and new_proj.empty:
        return pd.DataFrame()

    # Merge on category
    comparison = old_proj[["Category", "Sales $", "Projected Commission"]].rename(
        columns={"Projected Commission": "Old Commission"}
    )

    if not new_proj.empty:
        comparison = comparison.merge(
            new_proj[["Category", "Projected Commission", "Rate %"]].rename(
                columns={"Projected Commission": "New Commission", "Rate %": "New Rate %"}
            ),
            on="Category", how="outer"
        )
    else:
        comparison["New Commission"] = 0
        comparison["New Rate %"] = 0

    # Add old rate for display
    old_rate_lookup = {}
    for r in old_rates:
        cat = (r.get("category") or "ALL").upper()
        old_rate_lookup[cat] = r.get("rate_value", 0)

    flat_old = old_rate_lookup.get("ALL", 0)
    comparison["Old Rate %"] = comparison["Category"].apply(
        lambda c: old_rate_lookup.get(c.upper(), flat_old) if c else flat_old
    )

    comparison["Delta $"] = comparison["New Commission"].fillna(0) - comparison["Old Commission"].fillna(0)
    comparison["Delta %"] = comparison.apply(
        lambda r: ((r["New Commission"] - r["Old Commission"]) / r["Old Commission"] * 100)
        if r["Old Commission"] and r["Old Commission"] > 0 else 0, axis=1
    )

    return comparison.sort_values("Sales $", ascending=False)
