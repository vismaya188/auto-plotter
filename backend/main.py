import asyncio
import logging
import os
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional

from backend.config import settings
from backend.agent.graph import agent_app
from backend.agent.context import AgentJournal

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Prompt to Plot API",
    description="Agentic BI — Prompt to Plot with multi-source data ingestion.",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# Request / Response models
# ──────────────────────────────────────────────

class QueryRequest(BaseModel):
    prompt: str
    session_id: Optional[str] = None  # Routes to uploaded dataset when set
    chat_history: Optional[list] = None


class PostgresConnectRequest(BaseModel):
    host: str = Field(..., description="PostgreSQL host")
    port: int = Field(5432, description="PostgreSQL port")
    dbname: str = Field(..., description="Database name")
    user: str = Field(..., description="Username")
    password: str = Field(..., description="Password")
    table_name: str = Field(..., description="Table to import")
    session_id: Optional[str] = None


class UrlConnectRequest(BaseModel):
    url: str = Field(..., description="Public HTTPS or s3:// URL (CSV, Parquet, JSON, Google Sheets)")
    session_id: Optional[str] = None


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

async def _run_ingestion(fn, *args) -> dict:
    """
    Runs a synchronous ingestion function in a thread pool so the
    FastAPI event loop stays unblocked during heavy I/O.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


def _complete_ingestion(session_id: str, source_type: str, source_label: str, ingest_result: dict) -> dict:
    """
    After ingestion succeeds, runs auto-discovery and registers the session.
    Returns the final response payload.
    """
    from backend.semantic.auto_discover import auto_discover_semantics
    from backend.data.session_store import register_session, get_session

    table_name = ingest_result["table_name"]

    try:
        semantic = auto_discover_semantics(session_id)
    except Exception as e:
        logger.warning(f"Auto-discovery failed for session {session_id}: {e}")
        semantic = {}

    register_session(
        session_id=session_id,
        source_type=source_type,
        source_label=source_label,
        table_name=table_name,
        row_count=ingest_result["rows"],
        columns=ingest_result.get("columns", []),
        semantic=semantic
    )

    session = get_session(session_id)

    return {
        "status": "ready",
        "session_id": session_id,
        "table_name": table_name,
        "total_tables": len(session.get("tables", {})),
        "row_count": ingest_result["rows"],
        "columns": [c["column_name"] for c in ingest_result.get("columns", [])],
        "message": f"Table '{table_name}' loaded successfully. Total tables in session: {len(session.get('tables', {}))}."
    }


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None)
):
    """
    Upload a CSV, Excel (.xlsx), JSON, or Parquet file.
    Returns a session_id that must be sent with all subsequent /query calls.
    """
    from backend.data.ingestion import (
        validate_file, ingest_csv, ingest_excel, ingest_json
    )

    session_id = session_id or str(uuid.uuid4())
    filename = file.filename or "upload"

    try:
        file_bytes = await file.read()
        ext = validate_file(file_bytes, filename)  # raises ValueError on violations
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))

    try:
        if ext == "csv":
            result = await _run_ingestion(ingest_csv, file_bytes, filename, session_id)
        elif ext == "xlsx":
            result = await _run_ingestion(ingest_excel, file_bytes, filename, session_id)
        elif ext == "xls":
            raise HTTPException(status_code=415, detail="Legacy .xls not supported. Re-save as .xlsx.")
        elif ext == "json":
            result = await _run_ingestion(ingest_json, file_bytes, filename, session_id)
        else:
            raise HTTPException(status_code=415, detail=f"Unsupported extension: .{ext}")

        return _complete_ingestion(session_id, ext, filename, result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed for session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.post("/connect/postgres")
async def connect_postgres(request: PostgresConnectRequest):
    """
    Connects to a PostgreSQL database, copies the specified table
    into a session DuckDB, and auto-discovers its semantic model.
    """
    from backend.data.ingestion import ingest_postgres

    session_id = request.session_id or str(uuid.uuid4())

    try:
        result = await _run_ingestion(
            ingest_postgres,
            request.host, request.port, request.dbname,
            request.user, request.password,
            request.table_name, session_id
        )
        label = f"{request.host}/{request.dbname}.{request.table_name}"
        return _complete_ingestion(session_id, "postgres", label, result)

    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}")
        # Don't expose raw PG error messages (may contain credentials)
        raise HTTPException(
            status_code=500,
            detail="Failed to connect to PostgreSQL. Check credentials and table name."
        )


@app.post("/connect/url")
async def connect_url(request: UrlConnectRequest):
    """
    Reads a remote CSV, Parquet, JSON, or Google Sheets URL into a session DB.
    Supports: HTTPS URLs and s3:// URIs.
    """
    from backend.data.ingestion import ingest_url

    session_id = request.session_id or str(uuid.uuid4())

    try:
        result = await _run_ingestion(ingest_url, request.url, session_id)
        return _complete_ingestion(session_id, "url", request.url, result)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"URL ingestion failed ({request.url}): {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read URL: {str(e)}")


@app.get("/session/{session_id}")
async def get_session_info(session_id: str):
    """Returns metadata about all tables in a loaded data session."""
    from backend.data.session_store import get_session
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found. Please upload data first.")
    tables = session.get("tables", {})
    table_summary = {
        name: {
            "row_count": info.get("row_count"),
            "columns": [c["column_name"] if isinstance(c, dict) else c for c in info.get("columns", [])]
        }
        for name, info in tables.items()
    }
    foreign_keys = session.get("semantic", {}).get("foreign_keys", [])
    return {
        "session_id": session_id,
        "total_tables": len(tables),
        "tables": table_summary,
        "foreign_keys": foreign_keys,
    }


@app.post("/query")
async def run_query(request: QueryRequest):
    from fastapi.responses import StreamingResponse
    import json

    session_id = request.session_id or str(uuid.uuid4())
    journal = AgentJournal(session_id=session_id)

    # Session recovery: rehydrate from last checkpoint if available
    recovered_state = journal.rehydrate_state()
    if recovered_state:
        initial_state = recovered_state
        initial_state["_session_id"] = session_id
        initial_state["user_prompt"] = request.prompt  # Always use latest prompt
        initial_state["chat_history"] = request.chat_history or []
    else:
        initial_state = {
            "_session_id": session_id,
            "session_id": session_id,
            "user_prompt": request.prompt,
            "chat_history": request.chat_history or [],
            "sql_retries": 0,
            "errors": ""
        }

    async def event_generator():
        final_merged_state = initial_state.copy()
        
        try:
            yield f"data: {json.dumps({'event': 'progress', 'message': '🚀 Initializing agent...'})}\n\n"
            
            async for s in agent_app.astream(initial_state):
                node_name = list(s.keys())[0]
                state_data = s[node_name]
                final_merged_state.update(state_data)
                journal.checkpoint(final_merged_state)
                
                # Friendly progress messages
                msg = f"⚙️ Processing step: {node_name}"
                if node_name == "understand_intent": msg = "🔍 Understanding your question..."
                elif node_name == "lookup_semantics": msg = "📚 Checking data dictionary..."
                elif node_name == "generate_sql": msg = "🔨 Generating database query..."
                elif node_name == "validate_and_retrieve": msg = "✅ Validating and fetching data..."
                elif node_name == "select_visualization": msg = "📊 Building chart..."
                elif node_name == "generate_insight": msg = "🧠 Extracting insights..."
                
                yield f"data: {json.dumps({'event': 'progress', 'message': msg})}\n\n"

            trace = final_merged_state.get("trace")
            if trace:
                trace.save(final_merged_state)

            journal.clear_checkpoint()

            final_result = {
                "status": final_merged_state.get("status", "unknown"),
                "visualization": final_merged_state.get("visualization", {}),
                "insights": final_merged_state.get("insights", {}),
                "generated_sql": final_merged_state.get("generated_sql", ""),
                "errors": final_merged_state.get("errors", ""),
                "session_id": session_id
            }
            
            import math
            def clean_nan(obj):
                if isinstance(obj, float):
                    if math.isnan(obj) or math.isinf(obj):
                        return None
                    return obj
                elif isinstance(obj, dict):
                    return {k: clean_nan(v) for k, v in obj.items()}
                elif isinstance(obj, list) or isinstance(obj, tuple):
                    return [clean_nan(v) for v in obj]
                return obj

            yield f"data: {json.dumps({'event': 'complete', 'result': clean_nan(final_result)})}\n\n"
            
        except Exception as e:
            logger.error(f"Agent streaming error: {e}")
            yield f"data: {json.dumps({'event': 'error', 'error': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Prompt to Plot", "version": "0.2.0"}


# Mount frontend static files — must be LAST (catches all unmatched routes)
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
os.makedirs(frontend_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=8000, reload=True)
