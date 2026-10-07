from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
import time
import json

from backend.config import settings
from backend.security.hooks import sanitize_prompt, validate_sql, validate_tool_output, SecurityViolation, AmbiguousPromptError
from backend.agent.tools import (
    semantic_lookup,
    query_generate,
    data_retrieve,
    viz_select,
    insight_generate
)
from backend.agent.context import AgentTrace
from backend.llm.gemini import LLMClient


class AgentState(TypedDict, total=False):
    user_prompt: str
    chat_history: List[Dict[str, str]]
    intent: str
    intent_type: str
    dimensions: List[str]
    measures: List[str]
    filters: List[str]
    semantic_mapping: str
    generated_sql: str
    sql_validation: str
    sql_retries: int
    query_result: List[Dict[str, Any]]
    visualization: Dict[str, Any]
    insights: Dict[str, Any]
    errors: str
    status: str
    session_start_time: float
    trace: Any  # AgentTrace instance carried through state
    session_id: str  # Optional: routes to user-uploaded session DB when set


class DataRetrievalError(Exception):
    """Raised when data retrieval or SQL validation fails during agent execution."""
    pass


class TimeBudgetExceededError(Exception):
    """Raised when the agent exceeds the configured session time budget."""
    pass


def _check_time_budget(state: AgentState):
    """Pre-model hook: aborts if total session time exceeds the configured limit."""
    elapsed = time.time() - state.get("session_start_time", time.time())
    if elapsed > settings.agent_time_budget_seconds:
        raise TimeBudgetExceededError(
            f"Session time budget of {settings.agent_time_budget_seconds}s exceeded ({elapsed:.1f}s elapsed)."
        )


# 2. Define Nodes

def validate_input_node(state: AgentState):
    trace = AgentTrace(session_id=state.get("_session_id", str(id(state))))
    try:
        clean_prompt = sanitize_prompt(state.get("user_prompt", ""))
        trace.log_event("validate_input", tool_called="sanitize_prompt",
                        tool_arguments={"prompt": clean_prompt},
                        hook_decision="ALLOW", status="success")
        return {
            "user_prompt": clean_prompt,
            "status": "input_validated",
            "session_start_time": time.time(),
            "trace": trace
        }
    except (SecurityViolation, AmbiguousPromptError) as e:
        trace.log_event("validate_input", tool_called="sanitize_prompt",
                        hook_decision="DENY", status="failed", error=str(e))
        return {"errors": str(e), "status": "failed", "trace": trace}


