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
from typing import List, Literal, Optional

import duckdb
from pydantic import BaseModel, Field

from backend.data.session_store import get_session_db_path
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
    table_name: str = Field(description="The exact table name in the database")
    table_description: str = Field(
        description="One sentence describing what this dataset contains and its business purpose"
    )
    columns: List[ColumnSemantics] = Field(
        description="Semantic metadata for every column in the table"
    )

class MultiTableSemantics(BaseModel):
    tables: List[TableSemantics] = Field(description="List of semantic metadata for all tables")
    foreign_keys: List[str] = Field(
        default_factory=list,
        description="List of inferred foreign key relationships between tables, e.g. 'orders.customer_id = customers.customer_id'. Leave empty if only one table."
    )


# ──────────────────────────────────────────────
# Schema introspection (reads structure, not full data)
# ──────────────────────────────────────────────

def _get_schema_summary(session_id: str) -> dict:
    """
    Returns a lightweight schema summary for ALL tables for the LLM prompt.
    """
    path = get_session_db_path(session_id)
    conn = duckdb.connect(path, read_only=True)
    summary = {}
    try:
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        for table in tables:
            schema_rows = conn.execute(f"DESCRIBE {table}").fetchall()
            columns = [{"column_name": r[0], "column_type": r[1]} for r in schema_rows]

            sample_df = conn.execute(f"SELECT * FROM {table} LIMIT 3").fetchdf()
            sample_rows = json.loads(sample_df.to_json(orient="records", date_format="iso"))

            row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

            summary[table] = {
                "columns": columns,
                "sample_rows": sample_rows,
                "row_count": row_count
            }
        return summary
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

    logger.info(f"[{session_id}] Auto-discovering semantics for {len(raw)} tables")

    try:
        semantic = _llm_discover(raw, session_id)
        logger.info(f"[{session_id}] LLM semantic discovery complete")
    except Exception as e:
        logger.warning(f"[{session_id}] LLM discovery failed ({e}), using rule-based fallback")
        semantic = _rule_based_fallback(raw)

    return semantic


def _llm_discover(raw: dict, session_id: str) -> dict:
    """Calls Gemini with structured output to generate the semantic model for multiple tables."""
    client = LLMClient()

    prompt = (
        f"You are a business intelligence expert. Analyze this database containing multiple tables.\n\n"
        f"Database Schema and Sample Data:\n{json.dumps(raw, indent=2)}\n\n"
        f"Instructions:\n"
        f"- For each table, describe its business purpose.\n"
        f"- For each column, set role='dimension' if it is text/categorical/date, "
        f"or role='measure' if it is numeric and meaningful to aggregate.\n"
        f"- Write a concise description and 4-6 synonyms for each column.\n"
        f"- For measures, set allowed_aggregations to [SUM, AVG, MIN, MAX, COUNT].\n"
        f"- Analyze the tables and infer any FOREIGN KEY relationships (e.g. 'orders.customer_id = customers.customer_id') based on column names. Return these in the foreign_keys array.\n"
        f"Return ONLY valid JSON matching the provided schema. No markdown."
    )

    response_text = client.generate_response(prompt, response_schema=MultiTableSemantics)
    parsed: MultiTableSemantics = MultiTableSemantics.model_validate_json(response_text)

    # Build the output dict in schema.json format
    tables_output = {}
    all_columns = []
    
    for table_def in parsed.tables:
        table_name = table_def.table_name
        if table_name not in raw:
            continue
            
        col_type_map = {c["column_name"]: c["column_type"] for c in raw[table_name]["columns"]}
        all_columns.extend(raw[table_name]["columns"])
        
        columns_dict = {}
        for col in table_def.columns:
            entry = {
                "type": col_type_map.get(col.column_name, "VARCHAR"),
                "role": col.role,
                "description": col.description,
                "synonyms": col.synonyms,
            }
            if col.allowed_aggregations:
                entry["allowed_aggregations"] = col.allowed_aggregations
            columns_dict[col.column_name] = entry
            
        tables_output[table_name] = {
            "description": table_def.table_description,
            "columns": columns_dict
        }

    return {
        "tables": tables_output,
        "foreign_keys": parsed.foreign_keys,
        "date_filters": _build_date_filters(all_columns),
        "kpis": {}  # KPIs can be added by the user later
    }


def _rule_based_fallback(raw: dict) -> dict:
    """
    Minimal semantic model built from DuckDB type heuristics alone for all tables.
    """
    import re
    numeric_types = {"integer", "bigint", "double", "float", "decimal", "numeric", "real", "hugeint", "smallint"}
    tables_output = {}
    all_columns = []

    for table_name, data in raw.items():
        columns_dict = {}
        all_columns.extend(data["columns"])
        
        for col in data["columns"]:
            col_name = col["column_name"]
            col_type = col["column_type"].lower()

            is_numeric = any(t in col_type for t in numeric_types)
            role = "measure" if is_numeric else "dimension"
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

        tables_output[table_name] = {
            "description": f"User-uploaded {table_name} dataset.",
            "columns": columns_dict
        }

    return {
        "tables": tables_output,
        "foreign_keys": [],
        "date_filters": _build_date_filters(all_columns),
        "kpis": {}
    }
