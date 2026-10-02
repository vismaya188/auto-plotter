"""
LLM-powered semantic model auto-discovery.

After data is ingested into a session DuckDB table, this module:
1. Reads the DuckDB schema + 3 sample rows (schema introspection, not user data)
2. Calls Gemini with a structured output schema (TableSemantics Pydantic model)
3. Returns a dict matching the existing schema.json format

The result is stored in session_store and used by semantic/tools.py for all
subsequent lookup calls in that session.
"""
import json
import logging
from typing import List, Literal

import duckdb
from pydantic import BaseModel, Field

from backend.data.session_store import get_session_db_path
from backend.data.ingestion import TABLE_NAME
from backend.llm.gemini import LLMClient

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Pydantic models for Gemini structured output
# ──────────────────────────────────────────────

class ColumnSemantics(BaseModel):
    column_name: str = Field(description="Exact column name from the database schema")
    role: Literal["dimension", "measure"] = Field(
        description="'dimension' for text/date/categorical columns, 'measure' for numeric aggregatable columns"
    )
    description: str = Field(description="One-sentence plain English business description of this column")
    synonyms: List[str] = Field(
        description="4-6 alternative words or phrases a business user might say to refer to this column"
    )
    allowed_aggregations: List[str] = Field(
        default_factory=list,
        description="For measures only: list from [SUM, AVG, MIN, MAX, COUNT]. Empty for dimensions."
    )


class TableSemantics(BaseModel):
    table_description: str = Field(
        description="One sentence describing what this dataset contains and its business purpose"
    )
    columns: List[ColumnSemantics] = Field(
        description="Semantic metadata for every column in the table"
    )


# ──────────────────────────────────────────────
# Schema introspection (reads structure, not full data)
# ──────────────────────────────────────────────

