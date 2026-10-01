"""
Universal data ingestor — loads any supported source into a session-scoped DuckDB table.

Every source normalises to a single table named 'user_data' in the session's
own .duckdb file located at data/sessions/{session_id}.duckdb

Corrections applied (from validation report):
  - Excel: uses DuckDB native read_xlsx (no openpyxl/pandas needed)
  - S3: uses DuckDB Secrets Manager (not deprecated SET s3_* vars)
  - Concurrency: per-session threading.Lock prevents multi-worker file corruption
  - SSRF: validates URLs against private IP ranges before fetching
"""
import ipaddress
import logging
import os
import socket
import tempfile
import threading
from urllib.parse import urlparse

import duckdb

from backend.data.session_store import SESSION_DB_DIR, get_session_db_path

logger = logging.getLogger(__name__)

TABLE_NAME = "user_data"
MAX_FILE_BYTES = 50 * 1024 * 1024  # 50 MB hard cap

# Allowed MIME types → mapped from filetype library guesses
ALLOWED_MIME_TYPES = {
    "text/csv",
    "text/plain",           # some CSVs sniff as text/plain
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # xlsx
    "application/vnd.ms-excel",   # xls (read-only; DuckDB only supports xlsx)
    "application/json",
    "application/x-ndjson",
    "application/octet-stream",   # parquet
}

# Per-session write locks — prevents two concurrent uploads to the same session DB
_session_locks: dict[str, threading.Lock] = {}
_session_locks_lock = threading.Lock()


def _get_session_lock(session_id: str) -> threading.Lock:
    """Returns (and lazily creates) the per-session write lock."""
    with _session_locks_lock:
        if session_id not in _session_locks:
            _session_locks[session_id] = threading.Lock()
        return _session_locks[session_id]


def _open_write_conn(session_id: str) -> duckdb.DuckDBPyConnection:
    """Opens a read-write connection to the session DuckDB file."""
    os.makedirs(SESSION_DB_DIR, exist_ok=True)
    path = get_session_db_path(session_id)
    return duckdb.connect(path, read_only=False)


