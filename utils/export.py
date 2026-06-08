"""
Export utilities for downloading filtered data as Excel.
"""
import io
import pandas as pd
import streamlit as st
from datetime import datetime


def excel_download_button(df: pd.DataFrame, filename_prefix: str, label: str = "Download Excel"):
    """
    Render a Streamlit download button for a DataFrame as Excel.

    Args:
        df: DataFrame to export
        filename_prefix: Base name for the file (e.g., "order_detail")
        label: Button text
    """
    if df is None or df.empty:
        return

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Data")
    buffer.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d")
    filename = f"{filename_prefix}_{timestamp}.xlsx"

    st.download_button(
        label=label,
        data=buffer,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
