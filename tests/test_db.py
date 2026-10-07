import pytest
from backend.data.database import Database, QuerySecurityError

@pytest.fixture
def db():
    """Pytest fixture to initialize the database before tests."""
    database = Database()
    yield database
    database.close()

def test_valid_select_query(db):
    """Test that a basic analytical SELECT query works and returns a DataFrame."""
    sql = "SELECT region, SUM(revenue) as total_rev FROM sales GROUP BY region"
    df = db.execute_query(sql)
    
    assert not df.empty, "DataFrame should not be empty"
    assert "region" in df.columns
    assert "total_rev" in df.columns

def test_destructive_query_blocked(db):
    """Test that our pre-tool hook correctly blocks destructive SQL."""
    
    # This query doesn't start with SELECT, so it should hit the first security check
    with pytest.raises(QuerySecurityError, match="Only SELECT, SUMMARIZE, and WITH queries are allowed."):
        db.execute_query("DROP TABLE sales")
        
    # This query starts with SELECT, but contains a forbidden keyword, hitting the second check
    with pytest.raises(QuerySecurityError, match="forbidden keyword"):
        db.execute_query("SELECT * FROM sales; DELETE FROM sales WHERE region='North'")
        
    with pytest.raises(QuerySecurityError, match="Only SELECT, SUMMARIZE, and WITH queries are allowed."):
        db.execute_query("UPDATE sales SET revenue=0")

def test_invalid_sql_raises_value_error(db):
    """Test that invalid SQL syntax or hallucinated columns return a clear ValueError."""
    with pytest.raises(ValueError, match="Invalid SQL Query"):
        # Intentionally spelling the column wrong
        db.execute_query("SELECT non_existent_column FROM sales")
