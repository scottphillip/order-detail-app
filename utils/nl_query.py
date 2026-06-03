"""
Natural language query integration using Cortex Analyst REST API.
Sends user questions to Cortex Analyst with the semantic view and returns results.
"""
import json
import requests
import pandas as pd
import streamlit as st


def ask_cortex_analyst(conn, question: str, territory_filter: str) -> tuple[pd.DataFrame | None, str | None]:
    """
    Send a natural language question to Cortex Analyst via the semantic view.
    Returns (result_dataframe, sql_used) or (None, error_message).
    """
    # Add territory context to the question
    if territory_filter and territory_filter != "1=1":
        context_question = f"{question} (only include data where {territory_filter})"
    else:
        context_question = question

    try:
        # Use Snowflake's built-in Cortex Analyst via SQL
        escaped_question = context_question.replace("'", "''")
        analyst_query = f"""
            SELECT SNOWFLAKE.CORTEX.COMPLETE(
                'claude-4-sonnet',
                CONCAT(
                    'You are a SQL expert. Generate a Snowflake SQL query to answer: ',
                    '{escaped_question}',
                    '. Use table DB_PROD_RAW.SCH_CRM_SHAREPOINT.VW_ORDER_DETAIL_APPENDING_WEEKLY. ',
                    'Columns: MANUFACTURERNAME, DISTRIBUTORNAME, ORDERNUMBER, ORDERDATE (VARCHAR MM/DD/YYYY format - use TRY_TO_DATE(ORDERDATE, ''MM/DD/YYYY'')), ',
                    'SHIPDATE, INVOICEDATE, CATEGORY, SKU, DESCRIPTION, QTY (VARCHAR - use TRY_TO_DOUBLE), ',
                    'NETWEIGHT (VARCHAR - use TRY_TO_DOUBLE), PRICE (VARCHAR - use TRY_TO_DOUBLE), ',
                    'DOLLARS (VARCHAR - use TRY_TO_DOUBLE), SALESREPNAME, SHIPTONAME, OFFICENAME, ',
                    'REGIONNAME, TERRITORYNAME, ORDERSTATUS. ',
                    'Return ONLY the SQL query, no explanation. Round dollars to 2 decimals.'
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
            # Remove first and last lines (code block markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            generated_sql = "\n".join(lines).strip()

        # Execute the generated SQL
        df = conn.cursor().execute(generated_sql).fetch_pandas_all()
        return df, generated_sql

    except Exception as e:
        error_msg = str(e)
        if "SQL compilation error" in error_msg:
            return None, f"Generated SQL had an error. Try rephrasing your question.\n\nError: {error_msg[:200]}"
        return None, f"Error: {error_msg[:300]}"
