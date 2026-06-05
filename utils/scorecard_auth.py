"""
Access control adapter for Scorecard Analytics.
Maps user tiers (full/department/territory) to REFERENCE_REGION
and REFERENCE_LOCAL_MARKET filters in TB_SCORECARD_BI_EXPORT.
"""
import re

# Department code → REFERENCE_REGION mapping
DEPT_TO_REGION = {
    "ANE": "Affinity Group Northeast",
    "ASE": "Affinity Group Southeast",
    "ASW": "Affinity Group Southwest",
    "AMW": "Affinity Group Midwest",
    "ACE": "Affinity Group Midwest",
    "AWE": "Affinity Group West",
}

SCORECARD_TABLE = "DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT"


def get_scorecard_access_filter(user: dict) -> str:
    """
    Build a SQL WHERE clause fragment to filter scorecard data
    based on the user's access tier.
    Uses REFERENCE_REGION and REFERENCE_LOCAL_MARKET.
    """
    tier = user.get("access_tier", "territory")
    dept = (user.get("DEPARTMENT") or "").upper().strip()
    office = user.get("OFFICE_LOCATION") or ""

    if tier == "full":
        return "1=1"

    if tier == "department":
        # Map department code to region
        region = DEPT_TO_REGION.get(dept)
        if region:
            return f"REFERENCE_REGION = '{region}'"
        # Fallback: try matching department code prefix in LOCAL_MARKET
        if dept:
            return f"REFERENCE_LOCAL_MARKET LIKE '{dept} - %'"
        return "1=1"

    # Territory level: match OFFICE_LOCATION against REFERENCE_LOCAL_MARKET
    if not office:
        if dept:
            return f"REFERENCE_LOCAL_MARKET LIKE '{dept} - %'"
        return "1=1"

    # Split multi-location values (e.g., "Metro NY/ Eastern PA")
    locations = [loc.strip() for loc in re.split(r"[/,]", office) if loc.strip()]

    if len(locations) == 1:
        return f"REFERENCE_LOCAL_MARKET LIKE '%{locations[0]}%'"

    conditions = [f"REFERENCE_LOCAL_MARKET LIKE '%{loc}%'" for loc in locations]
    return f"({' OR '.join(conditions)})"
