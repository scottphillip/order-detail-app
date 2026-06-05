"""
Floating chatbot widget that appears in the bottom-right corner of every page.
Uses Snowflake Cortex Complete to answer natural language questions about scorecard data.
Injected via st.components.v1.html() as a fixed-position overlay.
"""
import streamlit as st
import streamlit.components.v1 as components


def render_floating_chatbot(conn):
    """
    Render a floating chatbot icon in the bottom-right corner.
    When clicked, expands to a chat panel. Uses query params for communication.
    """
    # Check if there's a pending question from the chatbot
    query_params = st.query_params
    chatbot_q = None
    if "chatbot_q" in query_params:
        from urllib.parse import unquote
        chatbot_q = unquote(query_params["chatbot_q"])
        del st.query_params["chatbot_q"]

    # Process pending question
    if chatbot_q and conn:
        _process_chatbot_question(conn, chatbot_q)

    # Render the floating widget HTML
    components.html(_get_chatbot_html(), height=0)


def _process_chatbot_question(conn, question: str):
    """Process a chatbot question and display result in an expander."""
    with st.expander("💬 Chatbot Response", expanded=True):
        try:
            escaped_q = question.replace("'", "''")
            sql = f"""
                SELECT SNOWFLAKE.CORTEX.COMPLETE(
                    'claude-4-sonnet',
                    CONCAT(
                        'You are a SQL expert for Snowflake. Generate a SQL query to answer: ',
                        '{escaped_q}',
                        '. Use table DB_PROD_CSM.SCH_CSM_SCORECARD.TB_SCORECARD_BI_EXPORT. ',
                        'Key columns: CLIENT_NAME, REFERENCE_CUSTOMER_NAME, REFERENCE_PARENT_DISTRIBUTOR, ',
                        'ITEM_NUMBER, ITEM_DESCRIPTION, ITEM_CATEGORY, DATA_YEAR, DATA_MONTH, ',
                        'CASES (units), DOLLARS (revenue), LBS (weight), ',
                        'REFERENCE_REGION, REFERENCE_LOCAL_MARKET, REFERENCE_STATE. ',
                        'DATA_YEAR is numeric. DATA_MONTH is 1-12. ',
                        'Return ONLY SQL, no markdown. Limit 30 rows. Round DOLLARS to 2 decimals.'
                    )
                ) AS GENERATED_SQL
            """
            result = conn.cursor().execute(sql).fetch_pandas_all()
            if not result.empty:
                gen_sql = result.iloc[0]["GENERATED_SQL"].strip()
                if gen_sql.startswith("```"):
                    lines = gen_sql.split("\n")
                    lines = [l for l in lines if not l.strip().startswith("```")]
                    gen_sql = "\n".join(lines).strip()

                df = conn.cursor().execute(gen_sql).fetch_pandas_all()
                st.markdown(f"**Q:** {question}")
                if not df.empty:
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("No results found.")
                with st.expander("SQL", expanded=False):
                    st.code(gen_sql, language="sql")
        except Exception as e:
            st.error(f"Error: {str(e)[:200]}")


def _get_chatbot_html() -> str:
    """Return the floating chatbot widget HTML/CSS/JS."""
    return """
    <style>
        #chatbot-fab {
            position: fixed;
            bottom: 24px;
            right: 24px;
            z-index: 999999;
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: #F5921E;
            color: white;
            border: none;
            cursor: pointer;
            font-size: 24px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: transform 0.2s, background 0.2s;
        }
        #chatbot-fab:hover {
            transform: scale(1.1);
            background: #e0820a;
        }
        #chatbot-panel {
            position: fixed;
            bottom: 90px;
            right: 24px;
            z-index: 999998;
            width: 360px;
            max-height: 420px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.2);
            display: none;
            flex-direction: column;
            overflow: hidden;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        }
        #chatbot-panel.open { display: flex; }
        #chatbot-header {
            background: #2D2D2D;
            color: white;
            padding: 12px 16px;
            font-size: 14px;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        #chatbot-header .close-btn {
            background: none; border: none; color: #aaa;
            font-size: 18px; cursor: pointer;
        }
        #chatbot-body {
            flex: 1;
            padding: 16px;
            overflow-y: auto;
            max-height: 300px;
        }
        #chatbot-body p {
            color: #666; font-size: 13px; margin: 0 0 8px 0;
        }
        #chatbot-body .example {
            background: #f5f5f5; border-radius: 8px; padding: 8px 12px;
            margin: 4px 0; cursor: pointer; font-size: 12px; color: #333;
            transition: background 0.2s;
        }
        #chatbot-body .example:hover { background: #ede4d9; }
        #chatbot-input-area {
            border-top: 1px solid #eee;
            padding: 8px 12px;
            display: flex;
            gap: 8px;
        }
        #chatbot-input {
            flex: 1;
            border: 1px solid #ddd;
            border-radius: 20px;
            padding: 8px 14px;
            font-size: 13px;
            outline: none;
        }
        #chatbot-input:focus { border-color: #F5921E; }
        #chatbot-send {
            background: #F5921E;
            color: white;
            border: none;
            border-radius: 50%;
            width: 32px;
            height: 32px;
            cursor: pointer;
            font-size: 14px;
        }
    </style>
    
    <button id="chatbot-fab" onclick="toggleChatbot()">💬</button>
    
    <div id="chatbot-panel">
        <div id="chatbot-header">
            <span>Ask Scorecard Data</span>
            <button class="close-btn" onclick="toggleChatbot()">✕</button>
        </div>
        <div id="chatbot-body">
            <p>Ask a question about your scorecard data:</p>
            <div class="example" onclick="askQuestion(this.textContent)">Top 10 clients by cases this year</div>
            <div class="example" onclick="askQuestion(this.textContent)">Monthly trend for Brakebush 2026</div>
            <div class="example" onclick="askQuestion(this.textContent)">Which categories are declining?</div>
            <div class="example" onclick="askQuestion(this.textContent)">Total cases by region 2026</div>
        </div>
        <div id="chatbot-input-area">
            <input id="chatbot-input" type="text" placeholder="Type your question..."
                   onkeydown="if(event.key==='Enter')sendQuestion()">
            <button id="chatbot-send" onclick="sendQuestion()">→</button>
        </div>
    </div>
    
    <script>
    function toggleChatbot() {
        document.getElementById('chatbot-panel').classList.toggle('open');
    }
    function askQuestion(text) {
        document.getElementById('chatbot-input').value = text;
        sendQuestion();
    }
    function sendQuestion() {
        const input = document.getElementById('chatbot-input');
        const q = input.value.trim();
        if (!q) return;
        input.value = '';
        // Navigate to Ask Data tab with the question
        const url = new URL(window.parent.location);
        url.searchParams.set('chatbot_q', encodeURIComponent(q));
        window.parent.location.href = url.toString();
    }
    </script>
    """
