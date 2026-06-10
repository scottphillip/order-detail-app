"""
Commission Import Tool - Process manufacturer commission files into Telus import format.
Allows the reconciliation team to upload commission files, resolve reference misses,
and download formatted import files without running desktop scripts.
"""
import streamlit as st
import pandas as pd
from datetime import datetime

from utils.auth import get_access_display
from utils.connection import get_nxt_connection
from utils.invoice_import import (
    EXPORT_HEADERS,
    write_export_bytes,
    coverage_label_from_dates,
    customer_lookup_key,
    ProcessResult,
)

st.set_page_config(
    page_title="Commission Import | Affinity Insights",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Auth Guard
if "user" not in st.session_state:
    st.warning("Please sign in from the home page.")
    st.stop()

user = st.session_state.user

# Header
st.markdown("""
<div style="background: #2D2D2D; padding: 12px 20px; border-radius: 8px; margin-bottom: 15px;">
    <span style="color: #9C27B0; font-size: 18px; font-weight: bold;">COMMISSION IMPORT</span>
    <span style="color: #AAAAAA; font-size: 13px; margin-left: 12px;">Telus ServerSideInvoiceImport File Builder</span>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown(f"### {user['DISPLAY_NAME']}")
    st.caption(get_access_display(user))
    st.markdown("---")
    if st.button("← Back to Home", use_container_width=True):
        st.switch_page("app.py")

# Client configuration
CLIENTS = {
    "Baker Boy": {
        "mfr_code": "BAKERBOY",
        "user": "LisaFMS",
        "file_types": [".xlsx", ".xlsm", ".zip"],
        "description": "Commission DETAIL workbooks (Excel .xlsx/.xlsm or .zip archives)",
    },
    "Reser": {
        "mfr_code": "RESE",
        "user": "pmgljackson",
        "file_types": [".xlsx"],
        "description": "Commission workbook with region-split invoices",
    },
    "McCormick": {
        "mfr_code": "MCCO",
        "user": "CINDYTFMS",
        "file_types": [".xlsx", ".csv"],
        "description": "Debit/Credit/Invoice commission files",
    },
    "Maple Leaf Farms": {
        "mfr_code": "MAPL",
        "user": "kspencerANE",
        "file_types": [".xlsx", ".csv"],
        "description": "Commission invoices with product catalog lookup",
    },
    "Parway (PLZ)": {
        "mfr_code": "PAR",
        "user": "CINDYTFMS",
        "file_types": [".xlsx"],
        "description": "PLZ earnings sheet",
    },
    "Lactalis": {
        "mfr_code": "LACTALIS",
        "user": "LisaFMS",
        "file_types": [".xlsx", ".xls", ".zip"],
        "description": "Monthly zip with broker detail sheets",
    },
}


def get_connection():
    """Get Snowflake connection for reference lookups."""
    return get_nxt_connection()


@st.cache_data(ttl=300, show_spinner=False)
def load_references(_conn, client: str) -> pd.DataFrame:
    """Load reference mappings for a client from Snowflake."""
    query = f"""
        SELECT LOOKUP_KEY, DISPLAY_NAME, DIST_CODE, SHIP_TO, PRICE_MODE, PRICE_LIST, OFFICE_CODE, REGION
        FROM DB_PROD_TRF.SCH_TRF_UTILS.TB_INVOICE_IMPORT_REFERENCES
        WHERE CLIENT = '{client}' AND IS_ACTIVE = TRUE
        ORDER BY DISPLAY_NAME
    """
    return pd.read_sql(query, _conn)


def log_import_run(conn, client: str, file_names: list, rows_parsed: int, rows_exported: int, ref_misses: int, status: str, notes: str = ""):
    """Log an import run to history table."""
    files_str = ", ".join(file_names)[:4000]
    notes_safe = notes.replace("'", "''")[:4000]
    cursor = conn.cursor()
    cursor.execute(f"""
        INSERT INTO DB_PROD_TRF.SCH_TRF_UTILS.TB_INVOICE_IMPORT_HISTORY 
        (CLIENT, USER_EMAIL, FILE_NAMES, ROWS_PARSED, ROWS_EXPORTED, REFERENCE_MISSES, STATUS, NOTES)
        VALUES ('{client}', '{user["EMAIL"]}', '{files_str}', {rows_parsed}, {rows_exported}, {ref_misses}, '{status}', '{notes_safe}')
    """)


# ============================================================
# TABS
# ============================================================

tab_upload, tab_references, tab_history = st.tabs(["Upload & Process", "Reference Manager", "Import History"])

# ============================================================
# TAB 1: UPLOAD & PROCESS
# ============================================================
with tab_upload:
    col1, col2 = st.columns([1, 2])
    
    with col1:
        selected_client = st.selectbox("Select Client", list(CLIENTS.keys()))
        client_config = CLIENTS[selected_client]
        st.caption(client_config["description"])
        st.markdown(f"**MFR Code:** `{client_config['mfr_code']}`")
        st.markdown(f"**Import User:** `{client_config['user']}`")
    
    with col2:
        uploaded_files = st.file_uploader(
            "Upload Commission File(s)",
            type=["xlsx", "xlsm", "xls", "csv", "zip"],
            accept_multiple_files=True,
            help=f"Accepted formats: {', '.join(client_config['file_types'])}"
        )

    if uploaded_files:
        st.markdown("---")
        
        if st.button("Process Files", type="primary", use_container_width=True):
            with st.spinner(f"Processing {len(uploaded_files)} file(s) for {selected_client}..."):
                try:
                    # Import the appropriate processor
                    if selected_client == "Baker Boy":
                        from utils.processors.baker_boy import process_baker_boy
                        conn = get_connection()
                        refs_df = load_references(conn, "BAKER_BOY")
                        result = process_baker_boy(uploaded_files, refs_df)
                    else:
                        st.warning(f"{selected_client} processor not yet available. Baker Boy is ready.")
                        st.stop()
                    
                    # Display results
                    st.session_state["import_result"] = result
                    st.session_state["import_client"] = selected_client
                    
                except Exception as e:
                    st.error(f"Processing failed: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())
        
        # Show results if available
        if "import_result" in st.session_state and st.session_state.get("import_client") == selected_client:
            result = st.session_state["import_result"]
            
            st.markdown("### Results")
            
            # Metrics
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Files Processed", len(result.files_processed))
            m2.metric("Detail Lines", f"{len(result.rows):,}")
            m3.metric("Reference Misses", len(result.reference_misses))
            m4.metric("Warnings", len(result.warnings))
            
            # Warnings
            if result.warnings:
                with st.expander(f"Warnings ({len(result.warnings)})"):
                    for w in result.warnings:
                        st.warning(w)
            
            # Reference misses
            if result.reference_misses:
                with st.expander(f"Unmatched Customers ({len(result.reference_misses)})", expanded=True):
                    st.caption("These customers are not in the reference table. Add them in the Reference Manager tab.")
                    miss_data = []
                    for key, info in result.reference_misses.items():
                        miss_data.append({
                            "Customer Name": info.get("customer_name", key),
                            "Lines": info.get("line_count", 0),
                            "Reason": info.get("reason", "Not found"),
                        })
                    st.dataframe(pd.DataFrame(miss_data), use_container_width=True, hide_index=True)
            
            # Download button
            if result.rows:
                can_export = len(result.reference_misses) == 0
                
                if not can_export:
                    st.warning(
                        f"{len(result.reference_misses)} customer(s) have no distributor mapping. "
                        "Add them in the Reference Manager tab, then re-process."
                    )
                
                label = coverage_label_from_dates(result.dates_seen)
                filename = f"{client_config['mfr_code']}_{label}_Combined_Import.xlsx"
                
                xlsx_bytes, rows_written = write_export_bytes(
                    result.rows,
                    user=client_config["user"],
                    drop_zeros=True,
                )
                
                if xlsx_bytes:
                    st.download_button(
                        label=f"Download Import File ({rows_written:,} rows)",
                        data=xlsx_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary" if can_export else "secondary",
                        use_container_width=True,
                    )
                    
                    # Log the run
                    try:
                        conn = get_connection()
                        log_import_run(
                            conn, 
                            client_config["mfr_code"],
                            result.files_processed,
                            len(result.rows),
                            rows_written,
                            len(result.reference_misses),
                            "SUCCESS" if can_export else "PARTIAL",
                        )
                    except Exception:
                        pass


# ============================================================
# TAB 2: REFERENCE MANAGER
# ============================================================
with tab_references:
    ref_client = st.selectbox("Client", list(CLIENTS.keys()), key="ref_client_select")
    client_key = CLIENTS[ref_client]["mfr_code"]
    
    conn = get_connection()
    refs_df = load_references(conn, client_key)
    
    st.markdown(f"**{len(refs_df)} active reference mappings** for {ref_client}")
    
    col_search, col_add = st.columns([2, 1])
    
    with col_search:
        search = st.text_input("Search references", placeholder="Type customer name...")
    
    with col_add:
        st.markdown("")
        st.markdown("")
        add_new = st.button("+ Add New Mapping", use_container_width=True)
    
    # Display filtered references
    if search and not refs_df.empty:
        mask = refs_df["DISPLAY_NAME"].str.contains(search, case=False, na=False)
        display_df = refs_df[mask]
    else:
        display_df = refs_df
    
    if not display_df.empty:
        st.dataframe(
            display_df[["DISPLAY_NAME", "DIST_CODE", "SHIP_TO", "PRICE_MODE", "PRICE_LIST"]].rename(columns={
                "DISPLAY_NAME": "Customer Name",
                "DIST_CODE": "Dist Code",
                "SHIP_TO": "Ship To",
                "PRICE_MODE": "Price Mode",
                "PRICE_LIST": "Price List",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No references found. Add mappings using the form below.")
    
    # Add new mapping form
    if add_new:
        st.markdown("---")
        st.markdown("### Add New Reference Mapping")
        
        with st.form("add_ref_form"):
            new_name = st.text_input("Customer Name (as it appears on commission)")
            c1, c2 = st.columns(2)
            new_dist = c1.text_input("Distributor Code (Foodmark)")
            new_ship = c2.text_input("Ship To Code")
            c3, c4 = st.columns(2)
            new_pm = c3.text_input("Price Mode Override", value="")
            new_pl = c4.text_input("Price List Name Override", value="default")
            
            submitted = st.form_submit_button("Save Mapping", type="primary")
            
            if submitted and new_name and new_dist:
                lookup = customer_lookup_key(new_name)
                name_safe = new_name.replace("'", "''")
                cursor = conn.cursor()
                cursor.execute(f"""
                    INSERT INTO DB_PROD_TRF.SCH_TRF_UTILS.TB_INVOICE_IMPORT_REFERENCES
                    (CLIENT, LOOKUP_KEY, DISPLAY_NAME, DIST_CODE, SHIP_TO, PRICE_MODE, PRICE_LIST, ADDED_BY)
                    VALUES ('{client_key}', '{lookup}', '{name_safe}', '{new_dist}', '{new_ship}', '{new_pm}', '{new_pl}', '{user["EMAIL"]}')
                """)
                st.success(f"Added: {new_name} → {new_dist} / {new_ship}")
                load_references.clear()
                st.rerun()


# ============================================================
# TAB 3: IMPORT HISTORY
# ============================================================
with tab_history:
    conn = get_connection()
    history_df = pd.read_sql("""
        SELECT CLIENT, RUN_TIMESTAMP, USER_EMAIL, FILE_NAMES, 
               ROWS_PARSED, ROWS_EXPORTED, REFERENCE_MISSES, STATUS, NOTES
        FROM DB_PROD_TRF.SCH_TRF_UTILS.TB_INVOICE_IMPORT_HISTORY
        ORDER BY RUN_TIMESTAMP DESC
        LIMIT 50
    """, conn)
    
    if not history_df.empty:
        st.dataframe(
            history_df.rename(columns={
                "CLIENT": "Client",
                "RUN_TIMESTAMP": "Date",
                "USER_EMAIL": "User",
                "FILE_NAMES": "Files",
                "ROWS_PARSED": "Parsed",
                "ROWS_EXPORTED": "Exported",
                "REFERENCE_MISSES": "Misses",
                "STATUS": "Status",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No import history yet. Process your first file in the Upload tab!")
