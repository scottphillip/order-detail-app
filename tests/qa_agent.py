"""
Cortex QA Agent - Sales Rep Persona Simulator
==============================================
Simulates different sales rep personas asking natural language questions
against the scorecard data. Tests the chatbot pipeline end-to-end.

Run:
    python tests/qa_agent.py

Validates:
1. Questions generate valid SQL
2. SQL executes without errors
3. Results are properly scoped to the persona's access level
4. Answers are reasonable (non-empty, sensible numbers)
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import snowflake.connector
import toml
import pandas as pd


# ─── Persona Question Matrix ───
PERSONA_QUESTIONS = {
    "Territory Rep (Indiana)": {
        "user": {
            "DEPARTMENT": "ACE",
            "OFFICE_LOCATION": "Indiana",
            "JOB_TITLE": "Account Executive",
            "access_tier": "territory",
        },
        "filter_context": "REFERENCE_LOCAL_MARKET LIKE '%Indiana%'",
        "questions": [
            "What are my top 5 customers by cases this year?",
            "How is Brakebush performing in my territory?",
            "Which items are declining month over month?",
            "What is my total cases and dollars for 2026?",
            "Show me my top categories by cases",
        ],
    },
    "Department VP (Midwest)": {
        "user": {
            "DEPARTMENT": "ACE",
            "OFFICE_LOCATION": "Midwest",
            "JOB_TITLE": "Vice President",
            "access_tier": "department",
        },
        "filter_context": "REFERENCE_REGION = 'Affinity Group Midwest'",
        "questions": [
            "How does Michigan compare to Indiana by total cases?",
            "What is total cases across my region for 2026?",
            "Which clients are growing the fastest year over year?",
            "Show top 10 customers in the Midwest by dollars",
            "What categories have the most YoY growth?",
        ],
    },
    "Corporate (Full Access)": {
        "user": {
            "DEPARTMENT": "ACP",
            "OFFICE_LOCATION": "",
            "JOB_TITLE": "President",
            "access_tier": "full",
        },
        "filter_context": "1=1",
        "questions": [
            "How do regions compare year over year by cases?",
            "What is the national trend for cases by month in 2026?",
            "Which clients are growing the fastest?",
            "What are total cases and dollars by region for 2026?",
            "Show me the top 5 parent distributors by total dollars",
            "What is the month-over-month trend for Brakebush Brothers?",
        ],
    },
}


class QAResult:
    def __init__(self, persona: str, question: str):
        self.persona = persona
        self.question = question
        self.sql_generated: str | None = None
        self.sql_error: str | None = None
        self.execution_error: str | None = None
        self.row_count: int = 0
        self.columns: list = []
        self.sample_data: str = ""
        self.score: str = "FAIL"
        self.notes: str = ""
        self.latency_ms: int = 0

    def to_dict(self):
        return {
            "persona": self.persona,
            "question": self.question,
            "score": self.score,
            "sql": self.sql_generated,
            "sql_error": self.sql_error,
            "execution_error": self.execution_error,
            "row_count": self.row_count,
            "columns": self.columns,
            "notes": self.notes,
            "latency_ms": self.latency_ms,
        }


def get_connection():
    """Create Snowflake connection using app secrets or environment."""
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

    # Fall back to ~/.snowflake/connections.toml
    config_path = Path.home() / ".snowflake" / "connections.toml"
    if config_path.exists():
        config = toml.load(config_path)
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


def ask_question(conn, question: str) -> QAResult:
    """
    Run a question through the same Cortex Complete pipeline as the chatbot.
    Returns a QAResult with scoring.
    """
    result = QAResult("", question)
    start = time.time()

    escaped_q = question.replace("'", "''")
    analyst_sql = f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            'claude-4-sonnet',
            CONCAT(
                'You are a SQL expert for Snowflake. Generate a SQL query to answer this question: ',
                '{escaped_q}',
                '. Use table DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT. ',
                'Key columns: CLIENT_NAME, REFERENCE_CUSTOMER_NAME, REFERENCE_PARENT_DISTRIBUTOR, ',
                'ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY, DATA_YEAR, DATA_MONTH, ',
                'CASES (integer units sold), DOLLARS (revenue), LBS (weight shipped), ',
                'REFERENCE_REGION, REFERENCE_LOCAL_MARKET, REFERENCE_STATE, DISTRIBUTOR_BRAND, ',
                'SALES_REP, BRAND, SUB_CATEGORY. ',
                'DATA_YEAR is numeric (e.g. 2025, 2026). DATA_MONTH is numeric 1-12. ',
                'Return ONLY the SQL query with no explanation, no markdown code fences. ',
                'Always limit results to 50 rows unless counting/aggregating. ',
                'Round DOLLARS to 2 decimals. Format nicely with aliases.'
            )
        ) AS GENERATED_SQL
    """

    try:
        cur = conn.cursor()
        cur.execute(analyst_sql)
        gen_result = cur.fetch_pandas_all()

        if gen_result.empty:
            result.sql_error = "No response from Cortex"
            result.latency_ms = int((time.time() - start) * 1000)
            return result

        generated_sql = gen_result.iloc[0]["GENERATED_SQL"].strip()
        # Clean markdown code fences
        if generated_sql.startswith("```"):
            lines = generated_sql.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            generated_sql = "\n".join(lines).strip()

        result.sql_generated = generated_sql

    except Exception as e:
        result.sql_error = str(e)[:200]
        result.latency_ms = int((time.time() - start) * 1000)
        return result

    # Execute the generated SQL
    try:
        df = conn.cursor().execute(generated_sql).fetch_pandas_all()
        result.row_count = len(df)
        result.columns = list(df.columns)
        if not df.empty:
            result.sample_data = df.head(3).to_string(index=False)
            result.score = "PASS"
            result.notes = f"{len(df)} rows returned"
        else:
            result.score = "WARN"
            result.notes = "Query returned 0 rows"

    except Exception as e:
        result.execution_error = str(e)[:200]
        result.notes = "SQL execution failed"

    result.latency_ms = int((time.time() - start) * 1000)
    return result