def understand_intent_node(state: AgentState):
    trace: AgentTrace = state.get("trace")
    try:
        _check_time_budget(state)
    except TimeBudgetExceededError as e:
        trace.log_event("understand_intent", status="failed", error=str(e))
        return {"errors": str(e), "status": "failed"}

    # Build a schema context snippet so the LLM extracts real column names
    # and has conversational memory of what's loaded.
    schema_context = ""
    system_prefix = ""
    session_id = state.get("session_id")
    if session_id:
        try:
            from backend.data.session_store import get_semantic
            schema = get_semantic(session_id)
            if schema:
                table_names = list(schema.get("tables", {}).keys())
                col_names = [
                    f"{tbl}.{col}"
                    for tbl, tinfo in schema.get("tables", {}).items()
                    for col in tinfo.get("columns", {}).keys()
                ]
                fk_list = schema.get("foreign_keys", [])
                schema_context = (
                    f"\n\nAvailable tables: {table_names}"
                    f"\nAvailable columns (table.column): {col_names[:40]}"
                    + (f"\nForeign keys: {fk_list}" if fk_list else "")
                )
                system_prefix = f"[SYSTEM] User currently has {len(table_names)} tables loaded: {', '.join(table_names)}.\n"
        except Exception:
            pass  # Schema context is optional — don't break if it fails

    history_text = system_prefix
    if state.get("chat_history"):
        history_text += "Chat History:\n" + "\n".join([f"{msg['role']}: {msg['content']}" for msg in state["chat_history"]])

    client = LLMClient()
    prompt = (
        f"Analyze this business question: '{state['user_prompt']}'.\n"
        f"{history_text}\n\n"
        f"Classify the user's intent into exactly one of three categories:\n"
        f"1. 'conversational': Greetings, asking how to use the app, or general chat that DOES NOT require querying the database.\n"
        f"2. 'data_qa': ONLY choose this if the user asks for a general summary, overview, or explanation of the uploaded data. Requires a SQL query but NO chart.\n"
        f"3. 'visualization': ANY other data question (e.g. 'what is the total revenue', 'How many customers in the USA?', 'Show month-over-month trend'). ALWAYS choose this for specific data lookups or business questions so the user gets a KPI or chart.\n\n"
        f"Return a JSON object with:\n"
        f"- 'intent_type': 'conversational', 'data_qa', or 'visualization'\n"
        f"- 'response': (only if 'conversational') your text response to the user\n"
        f"- 'dimensions': (only if NOT conversational) list of EXACT column names for grouping (e.g. orderDate, companyName). Prefer names from the Available columns list.\n"
        f"- 'measures': (only if NOT conversational) list of EXACT column names for numeric metrics (e.g. freight, unitPrice). Prefer names from the Available columns list.\n"
        f"- 'filters': (only if NOT conversational) list of filter conditions (e.g. 'last 180 days', 'top 20%')\n"
        f"If they ask for a general summary, set dimensions to ['all'] and measures to ['summary'].\n"
        f"{schema_context}\n"
        f"Return only valid JSON, no markdown."
    )
    response = client.generate_response(prompt)

    # Parse structured intent from LLM
    intent_type = "visualization"
    conversational_response = ""
    dimensions = []
    measures = []
    filters = []
    
    try:
        clean = response.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        intent_type = parsed.get("intent_type", "visualization")
        conversational_response = parsed.get("response", "")
        dimensions = parsed.get("dimensions", [])
        measures = parsed.get("measures", [])
        filters = parsed.get("filters", [])
    except (json.JSONDecodeError, AttributeError):
        # Fallback
        dimensions = [response]

    if intent_type == "conversational":
        trace.log_event("understand_intent", tool_called="gemini.generate_response",
                        tool_result={"intent_type": intent_type}, status="success")
        return {
            "intent": state["user_prompt"],
            "intent_type": intent_type,
            "visualization": {"chart_type": "message", "message": conversational_response},
            "status": "conversational"
        }

    trace.log_event("understand_intent", tool_called="gemini.generate_response",
                    tool_arguments={"prompt_length": len(prompt)},
                    tool_result={"intent_type": intent_type, "dimensions": dimensions, "measures": measures, "filters": filters},
                    status="success")
    return {
        "intent": state["user_prompt"],
        "intent_type": intent_type,
        "dimensions": dimensions,
        "measures": measures,
        "filters": filters,
        "status": "intent_understood"
    }


def lookup_semantics_node(state: AgentState):
    trace: AgentTrace = state.get("trace")
    session_id = state.get("session_id")
    # Combine all extracted terms for semantic lookup
    all_terms = (
        state.get("dimensions", []) +
        state.get("measures", []) +
        state.get("filters", [])
    )
    terms_str = " ".join(str(t) for t in all_terms) if all_terms else state.get("user_prompt", "")
    mapping = semantic_lookup(terms_str, session_id=session_id)
    trace.log_event("lookup_semantics", tool_called="semantic_lookup",
                    tool_arguments={"search_term": terms_str},
                    tool_result={"mapping_length": len(mapping)},
                    hook_decision="ALLOW", status="success")
    return {"semantic_mapping": mapping, "status": "semantics_found"}


