"""
Scorecard Data Validation Test Script
=====================================
Tests all scorecard data layer functions across different user access personas.
Validates that the app works correctly for every access tier.

Run:
    python tests/test_scorecard_personas.py

Requires: snowflake-connector-python, environment access to Snowflake.
Uses the same secrets as the Streamlit app (.streamlit/secrets.toml).
"""
import sys
import os
import time
from pathlib import Path
from datetime import datetime

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import snowflake.connector
import toml


# ─── Configuration ───
PERSONAS = [
    {
        "name": "Corporate (Full Access)",
        "tier": "full",
        "DEPARTMENT": "ACP",
        "OFFICE_LOCATION": "",
        "JOB_TITLE": "President",
        "DISPLAY_NAME": "Test Corporate",
        "MAIL": "test@affinitysales.com",
    },
    {
        "name": "VP Midwest (Department)",
        "tier": "department",
        "DEPARTMENT": "ACE",
        "OFFICE_LOCATION": "Midwest",
        "JOB_TITLE": "Vice President",
        "DISPLAY_NAME": "Test VP Midwest",
        "MAIL": "test.vp@affinitysales.com",
    },
    {
        "name": "VP Southwest (Department)",
        "tier": "department",
        "DEPARTMENT": "ASW",
        "OFFICE_LOCATION": "",
        "JOB_TITLE": "Vice President",
        "DISPLAY_NAME": "Test VP Southwest",
        "MAIL": "test.sw@affinitysales.com",
    },
    {
        "name": "Rep Indiana (Territory)",
        "tier": "territory",
        "DEPARTMENT": "ACE",
        "OFFICE_LOCATION": "Indiana",
        "JOB_TITLE": "Account Executive",
        "DISPLAY_NAME": "Test Rep Indiana",
        "MAIL": "test.rep@affinitysales.com",
    },
    {
        "name": "Rep Utah (Territory)",
        "tier": "territory",
        "DEPARTMENT": "AWE",
        "OFFICE_LOCATION": "Utah",
        "JOB_TITLE": "Key Account Specialist",
        "DISPLAY_NAME": "Test Rep Utah",
        "MAIL": "test.utah@affinitysales.com",
    },
]


class TestResult:
    def __init__(self, persona_name: str, test_name: str, passed: bool, detail: str = ""):
        self.persona = persona_name
        self.test = test_name
        self.passed = passed
        self.detail = detail

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.persona} | {self.test}: {self.detail}"


def get_connection():
    """Create Snowflake connection using app secrets or environment."""
    # Try .streamlit/secrets.toml first
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        secrets = toml.load(secrets_path)
        sf = secrets["snowflake"]
        return snowflake.connector.connect(
            account=sf["account"],
            user=sf["user"],
            password=sf["password"],
            role=sf["role"],
            warehouse=sf["warehouse"],
            database="DB_PROD_CSM",
        )

    # Fall back to default Snowflake connection (uses ~/.snowflake/connections.toml)
    try:
        return snowflake.connector.connect(
            connection_name="default",
            database="DB_PROD_CSM",
        )
    except Exception:
        pass

    # Fall back to environment variables or config
    import configparser
    config_path = Path.home() / ".snowflake" / "connections.toml"
    if config_path.exists():
        config = toml.load(config_path)
        # Use the default connection
        conn_cfg = config.get("default", config.get(list(config.keys())[0], {}))
        return snowflake.connector.connect(
            account=conn_cfg.get("account", conn_cfg.get("accountname", "")),
            user=conn_cfg.get("user", conn_cfg.get("username", "")),
            password=conn_cfg.get("password", ""),
            role=conn_cfg.get("role", ""),
            warehouse=conn_cfg.get("warehouse", ""),
            database="DB_PROD_CSM",
            authenticator=conn_cfg.get("authenticator", "snowflake"),
        )

    raise FileNotFoundError(
        "No Snowflake credentials found. Provide .streamlit/secrets.toml or ~/.snowflake/connections.toml"
    )


