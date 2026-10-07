import json
import logging
from difflib import SequenceMatcher
from backend.semantic.model import semantic_model

logger = logging.getLogger(__name__)


def _fuzzy_match(term: str, candidates: list, threshold: float = 0.72) -> bool:
    """Returns True if `term` fuzzy-matches any candidate above the threshold."""
    term_lower = term.lower()
    for c in candidates:
        if SequenceMatcher(None, term_lower, c.lower()).ratio() >= threshold:
            return True
    return False


def semantic_lookup(search_term: str, session_id: str = None) -> str:
    """
    Looks up a business term in the semantic model.
    Returns matched columns, relevant KPI definitions, and date filter SQL snippets.

    If session_id is provided and a dynamic semantic model exists for it,
    that session schema is used instead of the static schema.json.
    """
    # Resolve which schema to use — session-specific or default
    if session_id:
        from backend.data.session_store import get_semantic
        schema = get_semantic(session_id) or semantic_model.get_full_schema()
    else:
        schema = semantic_model.get_full_schema()

    terms = [t.strip().lower() for t in search_term.replace(',', ' ').split() if t.strip()]
    matches = []

    for table_name, table_info in schema.get("tables", {}).items():
        for col_name, col_info in table_info.get("columns", {}).items():
            synonyms_lower = [s.lower() for s in col_info.get("synonyms", [])]
            description_lower = col_info.get("description", "").lower()
            all_candidates = [col_name.lower()] + synonyms_lower + description_lower.split()

            is_match = any(
                term in col_name.lower()
                or term in synonyms_lower
                or term in description_lower
                or _fuzzy_match(term, all_candidates)
                for term in terms
            )
            if is_match:
                match_data = {
                    "table": table_name,
                    "column": col_name,
                    "role": col_info.get("role"),
                    "type": col_info.get("type"),
                    "description": col_info.get("description"),
                    "annotation": "read-only"
                }
                if "allowed_aggregations" in col_info:
                    match_data["allowed_aggregations"] = col_info["allowed_aggregations"]
                matches.append(match_data)

    # Include relevant KPI definitions
    kpi_matches = []
    for kpi_name, kpi_info in schema.get("kpis", {}).items():
        if any(term in kpi_name or term in kpi_info.get("description", "").lower() for term in terms):
            kpi_matches.append({"kpi": kpi_name, **kpi_info})

    # Always include date filter hints so LLM can handle time-based queries
    date_filters = schema.get("date_filters", {})

    if not matches and not kpi_matches:
        # Build a helpful fallback using actual available columns
        tables = list(schema.get("tables", {}).keys())
        table_list = ", ".join(tables) if tables else "no tables found"
        all_cols = [
            col_name
            for table_info in schema.get("tables", {}).values()
            for col_name in table_info.get("columns", {}).keys()
        ]
        col_list = ", ".join(all_cols) if all_cols else "no columns found"
        fk_list = ", ".join(schema.get("foreign_keys", [])) if schema.get("foreign_keys") else "none"
        return (
            f"No semantic matches found for '{search_term}'.\n"
            f"Available tables: {table_list}.\n"
            f"Available columns: {col_list}.\n"
            f"Foreign keys: {fk_list}.\n"
            f"Try rephrasing using these terms."
        )

    return json.dumps({
        "search_term": search_term,
        "matches": matches,
        "kpi_definitions": kpi_matches,
        "date_filter_hints": date_filters,
        "foreign_keys": schema.get("foreign_keys", [])
    }, indent=2)