def generate_sql_node(state: AgentState):
    trace: AgentTrace = state.get("trace")
    try:
        _check_time_budget(state)
    except TimeBudgetExceededError as e:
        trace.log_event("generate_sql", status="failed", error=str(e))
        return {"errors": str(e), "status": "failed"}

    sql = query_generate(
        intent=state.get("intent", ""),
        semantic_mapping=state.get("semantic_mapping", ""),
        error_context=state.get("sql_validation", "") if state.get("sql_retries", 0) > 0 else ""
    )

    if sql.startswith("CANNOT_ANSWER:"):
        trace.log_event("generate_sql", hook_decision="ABORT", status="success")
        message = sql.replace("CANNOT_ANSWER:", "").strip()
        return {
            "intent_type": "conversational",
            "visualization": {"chart_type": "message", "message": message},
            "status": "conversational",
            "errors": ""
        }

    trace.log_event("generate_sql", tool_called="query_generate",
                    tool_arguments={"intent": state.get("intent"), "retry": state.get("sql_retries", 0)},
                    tool_result={"sql": sql}, status="success")
    return {"generated_sql": sql, "status": "sql_generated"}


def validate_and_retrieve_node(state: AgentState):
    trace: AgentTrace = state.get("trace")
    sql = state.get("generated_sql", "")
    retries = state.get("sql_retries", 0)
    session_id = state.get("session_id")

    try:
        # Pre-tool hook
        valid_sql = validate_sql(sql)
        trace.log_event("validate_sql", tool_called="validate_sql",
                        tool_arguments={"sql": valid_sql},
                        hook_decision="ALLOW", status="success")

        # Tool execution — routes to session DB if session_id is set
        result = data_retrieve(valid_sql, session_id=session_id)
        if result["status"] == "error":
            raise DataRetrievalError(result["message"])

        # Post-tool hook
        data = result["data"]
        safe_data = validate_tool_output(data)

        # Empty result guard
        if len(safe_data) == 0:
            trace.log_event("validate_and_retrieve", tool_called="data_retrieve",
                            tool_result={"rows": 0}, hook_decision="WARN",
                            status="success")
            return {
                "sql_validation": "VALID",
                "query_result": [],
                "status": "data_retrieved",
                "errors": "The query executed successfully but returned no data. Try broadening your filters."
            }

        trace.log_event("validate_and_retrieve", tool_called="data_retrieve",
                        tool_result={"rows": len(safe_data)},
                        hook_decision="ALLOW", status="success")
        return {
            "sql_validation": "VALID",
            "query_result": safe_data,
            "status": "data_retrieved",
            "errors": ""
        }

    except Exception as e:
        error_msg = str(e)
        new_retries = retries + 1
        
        # New targeted lookup logic for missing columns/tables
        error_lower = error_msg.lower()
        supplemental_info = ""
        if "not found" in error_lower or "does not exist" in error_lower or "no column named" in error_lower:
            import re
            match = re.search(r"name '?([^']*)'?", error_msg) or re.search(r"column '?([^']*)'?", error_msg)
            term = match.group(1) if match else error_msg
            supplemental_info = semantic_lookup(term, session_id=session_id)
            
        error_context = error_msg
        if supplemental_info:
            error_context += f"\nHint: Here is the semantic mapping for the missing term: {supplemental_info}"

        trace.log_event("validate_and_retrieve", tool_called="data_retrieve",
                        hook_decision="DENY", retry_count=new_retries,
                        status="failed", error=error_msg)
        return {
            "sql_validation": error_context,
            "sql_retries": new_retries,
            "status": "sql_error",
            "errors": error_msg
        }


def select_visualization_node(state: AgentState):
    trace: AgentTrace = state.get("trace")
    viz = viz_select(state.get("query_result", []), state.get("intent", ""))
    trace.log_event("select_visualization", tool_called="viz_select",
                    tool_result={"chart_type": viz.get("chart_type")},
                    status="success")
    return {"visualization": viz}


