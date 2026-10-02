import os
import uuid
import tempfile
import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.data.session_store import get_session_db_path, session_has_data, SESSION_DB_DIR

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_sessions():
    """Ensure sessions dir exists and clean up after tests."""
    os.makedirs(SESSION_DB_DIR, exist_ok=True)
    yield
    # Cleanup logic (optional, we could delete test .duckdb files)


def test_upload_csv_endpoint():
    # 1. Create a dummy CSV file
    csv_content = b"id,name,revenue,date\n1,Alice,100,2023-01-01\n2,Bob,200,2023-01-02\n3,Charlie,300,2023-01-03\n"
    
    session_id = str(uuid.uuid4())
    
    # 2. Make the request to the /upload endpoint
    files = {'file': ('test.csv', csv_content, 'text/csv')}
    data = {'session_id': session_id}
    
    response = client.post("/upload", files=files, data=data)
    
    # 3. Assert response is successful
    assert response.status_code == 200, f"Upload failed: {response.text}"
    
    result = response.json()
    assert result["status"] == "ready"
    assert result["session_id"] == session_id
    assert result["row_count"] == 3
    
    # Check if expected columns exist
    cols = result["columns"]
    assert "id" in cols
    assert "name" in cols
    assert "revenue" in cols
    assert "date" in cols
    
    # 4. Check if session_store saved it
    assert session_has_data(session_id) is True
    
    # 5. Check if DuckDB file exists
    db_path = get_session_db_path(session_id)
    assert os.path.exists(db_path)


def test_query_uploaded_data():
    # 1. First upload data
    csv_content = b"region,sales\nNorth,500\nSouth,800\nEast,200\n"
    session_id = str(uuid.uuid4())
    
    files = {'file': ('sales.csv', csv_content, 'text/csv')}
    upload_res = client.post("/upload", files=files, data={'session_id': session_id})
    assert upload_res.status_code == 200

    # 2. Now run a query against it
    query_payload = {
        "prompt": "Show me total sales by region",
        "session_id": session_id
    }
    
    query_res = client.post("/query", json=query_payload)
    assert query_res.status_code == 200
    
    query_result = query_res.json()
    assert query_result["status"] == "insight_generated"
    assert "sales" in query_result.get("generated_sql", "").lower()
