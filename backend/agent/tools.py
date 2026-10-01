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
    You are a SQL generation assistant for DuckDB.
    User Intent: {intent}
    Semantic Mapping: {semantic_mapping}

    Rules:
    - Generate ONLY a valid DuckDB SQL SELECT query.
    - Do not include markdown formatting (like ```sql).
    - Do not include any explanations.
    - Use date filter hints from the semantic mapping if the user mentions a time period.
    """
    if error_context:
        prompt += f"\nYour previous attempt failed with this error: {error_context}\nPlease fix the SQL."

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