def generate_insight_node(state: AgentState):
    trace: AgentTrace = state.get("trace")
    try:
        _check_time_budget(state)
    except TimeBudgetExceededError as e:
        trace.log_event("generate_insight", status="failed", error=str(e))
        return {"errors": str(e), "status": "failed"}

    data = state.get("query_result", [])
    if len(data) > 15:
        try:
            import pandas as pd
            import numpy as np
            df = pd.DataFrame(data)
            # Replace NaNs with None so it's clean for the prompt
            desc = df.describe(include='all').replace({np.nan: None}).to_dict()
            data_str = f"Showing top 15 of {len(data)} rows: {data[:15]}\n\nSummary Statistics for all {len(data)} rows:\n{desc}"
        except Exception:
            data_str = f"Showing top 15 of {len(data)} rows: {data[:15]}"
    else:
        data_str = str(data)

    insight = insight_generate(state.get("intent", ""), data_str)
    trace.log_event("generate_insight", tool_called="insight_generate",
                    tool_result={"insight_keys": list(insight.keys()) if isinstance(insight, dict) else []},
                    status="success")
    
    # If this was a DATA_QA intent, we bypass visualization entirely and output the insight as the chat message
    if state.get("intent_type") == "data_qa":
        return {
            "insights": insight, 
            "visualization": {"chart_type": "message", "message": f"{insight.get('fact', '')}\n\n{insight.get('insight', '')}\n\n{insight.get('action', '')}"},
            "status": "insight_generated"
        }
        
    return {"insights": insight, "status": "insight_generated"}


# 3. Define Conditional Edges

def should_retry(state: AgentState):
    """Controls the self-correction loop for SQL generation."""
    if state.get("status") == "sql_error":
        if state.get("sql_retries", 0) < 3:
            return "retry"
        return "fail"
    return "continue"


def check_errors(state: AgentState):
    """Halts the graph early if a security hook or time budget failed."""
    if state.get("errors"):
        return "fail"
    return "continue"


def check_intent(state: AgentState):
    """Routes conversational intents directly to END, otherwise continues."""
    if state.get("status") == "conversational":
        return "end"
    if state.get("errors"):
        return "fail"
    return "continue"


def fan_out_node(state: AgentState):
    return {"status": "processing_outputs"}

def after_validate_and_retrieve(state: AgentState):
    """Routes to fan_out if visualization is needed, otherwise direct to insight (data_qa)."""
    status = should_retry(state)
    if status != "continue":
        return status
        
    if state.get("intent_type") == "data_qa":
        return "generate_insight"
    return "fan_out"

def check_sql_generation(state: AgentState):
    """Routes to END if the LLM determines the SQL cannot be generated due to missing data."""
    if state.get("status") == "conversational":
        return "end"
    return "continue"

# 4. Build the LangGraph Workflow
workflow = StateGraph(AgentState)

workflow.add_node("validate_input", validate_input_node)
workflow.add_node("understand_intent", understand_intent_node)
workflow.add_node("lookup_semantics", lookup_semantics_node)
workflow.add_node("generate_sql", generate_sql_node)
workflow.add_node("validate_and_retrieve", validate_and_retrieve_node)
workflow.add_node("fan_out", fan_out_node)
workflow.add_node("select_visualization", select_visualization_node)
workflow.add_node("generate_insight", generate_insight_node)

workflow.set_entry_point("validate_input")

workflow.add_conditional_edges("validate_input", check_errors, {"continue": "understand_intent", "fail": END})
workflow.add_conditional_edges("understand_intent", check_intent, {"continue": "lookup_semantics", "end": END, "fail": END})
workflow.add_edge("lookup_semantics", "generate_sql")

workflow.add_conditional_edges(
    "generate_sql",
    check_sql_generation,
    {"continue": "validate_and_retrieve", "end": END}
)

workflow.add_conditional_edges(
    "validate_and_retrieve",
    after_validate_and_retrieve,
    {"fan_out": "fan_out", "generate_insight": "generate_insight", "retry": "generate_sql", "fail": END}
)

workflow.add_edge("fan_out", "select_visualization")
workflow.add_edge("fan_out", "generate_insight")
workflow.add_edge("select_visualization", END)
workflow.add_edge("generate_insight", END)

agent_app = workflow.compile()
