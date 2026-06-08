"""
Natural language query integration using Cortex Complete.
Sends user questions to Cortex Complete to generate SQL, validates the output,
and executes it with safety guardrails (read-only, row-limited, access-scoped).
"""
import re
import pandas as pd
import streamlit as st


# SQL keywords that indicate destructive operations — reject these
_FORBIDDEN_KEYWORDS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|MERGE|GRANT|REVOKE|'
    r'COPY\s+INTO|PUT|REMOVE|CALL|EXECUTE\s+TASK|EXECUTE\s+IMMEDIATE)\b',
    re.IGNORECASE
)

# Maximum rows returned from AI-generated queries
_MAX_ROWS = 1000

# Query timeout in seconds
_QUERY_TIMEOUT = 30


def _validate_generated_sql(sql: str) -> str | None:
    """
    Validate AI-generated SQL for safety.
    Returns None if valid, or an error message if rejected.
    """
    if not sql or not sql.strip():
        return "Empty SQL generated"

    # Reject DML/DDL
    match = _FORBIDDEN_KEYWORDS.search(sql)
    if match:
        return f"Rejected: query contains forbidden keyword '{match.group()}'. Only SELECT queries are allowed."

    # Must start with SELECT (after stripping whitespace and CTEs)
    cleaned = sql.strip().upper()
    if not (cleaned.startswith("SELECT") or cleaned.startswith("WITH")):
        return "Rejected: query must be a SELECT statement"

    return None


def _enforce_limit(sql: str, max_rows: int = _MAX_ROWS) -> str:
    """Ensure the query has a LIMIT clause to prevent runaway result sets."""
    # Check if there's already a LIMIT at the end
    if re.search(r'\bLIMIT\s+\d+\s*$', sql, re.IGNORECASE):
        return sql
    return f"{sql.rstrip().rstrip(';')}\nLIMIT {max_rows}"


def ask_cortex_analyst(conn, question: str, territory_filter: str) -> tuple[pd.DataFrame | None, str | None]:
    """
    Send a natural language question to Cortex Complete for SQL generation.
    Returns (result_dataframe, sql_used) or (None, error_message).

    Safety guardrails:
    - Rejects DML/DDL (INSERT, UPDATE, DELETE, DROP, etc.)
    - Enforces LIMIT to prevent massive result sets
    - 30-second query timeout
    - Access filter injected via prompt context
    """
    # Add territory context to the question
    if territory_filter and territory_filter != "1=1":
        context_question = f"{question} (only include data where {territory_filter})"
    else:
        context_question = question

    try:
        # Use Snowflake's built-in Cortex Complete via SQL
        escaped_question = context_question.replace("'", "''")
        analyst_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                'claude-4-sonnet',
                CONCAT(
                    'You are a SQL expert. Generate a Snowflake SQL query to answer: ',
                    '{escaped_question}',
                    '. Use table DB_NXT.SCH_NXT.VW_MYORDERDETAIL_ALL. ',
                    'Columns: MANUFACTURERNAME, DISTRIBUTORNAME, PARENT_DISTRIBUTOR, ORDERNUMBER, ORDERDATE (VARCHAR MM/DD/YYYY format - use TRY_TO_DATE(ORDERDATE, ''MM/DD/YYYY'')), ',
                    'SHIPDATE, INVOICEDATE, CATEGORY, SKU, DESCRIPTION, QTY (VARCHAR - use TRY_TO_DOUBLE), ',
                    'NETWEIGHT (VARCHAR - use TRY_TO_DOUBLE), PRICE (VARCHAR - use TRY_TO_DOUBLE), ',
                    'DOLLARS (VARCHAR - use TRY_TO_DOUBLE), COMM (VARCHAR - use TRY_TO_DOUBLE), ',
                    'SALESREPNAME, SHIPTONAME, OFFICENAME, ',
                    'REGIONNAME, TERRITORYNAME, ORDERSTATUS. ',
                    'Return ONLY the SQL query, no explanation. Round dollars to 2 decimals. ',
                    'IMPORTANT: Generate only SELECT queries. Never use INSERT, UPDATE, DELETE, or DROP. ',
                    'Always include LIMIT 50 unless doing COUNT/SUM aggregation.'
                )
            ) AS generated_sql
        """

        result = conn.cursor().execute(analyst_query).fetch_pandas_all()

        if result.empty:
            return None, "No response from Cortex AI"

        generated_sql = result.iloc[0]["GENERATED_SQL"]

        # Clean up the response - extract SQL from markdown code blocks if present
        generated_sql = generated_sql.strip()
        if generated_sql.startswith("```"):
            lines = generated_sql.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            generated_sql = "\n".join(lines).strip()

        # --- SAFETY VALIDATION ---
        validation_error = _validate_generated_sql(generated_sql)
        if validation_error:
            return None, validation_error

        # Enforce row limit
        generated_sql = _enforce_limit(generated_sql)

        # Execute with timeout
        cur = conn.cursor()
        cur.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {_QUERY_TIMEOUT}")
        df = cur.execute(generated_sql).fetch_pandas_all()

        return df, generated_sql

    except Exception as e:
        error_msg = str(e)
        if "SQL compilation error" in error_msg:
            return None, f"Generated SQL had an error. Try rephrasing your question.\n\nError: {error_msg[:200]}"
        if "timeout" in error_msg.lower() or "cancel" in error_msg.lower():
            return None, "Query took too long (>30s). Try a more specific question or add filters."
        return None, f"Error: {error_msg[:300]}"
