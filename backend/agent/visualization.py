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


def _build_table(df: pd.DataFrame) -> tuple:
    fig = go.Figure(data=[go.Table(
        header=dict(values=list(df.columns),
                    fill_color='#1e293b',
                    font=dict(color='white', size=14),
                    align='left'),
        cells=dict(values=[df[col] for col in df.columns],
                   fill_color='#0f172a',
                   font=dict(color='white', size=12),
                   align='left'))
    ])
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=30, b=0)
    )
    return "table", fig

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

    # Three+ columns — try keyword heuristics first, then fall back to LLM chart selection
    elif len(keys) >= 3:
        if "scatter" in intent or "relationship" in intent:
            chart_type, fig = _build_scatter(df, keys)
        elif "box" in intent:
            # Box plot
            categorical_cols = df.select_dtypes(exclude='number').columns
            numeric_cols = df.select_dtypes(include='number').columns
            if len(categorical_cols) > 0 and len(numeric_cols) > 0:
                x_col = categorical_cols[0]
                y_col = numeric_cols[0]
                color_col = categorical_cols[1] if len(categorical_cols) > 1 else None
                fig = px.box(df, x=x_col, y=y_col, color=color_col, title=f"Box Plot of {y_col} by {x_col}")
                chart_type = "box"
            elif len(numeric_cols) >= 2:
                fig = px.box(df, x=keys[0], y=numeric_cols[0], title=f"Box Plot of {numeric_cols[0]} by {keys[0]}")
                chart_type = "box"
        elif "bar" in intent:
            # Grouped / Stacked bar chart
            numeric_cols = df.select_dtypes(include='number').columns
            categorical_cols = df.select_dtypes(exclude='number').columns
            if len(numeric_cols) > 0:
                y_col = numeric_cols[0]
                if len(categorical_cols) > 0:
                    x_col = categorical_cols[0]
                    color_col = categorical_cols[1] if len(categorical_cols) > 1 else (keys[1] if keys[1] != x_col and keys[1] != y_col else keys[2])
                else:
                    x_col = keys[0]
                    color_col = keys[1]
                fig = px.bar(df, x=x_col, y=y_col, color=color_col, barmode="group", title=f"Grouped Bar of {y_col} by {x_col}")
                chart_type = "bar"
            else:
                chart_type, fig = _build_table(df)
        else:
            # No keyword match — delegate to LLM chart selector
            try:
                data_types = {k: str(df[k].dtype) for k in keys}
                mapping = get_chart_mapping(intent, keys, data_types, len(df))
                chart_type = mapping.chart_type

                if chart_type == "line" and mapping.x_col in keys and mapping.y_col in keys:
                    color = mapping.color_col if mapping.color_col in keys else None
                    fig = px.line(df, x=mapping.x_col, y=mapping.y_col, color=color,
                                  title=mapping.title or f"{mapping.y_col} over {mapping.x_col}")
                elif chart_type == "bar" and mapping.x_col in keys and mapping.y_col in keys:
                    color = mapping.color_col if mapping.color_col in keys else None
                    fig = px.bar(df, x=mapping.x_col, y=mapping.y_col, color=color,
                                 barmode="group", title=mapping.title or f"{mapping.y_col} by {mapping.x_col}")
                elif chart_type == "scatter" and mapping.x_col in keys and mapping.y_col in keys:
                    color = mapping.color_col if mapping.color_col in keys else None
                    fig = px.scatter(df, x=mapping.x_col, y=mapping.y_col, color=color,
                                     title=mapping.title or f"Scatter of {mapping.y_col} vs {mapping.x_col}")
                else:
                    chart_type, fig = _build_table(df)
            except Exception as e:
                logger.warning(f"LLM chart selection failed, using table fallback: {e}")
                chart_type, fig = _build_table(df)

    # Fallback to a Plotly table if no other chart type fits
    if fig is None:
        chart_type, fig = _build_table(df)

    return {
        "chart_type": chart_type,
        "columns": keys,
        "plotly_json": json.loads(fig.to_json()) if fig else None
    }
