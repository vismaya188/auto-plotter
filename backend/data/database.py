import os
import re
import duckdb
import pandas as pd
import logging
from backend.config import settings

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DatabaseConfigError(Exception):
    pass

class QuerySecurityError(Exception):
    """Raised when a query attempts a forbidden/destructive operation."""
    pass

class Database:
    """
    Manages the local DuckDB instance and provides safe access to the data.
    """
    def __init__(self):
        self.db_path = settings.duckdb_path
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.csv_path = os.path.join(base_dir, "data", "sample_sales.csv")

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # One-time init: if the db file doesn't exist yet, create and populate it,
        # then immediately close the write connection.
        if not os.path.exists(self.db_path):
            init_conn = duckdb.connect(database=self.db_path, read_only=False)
            self._initialize_db(init_conn)
            init_conn.close()

        # All query execution uses a read-only connection (matches threat model)
        self.conn = duckdb.connect(database=self.db_path, read_only=True)

    def _initialize_db(self, conn):
        """Loads the raw CSV into a DuckDB table named 'sales'. Requires a write connection."""
        if not os.path.exists(self.csv_path):
            raise DatabaseConfigError(f"Could not find sample dataset at {self.csv_path}")

        try:
            conn.execute(f"CREATE TABLE IF NOT EXISTS sales AS SELECT * FROM read_csv_auto('{self.csv_path}')")
            logger.info("Database initialized successfully with 'sales' table.")
        except Exception as e:
            logger.error(f"Failed to initialize database: {e}")
            raise

    def execute_query(self, query: str) -> pd.DataFrame:
        """
        Executes a SQL query securely. 
        Only permits SELECT statements and blocks destructive keywords.
        Returns the result as a Pandas DataFrame.
        """
        query_upper = query.upper().strip()

        # 1. Pre-tool Hook: Ensure it is a read-only query
        if not query_upper.startswith("SELECT"):
            raise QuerySecurityError("Only SELECT queries are allowed.")

        # 2. Pre-tool Hook: Block destructive keywords (basic implementation)
        forbidden_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE"]
        for keyword in forbidden_keywords:
            # Use regex to match exact words (prevents blocking a column named 'drop_off')
            if re.search(rf"\b{keyword}\b", query_upper):
                logger.warning(f"Blocked destructive SQL attempt: {query}")
                raise QuerySecurityError(f"Query contains forbidden keyword: '{keyword}'. Only read operations are permitted.")

        # 3. Execution & Error Handling
        try:
            # DuckDB returns a highly efficient Pandas DataFrame natively
            result_df = self.conn.execute(query).df()
            return result_df
        except duckdb.Error as e:
            # If the LLM generated invalid SQL (e.g. hallucinated a column name),
            # we catch it here and return a clear error message.
            logger.error(f"DuckDB Execution Error: {e}")
            raise ValueError(f"Invalid SQL Query: {str(e)}")

    def close(self):
        """Closes the connection gracefully."""
        self.conn.close()
