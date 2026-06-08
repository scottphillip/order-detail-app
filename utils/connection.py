"""
Centralized Snowflake connection management for Affinity Sales Hub.
All pages should import from here instead of defining their own connections.
"""
import streamlit as st
import snowflake.connector


def _create_connection(database: str) -> snowflake.connector.SnowflakeConnection:
    """Create a fresh Snowflake connection to the specified database."""
    return snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        role=st.secrets["snowflake"]["role"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        database=database,
    )


def get_snowflake_connection(database: str = "DB_NXT", session_key: str = "sf_conn") -> snowflake.connector.SnowflakeConnection:
    """
    Get a Snowflake connection with automatic reconnect on failure.

    Args:
        database: Target database (DB_NXT for order detail, DB_PROD_CSM for scorecard)
        session_key: Session state key to store the connection under

    Returns:
        Active Snowflake connection
    """
    if session_key not in st.session_state or st.session_state[session_key] is None:
        st.session_state[session_key] = _create_connection(database)
    else:
        try:
            st.session_state[session_key].cursor().execute("SELECT 1")
        except Exception:
            st.session_state[session_key] = _create_connection(database)
    return st.session_state[session_key]


def get_nxt_connection() -> snowflake.connector.SnowflakeConnection:
    """Get connection to DB_NXT (Order Detail, Manufacturer Compare, Period Compare)."""
    return get_snowflake_connection(database="DB_NXT", session_key="sf_conn")


def get_csm_connection() -> snowflake.connector.SnowflakeConnection:
    """Get connection to DB_PROD_CSM (Scorecard Analytics)."""
    return get_snowflake_connection(database="DB_PROD_CSM", session_key="sf_conn_csm")
