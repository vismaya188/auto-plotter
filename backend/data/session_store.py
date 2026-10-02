import json
import os
import threading
from typing import Optional

SESSION_DB_DIR = os.path.join("data", "sessions")
REGISTRY_PATH = os.path.join(SESSION_DB_DIR, "registry.json")

# Thread lock to prevent concurrent registry writes from corrupting the file
_registry_lock = threading.Lock()


def _load() -> dict:
    """Reads the registry from disk. Returns empty dict if not yet created."""
    if not os.path.exists(REGISTRY_PATH):
        return {}
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(registry: dict):
    """Persists the registry to disk atomically."""
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    # Write to temp file then rename for atomic replacement
    tmp_path = REGISTRY_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    os.replace(tmp_path, REGISTRY_PATH)


def register_session(
    session_id: str,
    source_type: str,
    source_label: str,
    row_count: int,
    columns: list,
    semantic: dict
):
    """
    Stores metadata for an ingested session.
    source_type: 'csv' | 'excel' | 'json' | 'postgres' | 's3_url'
    source_label: friendly display name (filename, table name, URL)
    """
    with _registry_lock:
        registry = _load()
        registry[session_id] = {
            "source_type": source_type,
            "source_label": source_label,
            "row_count": row_count,
            "columns": columns,
            "semantic": semantic
        }
        _save(registry)


def get_session(session_id: str) -> Optional[dict]:
    """Returns full session metadata or None if not found."""
    return _load().get(session_id)


def get_semantic(session_id: str) -> Optional[dict]:
    """Returns just the semantic model for a session, or None."""
    session = get_session(session_id)
    return session["semantic"] if session else None


def session_has_data(session_id: str) -> bool:
    """Returns True if this session has ingested data."""
    return session_id is not None and get_session(session_id) is not None


def get_session_db_path(session_id: str) -> str:
    """Returns the filesystem path for this session's DuckDB file."""
    return os.path.join(SESSION_DB_DIR, f"{session_id}.duckdb")