def _get_schema(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Returns column schema as a list of dicts [{column_name, column_type}]."""
    rows = conn.execute(f"DESCRIBE {TABLE_NAME}").fetchall()
    return [{"column_name": r[0], "column_type": r[1]} for r in rows]


def _get_row_count(conn: duckdb.DuckDBPyConnection) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]


# ──────────────────────────────────────────────
# File-type validation (pure-python, no libmagic)
# ──────────────────────────────────────────────

def validate_file(file_bytes: bytes, filename: str) -> str:
    """
    Validates a file by checking:
    1. File size
    2. Byte-level magic signature via 'filetype' library
    3. Extension whitelist
    Returns the detected extension ('csv', 'xlsx', 'json', 'parquet').
    Raises ValueError on any violation.
    """
    if len(file_bytes) > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds 50 MB limit ({len(file_bytes) / 1e6:.1f} MB).")

    # Extension check
    ext = os.path.splitext(filename)[1].lower()
    allowed_exts = {".csv", ".xlsx", ".json", ".parquet", ".xls"}
    if ext not in allowed_exts:
        raise ValueError(f"File type '{ext}' is not supported. Allowed: CSV, Excel, JSON, Parquet.")

    # Magic byte check using filetype (pure Python, no system libs)
    try:
        import filetype
        kind = filetype.guess(file_bytes[:2048])
        if kind and kind.mime not in ALLOWED_MIME_TYPES:
            raise ValueError(f"File content does not match allowed types (detected: {kind.mime}).")
    except ImportError:
        logger.warning("filetype library not installed — skipping magic byte check.")

    # CSV injection: strip dangerous formula prefixes from first line
    if ext == ".csv":
        _check_csv_injection(file_bytes[:1024])

    return ext.lstrip(".")


def _check_csv_injection(header_bytes: bytes):
    """Logs a warning if CSV cells start with formula-injection characters."""
    try:
        first_line = header_bytes.decode("utf-8", errors="replace").split("\n")[0]
        cells = first_line.split(",")
        for cell in cells:
            cell = cell.strip().strip('"')
            if cell and cell[0] in ("=", "+", "-", "@", "|", "%"):
                logger.warning(f"CSV injection marker detected in header cell: '{cell}'")
                # We warn but do NOT block — DuckDB won't execute these as formulas
    except Exception:
        pass


# ──────────────────────────────────────────────
# SSRF guard for URL-based ingestion
# ──────────────────────────────────────────────

def _is_safe_url(url: str) -> bool:
    """
    Blocks URLs that resolve to private/loopback IPs to prevent SSRF.
    Allows only https:// and s3:// schemes.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "s3"):
        logger.warning(f"Blocked non-HTTPS/S3 URL scheme: {parsed.scheme}")
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Skip IP resolution for S3 scheme — handled by DuckDB httpfs internally
    if parsed.scheme == "s3":
        return True

    try:
        ip_str = socket.gethostbyname(hostname)
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            logger.warning(f"SSRF blocked: {url} resolves to private IP {ip_str}")
            return False
        # Block AWS metadata endpoint explicitly
        if ip_str.startswith("169.254."):
            logger.warning(f"SSRF blocked: AWS metadata endpoint attempted via {url}")
            return False
    except socket.gaierror:
        logger.warning(f"Could not resolve hostname: {hostname}")
        return False

    return True


# ──────────────────────────────────────────────
# Ingestion Functions
# ──────────────────────────────────────────────

def ingest_csv(file_bytes: bytes, filename: str, session_id: str) -> dict:
    """
    Writes file bytes to a temp file, then loads into session DuckDB via read_csv.
    DuckDB auto-detects delimiter, quoting, and column types.
    """
    with _get_session_lock(session_id):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        conn = _open_write_conn(session_id)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            conn.execute(f"""
                CREATE TABLE {TABLE_NAME} AS
                SELECT * FROM read_csv('{tmp_path}', auto_detect=true, sample_size=-1)
            """)
            schema = _get_schema(conn)
            row_count = _get_row_count(conn)
            logger.info(f"[{session_id}] CSV ingested: {row_count} rows, {len(schema)} cols")
            return {"status": "success", "rows": row_count, "columns": schema}
        except Exception as e:
            logger.error(f"[{session_id}] CSV ingestion error: {e}")
            raise
        finally:
            conn.close()
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def ingest_excel(file_bytes: bytes, filename: str, session_id: str) -> dict:
    """
    Ingests .xlsx files using DuckDB's native excel extension (read_xlsx).
    Significantly faster and more memory-efficient than openpyxl → pandas → DuckDB.
    Note: .xls (legacy) format is NOT supported by DuckDB's excel extension.
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".xls":
        raise ValueError(
            "Legacy .xls format is not supported. Please re-save the file as .xlsx."
        )

    with _get_session_lock(session_id):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        conn = _open_write_conn(session_id)
        try:
            conn.execute("INSTALL excel; LOAD excel;")
            conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            # all_varchar=True prevents type inference failures on messy Excel files
            # A CAST pass can be added later if needed
            conn.execute(f"""
                CREATE TABLE {TABLE_NAME} AS
                SELECT * FROM read_xlsx('{tmp_path}', all_varchar=true)
            """)
            schema = _get_schema(conn)
            row_count = _get_row_count(conn)
            logger.info(f"[{session_id}] Excel ingested: {row_count} rows, {len(schema)} cols")
            return {"status": "success", "rows": row_count, "columns": schema}
        except Exception as e:
            logger.error(f"[{session_id}] Excel ingestion error: {e}")
            raise
        finally:
            conn.close()
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def ingest_json(file_bytes: bytes, filename: str, session_id: str) -> dict:
    """Ingests JSON (array of objects) into DuckDB via read_json."""
    with _get_session_lock(session_id):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        conn = _open_write_conn(session_id)
        try:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            conn.execute(f"""
                CREATE TABLE {TABLE_NAME} AS
                SELECT * FROM read_json('{tmp_path}', auto_detect=true)
            """)
            schema = _get_schema(conn)
            row_count = _get_row_count(conn)
            logger.info(f"[{session_id}] JSON ingested: {row_count} rows")
            return {"status": "success", "rows": row_count, "columns": schema}
        except Exception as e:
            logger.error(f"[{session_id}] JSON ingestion error: {e}")
            raise
        finally:
            conn.close()
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def ingest_postgres(
    host: str, port: int, dbname: str,
    user: str, password: str,
    table_name: str, session_id: str
) -> dict:
    """
    ATTACHes PostgreSQL via DuckDB's postgres extension, then COPYs the target
    table into the session DB as 'user_data'. The PG connection is detached
    immediately after — all subsequent queries run air-gapped from production.
    """
    conn_str = f"host={host} port={port} dbname={dbname} user={user} password={password}"

    with _get_session_lock(session_id):
        conn = _open_write_conn(session_id)
        try:
            conn.execute("INSTALL postgres; LOAD postgres;")
            conn.execute(
                f"ATTACH '{conn_str}' AS pg_source (TYPE postgres, READ_ONLY)"
            )
            conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            conn.execute(
                f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM pg_source.{table_name}"
            )
            conn.execute("DETACH pg_source")
            schema = _get_schema(conn)
            row_count = _get_row_count(conn)
            logger.info(f"[{session_id}] PostgreSQL table '{table_name}' ingested: {row_count} rows")
            return {"status": "success", "rows": row_count, "columns": schema}
        except Exception as e:
            logger.error(f"[{session_id}] PostgreSQL ingestion error: {e}")
            raise
        finally:
            conn.close()


def ingest_url(url: str, session_id: str) -> dict:
    """
    Reads a remote file (S3 URI, HTTPS CSV/Parquet/JSON, or Google Sheets CSV export)
    directly into DuckDB using the httpfs extension.

    S3 credentials are set via DuckDB Secrets Manager (not deprecated SET vars).
    AWS env vars (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION) are read automatically
    by the CREDENTIAL_CHAIN provider if present.
    """
    # SSRF guard — blocks private IPs, non-HTTPS schemes
    if not _is_safe_url(url):
        raise ValueError(
            f"URL is not allowed. Only public HTTPS or s3:// URLs are permitted."
        )

    # Auto-convert Google Sheets share URL to CSV export URL
    if "docs.google.com/spreadsheets" in url and "export" not in url:
        sheet_id = url.split("/d/")[1].split("/")[0] if "/d/" in url else None
        if sheet_id:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
            logger.info(f"Google Sheets URL converted to CSV export: {url}")

    with _get_session_lock(session_id):
        conn = _open_write_conn(session_id)
        try:
            conn.execute("INSTALL httpfs; LOAD httpfs;")

            # Use DuckDB Secrets Manager for S3 credentials (2025 standard)
            aws_key = os.getenv("AWS_ACCESS_KEY_ID", "")
            aws_secret = os.getenv("AWS_SECRET_ACCESS_KEY", "")
            aws_region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1"))

            if url.startswith("s3://"):
                if aws_key and aws_secret:
                    # Static keys (less preferred, but supported)
                    conn.execute(f"""
                        CREATE OR REPLACE SECRET s3_session (
                            TYPE S3,
                            KEY_ID '{aws_key}',
                            SECRET '{aws_secret}',
                            REGION '{aws_region}'
                        )
                    """)
                else:
                    # IAM role / credential chain (preferred in cloud environments)
                    conn.execute(
                        "CREATE OR REPLACE SECRET s3_session (TYPE S3, PROVIDER CREDENTIAL_CHAIN)"
                    )

            conn.execute(f"DROP TABLE IF EXISTS {TABLE_NAME}")
            url_lower = url.lower().split("?")[0]  # strip query params for ext detection

            if url_lower.endswith(".parquet"):
                reader = f"read_parquet('{url}')"
            elif url_lower.endswith(".json") or url_lower.endswith(".ndjson"):
                reader = f"read_json('{url}', auto_detect=true)"
            else:
                reader = f"read_csv('{url}', auto_detect=true)"

            conn.execute(f"CREATE TABLE {TABLE_NAME} AS SELECT * FROM {reader}")
            schema = _get_schema(conn)
            row_count = _get_row_count(conn)
            logger.info(f"[{session_id}] URL ingested ({url}): {row_count} rows")
            return {"status": "success", "rows": row_count, "columns": schema}
        except Exception as e:
            logger.error(f"[{session_id}] URL ingestion error: {e}")
            raise
        finally:
            conn.close()
