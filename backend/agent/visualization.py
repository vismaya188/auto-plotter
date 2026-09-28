import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import Dict, Any, List
import json
from backend.llm.gemini import LLMClient
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)

class ChartMapping(BaseModel):
    chart_type: str = Field(description="The type of chart: 'line', 'bar', 'scatter', 'kpi', or 'table'")
    x_col: str = Field(description="The exact name of the column for the X-axis (or empty if not applicable)")
    y_col: str = Field(description="The exact name of the column for the Y-axis (or empty if not applicable)")
    color_col: str = Field(description="The exact name of the column for color grouping (or empty if not applicable)")
    title: str = Field(description="A descriptive title for the chart")

def get_chart_mapping(intent: str, columns: List[str], data_types: Dict[str, str], num_rows: int) -> ChartMapping:
    if num_rows == 1 and len(columns) == 1:
        return ChartMapping(chart_type="kpi", x_col="", y_col="", color_col="", title=columns[0])
        
    client = LLMClient()
    prompt = f"""
    You are a data visualization expert. Select the best chart type and map the columns for Plotly.
    User Intent: {intent}
    Data Schema (Columns and their types): {data_types}
    Number of Rows: {num_rows}
    
    Choose the best chart_type and specify exactly which columns map to x_col, y_col, and color_col.
    If it's just raw tabular data that shouldn't be charted, choose 'table'.
    """
    try:
        response_text = client.generate_response(prompt, response_schema=ChartMapping)
        # Assuming the returned text is JSON since response_schema is provided
        # The schema forces it to be parsable to ChartMapping
        return ChartMapping.model_validate_json(response_text)
    except Exception as e:
        logger.error(f"Failed to get chart mapping from LLM: {e}")
        # Fallback to table
        return ChartMapping(chart_type="table", x_col="", y_col="", color_col="", title="Data Table")

TIME_KEYWORDS = ['date', 'time', 'month', 'year', 'day']
GEO_KEYWORDS = ['country', 'state', 'city', 'region', 'location', 'territory', 'geo', 'map']
PART_WHOLE_KEYWORDS = ['share', 'proportion', 'breakdown', 'composition', 'percentage', 'pie', 'donut']


def _is_time_column(col_name: str) -> bool:
    return any(t in col_name.lower() for t in TIME_KEYWORDS)


def _is_geo_column(col_name: str) -> bool:
    return any(g in col_name.lower() for g in GEO_KEYWORDS)


def _build_kpi(df: pd.DataFrame, keys: list) -> tuple:
    val = df.iloc[0, 0]
    fig = go.Figure(go.Indicator(mode="number", value=val, title={"text": keys[0]}))
    return "kpi", fig


def _build_multi_kpi(df: pd.DataFrame, keys: list) -> tuple:
    """Renders multiple single-value KPIs side by side using subplots."""
    fig = go.Figure()
    cols = len(keys)
    for i, col in enumerate(keys):
        fig.add_trace(go.Indicator(
            mode="number",
            value=df.iloc[0][col],
            title={"text": col},
            domain={"x": [i / cols, (i + 1) / cols], "y": [0, 1]}
        ))
    return "multi_kpi", fig


def _build_two_col_chart(df: pd.DataFrame, keys: list, intent: str) -> tuple:
    col1, col2 = keys[0], keys[1]
    is_time = _is_time_column(col1) or _is_time_column(col2)

    if is_time or "trend" in intent:
        x_col = col1 if _is_time_column(col1) else col2
        y_col = col2 if x_col == col1 else col1
        fig = px.line(df, x=x_col, y=y_col, title=f"{y_col} over {x_col}")
        return "line", fig

    # Part-to-whole: pie/donut
    if any(k in intent for k in PART_WHOLE_KEYWORDS):
        numeric_cols = df.select_dtypes(include='number').columns
        if len(numeric_cols) > 0:
            y_col = numeric_cols[0]
            x_col = col1 if y_col == col2 else col2
            fig = px.pie(df, names=x_col, values=y_col, hole=0.4, title=f"{y_col} breakdown by {x_col}")
            return "donut", fig

    numeric_cols = df.select_dtypes(include='number').columns
    if len(numeric_cols) > 0:
        y_col = numeric_cols[0]
        x_col = col1 if y_col == col2 else col2
    else:
        x_col, y_col = col1, col2
    fig = px.bar(df, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
    return "bar", fig


def _build_scatter(df: pd.DataFrame, keys: list) -> tuple:
    numeric_cols = df.select_dtypes(include='number').columns
    if len(numeric_cols) < 2:
        return "table", None
    x_col, y_col = numeric_cols[0], numeric_cols[1]
    color_col = next((k for k in keys if k not in [x_col, y_col]), keys[0])
    fig = px.scatter(df, x=x_col, y=y_col, color=color_col, title=f"Scatter of {y_col} vs {x_col}")
    return "scatter", fig


def _build_map(df: pd.DataFrame, keys: list) -> tuple:
    """Builds a choropleth map if a geo column and numeric column are present."""
    geo_col = next((k for k in keys if _is_geo_column(k)), None)
    numeric_cols = df.select_dtypes(include='number').columns
    if geo_col is None or len(numeric_cols) == 0:
        return "table", None
    val_col = numeric_cols[0]
    fig = px.choropleth(df, locations=geo_col, locationmode="country names",
                        color=val_col, title=f"{val_col} by {geo_col}")
    return "map", fig


def select_visualization(intent_data: Dict[str, Any], data_records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Deterministically selects the best visualization based on data shape and intent.
    Returns a structured dict with chart_type, columns, and plotly_json.
    """
    if not data_records:
        return {
            "chart_type": "empty",
            "plotly_json": None,
            "columns": [],
            "message": "The query returned no data. Try broadening your filters or rephrasing your question."
        }

    df = pd.DataFrame(data_records)
    keys = list(df.columns)
    intent = intent_data.get("intent", "").lower()

    fig = None
    chart_type = "table"

    # Single row, single column → KPI
    if len(df) == 1 and len(keys) == 1:
        chart_type, fig = _build_kpi(df, keys)

    # Single row, multiple ALL-numeric columns → multi-KPI
    elif len(df) == 1 and len(keys) > 1:
        numeric_cols = df.select_dtypes(include='number').columns
        if len(numeric_cols) == len(keys):
            chart_type, fig = _build_multi_kpi(df, keys)

    # Geographic intent explicitly requested (not just column name match)
    elif "map" in intent and any(_is_geo_column(k) for k in keys):
        chart_type, fig = _build_map(df, keys)

    # Two columns
    elif len(keys) == 2:
        chart_type, fig = _build_two_col_chart(df, keys, intent)

    # Three+ columns with scatter/relationship intent
    elif len(keys) >= 3 and ("relationship" in intent or "scatter" in intent):
        chart_type, fig = _build_scatter(df, keys)

    return {
        "chart_type": chart_type,
        "columns": keys,
        "plotly_json": json.loads(fig.to_json()) if fig else None
    }