def run_tests():
    """Execute all validation tests for each persona."""
    from utils.scorecard_auth import get_scorecard_access_filter
    from utils.scorecard_data import (
        get_scorecard_years, get_scorecard_clients, get_scorecard_categories,
        get_scorecard_regions, get_scorecard_kpis, get_scorecard_kpis_prior_year,
        get_monthly_trend, get_top_clients, get_client_monthly_trend,
        get_growth_heatmap, get_category_breakdown, get_item_performance,
        get_category_yoy, get_top_customers, get_distributor_brand_split,
        get_parent_distributor_breakdown, get_customer_churn,
        get_client_market_share, get_state_breakdown, get_max_data_month,
    )

    conn = get_connection()
    current_year = datetime.now().year
    results: list[TestResult] = []
    full_access_counts = {}

    print(f"\n{'='*70}")
    print(f" SCORECARD DATA VALIDATION - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}\n")

    for persona in PERSONAS:
        pname = persona["name"]
        print(f"\n{'─'*50}")
        print(f" Testing: {pname}")
        print(f"{'─'*50}")

        # Build user dict (same as auth.py produces)
        user = {
            "DISPLAY_NAME": persona["DISPLAY_NAME"],
            "MAIL": persona["MAIL"],
            "DEPARTMENT": persona["DEPARTMENT"],
            "OFFICE_LOCATION": persona["OFFICE_LOCATION"],
            "JOB_TITLE": persona["JOB_TITLE"],
            "access_tier": persona["tier"],
        }

        access_filter = get_scorecard_access_filter(user)
        print(f"  Filter: {access_filter}")

        # TEST 1: get_scorecard_years returns data
        try:
            years = get_scorecard_years(conn, access_filter)
            passed = len(years) > 0 and current_year in years
            results.append(TestResult(pname, "get_scorecard_years",
                                      passed, f"Found {len(years)} years, current year {'present' if current_year in years else 'MISSING'}"))
        except Exception as e:
            results.append(TestResult(pname, "get_scorecard_years", False, str(e)[:100]))

        # TEST 2: get_scorecard_clients returns data
        try:
            clients = get_scorecard_clients(conn, access_filter)
            passed = len(clients) > 0
            results.append(TestResult(pname, "get_scorecard_clients",
                                      passed, f"Found {len(clients)} clients"))
            if persona["tier"] == "full":
                full_access_counts["clients"] = len(clients)
        except Exception as e:
            results.append(TestResult(pname, "get_scorecard_clients", False, str(e)[:100]))

        # TEST 3: get_max_data_month returns valid month
        try:
            max_month = get_max_data_month(conn, access_filter, current_year, None)
            passed = 1 <= max_month <= 12
            results.append(TestResult(pname, "get_max_data_month",
                                      passed, f"max_month={max_month}"))
        except Exception as e:
            results.append(TestResult(pname, "get_max_data_month", False, str(e)[:100]))

        # TEST 4: KPIs return positive values
        try:
            kpis = get_scorecard_kpis(conn, access_filter, current_year, None, max_month)
            cases = kpis.get("TOTAL_CASES", 0) or 0
            dollars = kpis.get("TOTAL_DOLLARS", 0) or 0
            passed = cases > 0 and dollars > 0
            results.append(TestResult(pname, "get_scorecard_kpis (positive)",
                                      passed, f"Cases={cases:,.0f}, Dollars=${dollars:,.0f}"))
        except Exception as e:
            results.append(TestResult(pname, "get_scorecard_kpis", False, str(e)[:100]))

        # TEST 5: YoY comparison is reasonable (not -50%+ due to partial months)
        try:
            kpis_py = get_scorecard_kpis_prior_year(conn, access_filter, current_year, None, max_month)
            py_cases = kpis_py.get("TOTAL_CASES", 0) or 0
            if py_cases > 0:
                yoy_pct = ((cases - py_cases) / py_cases) * 100
                passed = -50 < yoy_pct < 200  # Reasonable bounds
                results.append(TestResult(pname, "YoY comparison reasonable",
                                          passed, f"YoY Cases: {yoy_pct:+.1f}%"))
            else:
                results.append(TestResult(pname, "YoY comparison reasonable",
                                          False, "Prior year cases = 0"))
        except Exception as e:
            results.append(TestResult(pname, "YoY comparison reasonable", False, str(e)[:100]))

        # TEST 6: Monthly trend has data for all months up to max_month
        try:
            trend = get_monthly_trend(conn, access_filter, (current_year,), None, None)
            if not trend.empty:
                months_with_data = trend[trend["DATA_YEAR"] == current_year]["DATA_MONTH"].unique()
                expected_months = set(range(1, max_month + 1))
                actual_months = set(int(m) for m in months_with_data if m <= max_month)
                missing = expected_months - actual_months
                passed = len(missing) == 0
                results.append(TestResult(pname, "Monthly trend completeness",
                                          passed, f"Months 1-{max_month}: {'all present' if passed else f'missing {missing}'}"))
            else:
                results.append(TestResult(pname, "Monthly trend completeness", False, "Empty result"))
        except Exception as e:
            results.append(TestResult(pname, "Monthly trend completeness", False, str(e)[:100]))

        # TEST 7: Top customers uses REFERENCE_CUSTOMER_NAME
        try:
            cust_df = get_top_customers(conn, access_filter, current_year, None)
            if not cust_df.empty:
                has_ref = "REFERENCE_CUSTOMER_NAME" in cust_df.columns
                no_old = "CUSTOMER_NAME" not in cust_df.columns
                passed = has_ref and no_old
                results.append(TestResult(pname, "Uses REFERENCE_CUSTOMER_NAME",
                                          passed, f"Columns: {list(cust_df.columns)}"))
            else:
                results.append(TestResult(pname, "Uses REFERENCE_CUSTOMER_NAME", False, "Empty result"))
        except Exception as e:
            results.append(TestResult(pname, "Uses REFERENCE_CUSTOMER_NAME", False, str(e)[:100]))

        # TEST 8: Category breakdown returns data
        try:
            cat_df = get_category_breakdown(conn, access_filter, current_year, None)
            passed = not cat_df.empty and len(cat_df) > 0
            results.append(TestResult(pname, "Category breakdown non-empty",
                                      passed, f"{len(cat_df)} categories" if not cat_df.empty else "Empty"))
        except Exception as e:
            results.append(TestResult(pname, "Category breakdown non-empty", False, str(e)[:100]))

        # TEST 9: Access filter actually restricts data (territory < full)
        if persona["tier"] != "full" and "clients" in full_access_counts:
            passed = len(clients) < full_access_counts["clients"]
            results.append(TestResult(pname, "Access filter restricts data",
                                      passed,
                                      f"{len(clients)} clients (full={full_access_counts['clients']})"))

        # TEST 10: No division by zero or NaN in growth
        try:
            heatmap = get_growth_heatmap(conn, access_filter, current_year, None)
            if not heatmap.empty:
                has_nulls = heatmap["DOLLARS"].isnull().any()
                passed = not has_nulls
                results.append(TestResult(pname, "Heatmap data clean (no NULLs)",
                                          passed, f"Rows={len(heatmap)}, NULLs={'yes' if has_nulls else 'no'}"))
            else:
                results.append(TestResult(pname, "Heatmap data clean", True, "Empty (OK for territory)"))
        except Exception as e:
            results.append(TestResult(pname, "Heatmap data clean", False, str(e)[:100]))

        print(f"  Tests complete for {pname}")

    # ─── Summary ───
    print(f"\n\n{'='*70}")
    print(f" RESULTS SUMMARY")
    print(f"{'='*70}\n")

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"  Total: {total} | Passed: {passed} | Failed: {failed}")
    print(f"  Pass Rate: {(passed/total)*100:.1f}%\n")

    if failed > 0:
        print(f"  {'─'*50}")
        print(f"  FAILURES:")
        print(f"  {'─'*50}")
        for r in results:
            if not r.passed:
                print(f"  {r}")

    print(f"\n  {'─'*50}")
    print(f"  ALL RESULTS:")
    print(f"  {'─'*50}")
    for r in results:
        print(f"  {r}")

    # Write report file
    report_path = Path(__file__).parent / "validation_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Scorecard Validation Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Results:** {passed}/{total} passed ({(passed/total)*100:.1f}%)\n\n")
        f.write(f"## Summary\n\n")
        f.write(f"| Persona | Tests | Passed | Failed |\n")
        f.write(f"|---------|-------|--------|--------|\n")
        for persona in PERSONAS:
            pname = persona["name"]
            p_results = [r for r in results if r.persona == pname]
            p_pass = sum(1 for r in p_results if r.passed)
            p_fail = len(p_results) - p_pass
            f.write(f"| {pname} | {len(p_results)} | {p_pass} | {p_fail} |\n")

        f.write(f"\n## Details\n\n")
        for r in results:
            icon = "✅" if r.passed else "❌"
            f.write(f"- {icon} **{r.persona}** | {r.test}: {r.detail}\n")

    print(f"\n  Report saved to: {report_path}")
    conn.close()
    return failed == 0


if __name__ == "__main__":
    # Need to mock streamlit's cache decorator since we're running outside Streamlit
    import unittest.mock
    mock_cache = unittest.mock.MagicMock(side_effect=lambda **kwargs: lambda fn: fn)
    
    # Patch st.cache_data before importing scorecard_data
    import streamlit as st
    st.cache_data = mock_cache
    
    success = run_tests()
    sys.exit(0 if success else 1)
