from backend.semantic.tools import semantic_lookup as core_semantic_lookup
from backend.data.database import Database
from backend.llm.gemini import LLMClient

# Tool annotations — used by hooks to enforce permission model
TOOL_ANNOTATIONS = {
    "semantic_lookup":  {"access": "read-only",                   "idempotent": True},
    "query_generate":   {"access": "read-only",                   "idempotent": False},
    "data_retrieve":    {"access": "read-only, external-network",  "idempotent": True},
    "viz_select":       {"access": "read-only",                   "idempotent": True},
    "insight_generate": {"access": "read-only",                   "idempotent": False},
}


def semantic_lookup(search_term: str, session_id: str = None) -> str:
    """
    [read-only] Maps business terms to semantic model fields deterministically.
    Input:  search_term — space/comma separated business terms
            session_id  — if set, uses the session's auto-discovered semantic model
    Output: JSON string with matched columns, KPI definitions, date filter hints
    Error:  Returns a plain string describing available terms
    """
    from backend.semantic.tools import semantic_lookup as _do_lookup
    return _do_lookup(search_term, session_id=session_id)


def query_generate(intent: str, semantic_mapping: str, error_context: str = "") -> str:
    """
    [read-only] Generates DuckDB SQL from user intent and semantic mapping via LLM.
    Input:  intent, semantic_mapping, optional error_context from previous failed attempt
    Output: SQL string (SELECT only)
    Error:  Raises RuntimeError if LLM call fails
    """
    client = LLMClient()
    prompt = f"""
You are an expert DuckDB SQL analyst. Generate a single, complete, valid DuckDB SQL query.

User Intent: {intent}
Semantic Mapping (tables, columns, foreign keys): {semantic_mapping}

=== STRICT OUTPUT RULES ===
- Output ONLY raw SQL — no markdown fences, no explanations, no comments.
- The query MUST start with SELECT or WITH or SUMMARIZE.
- Never use DROP, DELETE, UPDATE, INSERT, CREATE, TRUNCATE, or any write operation.

=== SQL CONSTRUCTION RULES ===
1. JOINS: Use the foreign_keys from the Semantic Mapping to join tables correctly.
   - Prefer explicit JOIN ... ON syntax.
   - Use table aliases to keep queries readable.

2. CTEs (Common Table Expressions): Use WITH clauses freely for complex multi-step logic.
   - Break down complex calculations into named CTEs.
   - Example: WITH revenue_per_customer AS (...), cohorts AS (...) SELECT ...

3. WINDOW FUNCTIONS (DuckDB syntax):
   - Ranking: ROW_NUMBER() / RANK() / DENSE_RANK() OVER (ORDER BY ...)
   - Cohorts: NTILE(5) OVER (ORDER BY total_revenue DESC) — gives quintiles 1..5
   - Running totals: SUM(col) OVER (PARTITION BY category ORDER BY month)
   - Percentages: PERCENT_RANK() OVER (ORDER BY total_revenue DESC)
   - Lead/Lag: LAG(revenue, 1) OVER (PARTITION BY customer ORDER BY month)

4. DATE ARITHMETIC (DuckDB):
   - Current date: CURRENT_DATE
   - Subtract interval: CURRENT_DATE - INTERVAL '6 months', CURRENT_DATE - INTERVAL '180 days'
   - Extract month/year: DATE_TRUNC('month', order_date) or YEAR(date_col), MONTH(date_col)
   - Date diff in days: DATEDIFF('day', start_date, end_date) — use this for churn/frequency

5. DERIVED METRICS: If the user defines a custom formula (e.g. "risk ratio = qty_ordered / units_in_stock"), implement it exactly as specified using column arithmetic.

6. BOOLEAN FLAGS: Use CASE WHEN ... THEN 'Label' ELSE 'Label' END for categorical groupings.
   - Example: CASE WHEN days_since_last_order > 180 THEN 'Churned' ELSE 'Active' END AS status

7. AGGREGATIONS: Always alias aggregated columns clearly.
   - SUM(unit_price * quantity * (1 - discount)) AS total_revenue
   - COUNT(DISTINCT order_id) AS order_count
   - AVG(days_between_orders) AS avg_order_frequency_days

8. SUMMARIZE: If the user asks for a general overview with no specific columns, use exactly:
   SUMMARIZE <table_name>
   (Extract the correct table name from the Semantic Mapping provided above. NEVER use read_csv_auto or hallucinate file names.)
9. ANALYTICAL ROBUSTNESS:
   - Apply standard SQL best practices for edge cases automatically. 
   - For example, when answering "Top N" or "Highest/Lowest" questions, intelligently decide whether to use standard `LIMIT`, or if `SELECT DISTINCT` / `DENSE_RANK()` is required to handle identical duplicate values in raw metrics. 
   - Adapt your query dynamically to best answer the user's core intent without being constrained to a single pattern.

=== DuckDB-SPECIFIC NOTES ===
- DuckDB supports QUALIFY to filter window function results: QUALIFY ROW_NUMBER() OVER (...) = 1
- String concat: col1 || ' ' || col2
- Type casting: CAST(col AS DOUBLE), col::INTEGER
- Structs are not needed; use flat column references.
"""
    if error_context:
        prompt += f"\n\n=== PREVIOUS ATTEMPT FAILED ===\nError: {error_context}\nFix the SQL so it passes DuckDB validation."

    response = client.generate_response(prompt)

    sql = response.strip()
    if sql.startswith("```sql"):
        sql = sql[6:]
    if sql.startswith("```"):
        sql = sql[3:]
    if sql.endswith("```"):
        sql = sql[:-3]
    return sql.strip()


def data_retrieve(sql_query: str, session_id: str = None) -> dict:
    """
    [read-only, external-network] Executes validated SQL against DuckDB.
    Input:  sql_query  — pre-validated SELECT statement
            session_id — if set, queries the user's uploaded session database
    Output: {"status": "success", "data": [...]} or {"status": "error", "message": "..."}
    Error:  Always returns structured dict, never raises
    """
    db = Database(session_id=session_id)
    try:
        df = db.execute_query(sql_query)
        records = df.to_dict(orient='records')
        return {"status": "success", "data": records}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        db.close()


def viz_select(data_records: list, intent: str = "") -> dict:
    """
    [read-only] Deterministically selects visualization based on data shape and intent.
    Input:  data_records — list of dicts, intent — user's original question
    Output: {"chart_type": "...", "columns": [...], "plotly_json": {...}}
    Error:  Returns table fallback on any unexpected shape
    """
    from backend.agent.visualization import select_visualization
    return select_visualization({"intent": intent}, data_records)


def insight_generate(intent: str, data_summary: str) -> dict:
    """
    [read-only] Generates a structured, data-grounded Fact/Insight/Action response.
    Input:  intent — user question, data_summary — truncated string of query results
    Output: {"fact": "...", "insight": "...", "action": "..."}
    Error:  Returns safe fallback dict if LLM fails or grounding check fails
    """
    from backend.agent.insight import generate_structured_insight
    return generate_structured_insight(intent, data_summary)