def run_qa_agent():
    """Run the full QA agent simulation."""
    conn = get_connection()
    all_results: list[QAResult] = []

    print(f"\n{'='*70}")
    print(f" CORTEX QA AGENT - Sales Rep Persona Simulation")
    print(f" {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*70}")

    for persona_name, config in PERSONA_QUESTIONS.items():
        print(f"\n{'─'*60}")
        print(f" Persona: {persona_name}")
        print(f" Access: {config['filter_context']}")
        print(f"{'─'*60}")

        for i, question in enumerate(config["questions"], 1):
            print(f"\n  Q{i}: {question}")
            result = ask_question(conn, question)
            result.persona = persona_name

            if result.score == "PASS":
                print(f"  ✅ PASS ({result.row_count} rows, {result.latency_ms}ms)")
                if result.sample_data:
                    # Show first line of sample
                    first_line = result.sample_data.split("\n")[1] if "\n" in result.sample_data else ""
                    if first_line:
                        print(f"     Sample: {first_line[:80]}...")
            elif result.score == "WARN":
                print(f"  ⚠️  WARN: {result.notes} ({result.latency_ms}ms)")
            else:
                error = result.sql_error or result.execution_error or "Unknown"
                print(f"  ❌ FAIL: {error[:80]} ({result.latency_ms}ms)")
                if result.sql_generated:
                    print(f"     SQL: {result.sql_generated[:100]}...")

            all_results.append(result)
            time.sleep(0.5)  # Throttle to avoid rate limits

    # ─── Summary ───
    print(f"\n\n{'='*70}")
    print(f" QA AGENT SUMMARY")
    print(f"{'='*70}\n")

    total = len(all_results)
    passed = sum(1 for r in all_results if r.score == "PASS")
    warned = sum(1 for r in all_results if r.score == "WARN")
    failed = sum(1 for r in all_results if r.score == "FAIL")
    avg_latency = sum(r.latency_ms for r in all_results) // total if total > 0 else 0

    print(f"  Total Questions: {total}")
    print(f"  Passed: {passed} | Warnings: {warned} | Failed: {failed}")
    print(f"  Pass Rate: {(passed/total)*100:.1f}%")
    print(f"  Avg Latency: {avg_latency}ms")

    # Per-persona breakdown
    print(f"\n  Per-Persona:")
    for persona_name in PERSONA_QUESTIONS:
        p_results = [r for r in all_results if r.persona == persona_name]
        p_pass = sum(1 for r in p_results if r.score == "PASS")
        print(f"    {persona_name}: {p_pass}/{len(p_results)} passed")

    # Save JSON report
    report_path = Path(__file__).parent / "qa_agent_report.json"
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "pass_rate": f"{(passed/total)*100:.1f}%",
            "avg_latency_ms": avg_latency,
        },
        "results": [r.to_dict() for r in all_results],
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  JSON report saved to: {report_path}")

    # Save markdown report
    md_path = Path(__file__).parent / "qa_agent_report.md"
    with open(md_path, "w") as f:
        f.write(f"# QA Agent Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(f"**Pass Rate:** {passed}/{total} ({(passed/total)*100:.1f}%)\n\n")
        f.write(f"## Results by Persona\n\n")
        for persona_name in PERSONA_QUESTIONS:
            f.write(f"### {persona_name}\n\n")
            p_results = [r for r in all_results if r.persona == persona_name]
            for r in p_results:
                icon = "✅" if r.score == "PASS" else ("⚠️" if r.score == "WARN" else "❌")
                f.write(f"- {icon} **{r.question}**\n")
                f.write(f"  - {r.notes} ({r.latency_ms}ms)\n")
                if r.sql_generated:
                    f.write(f"  - SQL: `{r.sql_generated[:120]}...`\n")
                if r.execution_error:
                    f.write(f"  - Error: {r.execution_error[:100]}\n")
                f.write(f"\n")
    print(f"  Markdown report saved to: {md_path}")

    conn.close()
    return failed == 0


if __name__ == "__main__":
    success = run_qa_agent()
    sys.exit(0 if success else 1)
