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


# 1. Define the Typed State
class AgentState(TypedDict, total=False):
    user_prompt: str
    intent: str
    dimensions: List[str]
    measures: List[str]
    filters: List[str]
    semantic_mapping: str
    generated_sql: str
    sql_validation: str
    sql_retries: int
    query_result: List[Dict[str, Any]]
    visualization: Dict[str, Any]
    insights: str
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

    client = LLMClient()
    prompt = (
        f"Analyze this business question: '{state['user_prompt']}'. "
        f"If the user is asking a purely conversational question (like a greeting, asking how to use the app, or general chat), "
        f"return a JSON object with 'is_conversational': true, and 'response': 'your conversational response'. "
        f"IMPORTANT: If the user asks for a summary, overview, understanding, or explanation of the uploaded data/file, DO NOT treat it as conversational. It is an analytical query. "
        f"For analytical queries, return a JSON object with three keys: "
        f"'dimensions' (list of grouping fields like region, product, date), "
        f"'measures' (list of numeric fields like revenue, units), "
        f"'filters' (list of filter conditions mentioned like 'North region', 'last quarter'). "
        f"If they ask for a general summary, set dimensions to ['all'] and measures to ['summary']. "
        f"Return only valid JSON, no markdown."
    )
    response = client.generate_response(prompt)

    # Parse structured intent from LLM
    is_conversational = False
    conversational_response = ""
    try:
        clean = response.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        parsed = json.loads(clean)
        is_conversational = parsed.get("is_conversational", False)
        conversational_response = parsed.get("response", "")
        dimensions = parsed.get("dimensions", [])
        measures = parsed.get("measures", [])
        filters = parsed.get("filters", [])
    except (json.JSONDecodeError, AttributeError):
        # Fallback: treat entire response as a flat term list
        dimensions = [response]

    if is_conversational:
        trace.log_event("understand_intent", tool_called="gemini.generate_response",
                        tool_result={"is_conversational": True}, status="success")
        return {
            "intent": state["user_prompt"],
            "visualization": {"chart_type": "message", "message": conversational_response},
            "status": "conversational"
        }

    trace.log_event("understand_intent", tool_called="gemini.generate_response",
                    tool_arguments={"prompt_length": len(prompt)},
                    tool_result={"dimensions": dimensions, "measures": measures, "filters": filters},
                    status="success")
    return {
        "intent": state["user_prompt"],
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
        new_retries = retries + 1
        trace.log_event("validate_and_retrieve", tool_called="data_retrieve",
                        hook_decision="DENY", retry_count=new_retries,
                        status="failed", error=str(e))
        return {
            "sql_validation": str(e),
            "sql_retries": new_retries,
            "status": "sql_error",
            "errors": str(e)
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
        data_str = f"Showing top 15 of {len(data)} rows: {data[:15]}"
    else:
        data_str = str(data)

    insight = insight_generate(state.get("intent", ""), data_str)
    trace.log_event("generate_insight", tool_called="insight_generate",
                    tool_result={"insight_keys": list(insight.keys()) if isinstance(insight, dict) else []},
                    status="success")
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
workflow.add_edge("generate_sql", "validate_and_retrieve")

workflow.add_conditional_edges(
    "validate_and_retrieve",
    should_retry,
    {"continue": "fan_out", "retry": "generate_sql", "fail": END}
)

workflow.add_edge("fan_out", "select_visualization")
workflow.add_edge("fan_out", "generate_insight")
workflow.add_edge("select_visualization", END)
workflow.add_edge("generate_insight", END)

agent_app = workflow.compile()