def _get_schema_summary(session_id: str) -> dict:
    """
    Returns a lightweight schema summary for the LLM prompt:
    - Column names + DuckDB types
    - 3 sample rows (to help LLM understand actual data values)
    - Total row count
    """
    path = get_session_db_path(session_id)
    conn = duckdb.connect(path, read_only=True)
    try:
        schema_rows = conn.execute(f"DESCRIBE {TABLE_NAME}").fetchall()
        columns = [{"column_name": r[0], "column_type": r[1]} for r in schema_rows]

        sample_df = conn.execute(f"SELECT * FROM {TABLE_NAME} LIMIT 3").fetchdf()
        # Convert to JSON-serializable format — handle NaN, dates, etc.
        sample_rows = json.loads(sample_df.to_json(orient="records", date_format="iso"))

        row_count = conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]

        return {
            "columns": columns,
            "sample_rows": sample_rows,
            "row_count": row_count
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# Date filter generation
# ──────────────────────────────────────────────

def _build_date_filters(columns: list) -> dict:
    """
    Returns date filter hints if any date-like columns are found.
    Detects date columns by type or common column name patterns.
    """
    date_type_keywords = {"date", "timestamp", "datetime"}
    date_name_keywords = {"date", "time", "day", "month", "year", "period", "created", "updated"}

    has_date_col = any(
        any(kw in col["column_name"].lower() for kw in date_name_keywords)
        or any(kw in col["column_type"].lower() for kw in date_type_keywords)
        for col in columns
    )

    if not has_date_col:
        return {}

    # Find the most likely date column name for the hints
    date_col = next(
        (col["column_name"] for col in columns
         if any(kw in col["column_name"].lower() for kw in date_name_keywords)),
        "date"
    )

    return {
        "this year":    f"YEAR({date_col}) = YEAR(CURRENT_DATE)",
        "last year":    f"YEAR({date_col}) = YEAR(CURRENT_DATE) - 1",
        "this month":   f"YEAR({date_col}) = YEAR(CURRENT_DATE) AND MONTH({date_col}) = MONTH(CURRENT_DATE)",
        "last month":   f"{date_col} >= DATE_TRUNC('month', CURRENT_DATE) - INTERVAL 1 MONTH AND {date_col} < DATE_TRUNC('month', CURRENT_DATE)",
        "last quarter": f"{date_col} >= DATE_TRUNC('quarter', CURRENT_DATE) - INTERVAL 3 MONTH AND {date_col} < DATE_TRUNC('quarter', CURRENT_DATE)",
        "this quarter": f"{date_col} >= DATE_TRUNC('quarter', CURRENT_DATE) AND {date_col} < DATE_TRUNC('quarter', CURRENT_DATE) + INTERVAL 3 MONTH"
    }


# ──────────────────────────────────────────────
# Main discovery function
# ──────────────────────────────────────────────

def auto_discover_semantics(session_id: str) -> dict:
    """
    Calls Gemini to generate a full semantic model from schema + sample data.
    Returns a dict compatible with the existing schema.json format.

    Falls back to a minimal rule-based semantic model if the LLM call fails,
    so ingestion never fails just because auto-discovery errored.
    """
    try:
        raw = _get_schema_summary(session_id)
    except Exception as e:
        logger.error(f"[{session_id}] Schema introspection failed: {e}")
        raise

    logger.info(f"[{session_id}] Auto-discovering semantics for {len(raw['columns'])} columns, {raw['row_count']} rows")

    try:
        semantic = _llm_discover(raw, session_id)
        logger.info(f"[{session_id}] LLM semantic discovery complete")
    except Exception as e:
        logger.warning(f"[{session_id}] LLM discovery failed ({e}), using rule-based fallback")
        semantic = _rule_based_fallback(raw)

    return semantic


def _llm_discover(raw: dict, session_id: str) -> dict:
    """Calls Gemini with structured output to generate the semantic model."""
    client = LLMClient()

    prompt = (
        f"You are a business intelligence expert. Analyze this database table schema and sample data, "
        f"then generate a precise semantic model for it.\n\n"
        f"Table Name: {TABLE_NAME}\n"
        f"Columns and Types (from DuckDB DESCRIBE):\n{json.dumps(raw['columns'], indent=2)}\n\n"
        f"Sample Rows (first 3 rows of actual data):\n{json.dumps(raw['sample_rows'], indent=2)}\n\n"
        f"Total Row Count: {raw['row_count']}\n\n"
        f"Instructions:\n"
        f"- For each column, set role='dimension' if it is text/categorical/date, "
        f"or role='measure' if it is numeric and meaningful to aggregate.\n"
        f"- Write a concise, plain-English description of what the column represents in a business context.\n"
        f"- Generate 4-6 synonyms: alternative words a non-technical business user might say.\n"
        f"- For measures, set allowed_aggregations to the appropriate subset of [SUM, AVG, MIN, MAX, COUNT].\n"
        f"- Also write a one-sentence table_description summarising the dataset.\n"
        f"Return ONLY valid JSON matching the provided schema. No markdown, no explanation."
    )

    response_text = client.generate_response(prompt, response_schema=TableSemantics)
    parsed: TableSemantics = TableSemantics.model_validate_json(response_text)

    # Build the output dict in schema.json format
    col_type_map = {c["column_name"]: c["column_type"] for c in raw["columns"]}
    columns_dict = {}
    for col in parsed.columns:
        entry = {
            "type": col_type_map.get(col.column_name, "VARCHAR"),
            "role": col.role,
            "description": col.description,
            "synonyms": col.synonyms,
        }
        if col.allowed_aggregations:
            entry["allowed_aggregations"] = col.allowed_aggregations
        columns_dict[col.column_name] = entry

    return {
        "tables": {
            TABLE_NAME: {
                "description": parsed.table_description,
                "columns": columns_dict
            }
        },
        "date_filters": _build_date_filters(raw["columns"]),
        "kpis": {}  # KPIs can be added by the user later; auto-discovery leaves this empty
    }


def _rule_based_fallback(raw: dict) -> dict:
    """
    Minimal semantic model built from DuckDB type heuristics alone.
    Used when the LLM call fails so ingestion can still proceed.
    """
    import re
    columns_dict = {}
    numeric_types = {"integer", "bigint", "double", "float", "decimal", "numeric", "real", "hugeint", "smallint"}

    for col in raw["columns"]:
        col_name = col["column_name"]
        col_type = col["column_type"].lower()

        is_numeric = any(t in col_type for t in numeric_types)
        role = "measure" if is_numeric else "dimension"
        # Simple synonym: split underscore/camelCase into words
        words = re.sub(r"([A-Z])", r" \1", col_name).replace("_", " ").lower().split()
        synonyms = list({col_name.lower(), *words})[:5]

        entry = {
            "type": col["column_type"],
            "role": role,
            "description": f"The {col_name.replace('_', ' ')} field.",
            "synonyms": synonyms,
        }
        if role == "measure":
            entry["allowed_aggregations"] = ["SUM", "AVG", "MIN", "MAX"]
        columns_dict[col_name] = entry

    return {
        "tables": {
            TABLE_NAME: {
                "description": "User-uploaded dataset.",
                "columns": columns_dict
            }
        },
        "date_filters": _build_date_filters(raw["columns"]),
        "kpis": {}
    }
