"""
Authentication and access control utilities.
Determines user access tier based on Office 365 directory data.
"""
import re
import streamlit as st


def authenticate_user(email: str, conn) -> dict | None:
    """
    Validate email against Office 365 directory and return user info.
    Returns None if user not found.
    """
    email = email.strip().lower()
    if not email.endswith("@affinitysales.com"):
        return None

    query = f"""
        SELECT 
            DISPLAY_NAME, MAIL, DEPARTMENT, OFFICE_LOCATION, JOB_TITLE
        FROM DB_PROD_RAW.SCH_CRM_SHAREPOINT.V_OFFICE365_USERS
        WHERE LOWER(MAIL) = '{email}'
          AND ACCOUNT_ENABLED = TRUE
        LIMIT 1
    """
    cur = conn.cursor()
    cur.execute(query)
    df = cur.fetch_pandas_all()

    if df.empty:
        return None

    row = df.iloc[0]
    user = {
        "DISPLAY_NAME": row["DISPLAY_NAME"],
        "MAIL": row["MAIL"],
        "DEPARTMENT": row["DEPARTMENT"] or "",
        "OFFICE_LOCATION": row["OFFICE_LOCATION"] or "",
        "JOB_TITLE": row["JOB_TITLE"] or "",
    }
    user["access_tier"] = _determine_access_tier(user)
    return user


def _determine_access_tier(user: dict) -> str:
    """
    Three-tier access:
      - 'full': President, CEO, or Corporate (ACP) department
      - 'department': VP, Vice President, Director
      - 'territory': Everyone else (filtered by OFFICE_LOCATION)
    """
    title = (user.get("JOB_TITLE") or "").lower()
    dept = (user.get("DEPARTMENT") or "").upper()

    # Full access
    if "president" in title or "ceo" in title or dept == "ACP":
        return "full"

    # Department-wide access
    if "vice president" in title or "vp " in title or title.startswith("vp") or "director" in title:
        return "department"

    # Territory-level (default)
    return "territory"


def get_access_filter(user: dict) -> str:
    """
    Build a SQL WHERE clause fragment to filter order data
    based on the user's access tier.
    """
    tier = user.get("access_tier", "territory")
    dept = (user.get("DEPARTMENT") or "").upper()
    office = user.get("OFFICE_LOCATION") or ""

    if tier == "full":
        return "1=1"

    if tier == "department":
        if dept:
            return f"TERRITORYNAME LIKE '{dept} - %'"
        return "1=1"

    # Territory level: match OFFICE_LOCATION to territory suffix
    if not office:
        # No office location, fall back to department filter
        if dept:
            return f"TERRITORYNAME LIKE '{dept} - %'"
        return "1=1"

    # Split multi-location values (e.g., "Metro NY/ Eastern PA" or "CA, AZ, NV, HI")
    locations = [loc.strip() for loc in re.split(r"[/,]", office) if loc.strip()]

    if len(locations) == 1:
        return f"TERRITORYNAME LIKE '%{locations[0]}%'"

    conditions = [f"TERRITORYNAME LIKE '%{loc}%'" for loc in locations]
    return f"({' OR '.join(conditions)})"


def get_access_display(user: dict) -> str:
    """Human-readable access level description."""
    tier = user.get("access_tier", "territory")
    if tier == "full":
        return "Full Access (All Regions)"
    elif tier == "department":
        dept = user.get("DEPARTMENT", "")
        return f"Department Access ({dept} - All Territories)"
    else:
        office = user.get("OFFICE_LOCATION", "")
        return f"Territory Access ({office})"
