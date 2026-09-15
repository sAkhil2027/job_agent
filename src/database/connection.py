import threading
import sqlite3
import os
import re
import logging
from src.config import Config

logger = logging.getLogger(__name__)

# Global connection pool for PostgreSQL
_pg_pool = None
_pg_pool_lock = threading.Lock()

def get_postgres_pool():
    """Returns singleton ThreadedConnectionPool for PostgreSQL."""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                if not Config.DATABASE_URL:
                    raise ValueError("DATABASE_URL is not set but PostgreSQL is required.")
                try:
                    import psycopg2
                    from psycopg2.pool import ThreadedConnectionPool
                    logger.info("Initializing PostgreSQL ThreadedConnectionPool (min=1, max=10)...")
                    _pg_pool = ThreadedConnectionPool(
                        minconn=1,
                        maxconn=10,
                        dsn=Config.DATABASE_URL,
                        connect_timeout=10
                    )
                except Exception as e:
                    logger.error(f"Failed to create PostgreSQL ThreadedConnectionPool: {e}")
                    raise
    return _pg_pool

class PostgresCursorWrapper:
    """
    Cursor wrapper for PostgreSQL (psycopg2) that transparently translates
    SQLite-style SQL syntax ('?', 'INSERT OR IGNORE', 'PRAGMA') to PostgreSQL syntax.
    """
    def __init__(self, psycopg2_cursor):
        self._cursor = psycopg2_cursor

    def _translate_sql(self, sql: str) -> str:
        if not sql:
            return sql
        
        # 1. Ignore SQLite PRAGMA statements
        if sql.strip().upper().startswith("PRAGMA"):
            return ""

        # 2. Replace '?' positional placeholders with PostgreSQL '%s'
        translated = re.sub(r"\?", "%s", sql)

        # 3. Replace 'INSERT OR IGNORE INTO' with 'INSERT INTO ... ON CONFLICT DO NOTHING'
        if "INSERT OR IGNORE INTO" in translated.upper():
            translated = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", translated, flags=re.IGNORECASE)
            if "ON CONFLICT" not in translated.upper():
                translated += " ON CONFLICT DO NOTHING"

        # 4. Replace 'INSERT OR REPLACE INTO' with 'INSERT INTO ... ON CONFLICT DO NOTHING'
        elif "INSERT OR REPLACE INTO" in translated.upper():
            translated = re.sub(r"INSERT OR REPLACE INTO", "INSERT INTO", translated, flags=re.IGNORECASE)
            if "ON CONFLICT" not in translated.upper():
                translated += " ON CONFLICT DO NOTHING"

        return translated

    def execute(self, sql: str, params=None):
        translated_sql = self._translate_sql(sql)
        if not translated_sql:
            return self
        if params is not None:
            self._cursor.execute(translated_sql, params)
        else:
            self._cursor.execute(translated_sql)
        return self

    def executescript(self, sql_script: str):
        statements = sql_script.split(";")
        for stmt in statements:
            cleaned = stmt.strip()
            if cleaned:
                self.execute(cleaned)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size) if size else self._cursor.fetchmany()

    def executemany(self, sql: str, seq_of_parameters):
        translated_sql = self._translate_sql(sql)
        if not translated_sql:
            return self
        self._cursor.executemany(translated_sql, seq_of_parameters)
        return self

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PostgresConnectionWrapper:
    """
    Connection wrapper around pooled psycopg2 connection.
    """
    def __init__(self, psycopg2_conn, pool=None):
        self._conn = psycopg2_conn
        self._pool = pool
        self._closed = False

    def cursor(self):
        return PostgresCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        try:
            self._conn.rollback()
        except Exception:
            pass

    def close(self):
        if not self._closed:
            self._closed = True
            if self._pool:
                try:
                    self._pool.putconn(self._conn)
                except Exception as e:
                    logger.warning(f"Error returning connection to pool: {e}")
            else:
                try:
                    self._conn.close()
                except Exception:
                    pass

    def execute(self, sql: str, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur


def get_connection():
    """
    Returns active DB connection: PostgreSQL if USE_POSTGRES=true or ENVIRONMENT=production,
    otherwise defaults to fast local SQLite (data/job_matcher.db).

    If in production or USE_POSTGRES=true, failure to connect to PostgreSQL raises an error
    immediately rather than silently falling back to ephemeral container disk.
    """
    use_postgres = (
        os.getenv("USE_POSTGRES", "false").lower() in ("true", "1", "yes") or
        getattr(Config, "ENVIRONMENT", "development") == "production"
    )

    if use_postgres:
        if not Config.DATABASE_URL:
            raise RuntimeError("USE_POSTGRES=true or ENVIRONMENT=production, but DATABASE_URL is not set.")
        try:
            pool = get_postgres_pool()
            conn = pool.getconn()
            return PostgresConnectionWrapper(conn, pool=pool)
        except Exception as e:
            logger.error(f"PostgreSQL connection failed: {e}")
            # Strict fail-fast in production / PostgreSQL mode
            raise RuntimeError(f"PostgreSQL connection failed in production mode: {e}") from e

    # Local SQLite Fallback for development
    db_dir = os.path.join(Config.BASE_DIR, "data")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "job_matcher.db")

    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to SQLite database: {e}")
        raise


def initialize_database():
    """Create tables if they don't exist by executing schema.sql."""
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            schema_sql = f.read()
        
        cursor.executescript(schema_sql)
        conn.commit()
        
        # Safely migrate schema by adding matches columns if they don't exist
        for col, col_type in [("matched_skills", "TEXT"), ("missing_skills", "TEXT"), ("reasoning", "TEXT"), ("match_version", "TEXT"), ("resume_hash", "TEXT"), ("soft_matches", "TEXT"), ("matched_capabilities", "TEXT"), ("score_breakdown", "TEXT"), ("level1_key", "TEXT")]:
            try:
                cursor.execute(f"ALTER TABLE matches ADD COLUMN {col} {col_type};")
                conn.commit()
            except Exception:
                conn.rollback()

        # Safely migrate jobs table columns
        for col, col_type in [("jd_hash", "TEXT"), ("parser_version", "TEXT")]:
            try:
                cursor.execute(f"ALTER TABLE jobs ADD COLUMN {col} {col_type};")
                conn.commit()
            except Exception:
                conn.rollback()

        # Safely migrate SQLite application_queue table if CHECK constraint is outdated
        if isinstance(conn, sqlite3.Connection):
            try:
                cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='application_queue';")
                tbl_row = cursor.fetchone()
                if tbl_row and tbl_row[0] and "'RUNNING'" not in tbl_row[0]:
                    logger.info("Migrating application_queue SQLite table schema for new statuses...")
                    cursor.execute("PRAGMA foreign_keys = OFF;")
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS application_queue_new (
                            id TEXT PRIMARY KEY,
                            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                            resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
                            status TEXT NOT NULL DEFAULT 'QUEUED' CHECK(
                                status IN (
                                    'QUEUED', 'RUNNING', 'PROCESSING', 'FORM_FILLING', 
                                    'AWAITING_USER_SUBMIT', 'SUBMITTED', 'COMPLETED', 
                                    'FAILED', 'RETRY', 'RETRYING'
                                )
                            ),
                            attempt_count INTEGER DEFAULT 0,
                            attempts INTEGER DEFAULT 0,
                            error_message TEXT,
                            error_msg TEXT,
                            browser_session_id TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            started_at TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            completed_at TIMESTAMP,
                            CONSTRAINT unique_queue UNIQUE (resume_id, job_id)
                        );
                    """)
                    cursor.execute("""
                        INSERT OR IGNORE INTO application_queue_new (id, job_id, resume_id, status, attempts, created_at, updated_at)
                        SELECT id, job_id, resume_id, status, attempts, created_at, updated_at FROM application_queue;
                    """)
                    cursor.execute("DROP TABLE application_queue;")
                    cursor.execute("ALTER TABLE application_queue_new RENAME TO application_queue;")
                    cursor.execute("PRAGMA foreign_keys = ON;")
                    conn.commit()
            except Exception as mig_err:
                logger.warning(f"Note on application_queue status migration: {mig_err}")

        # Safely migrate application_queue table columns
        app_queue_cols = [
            ("error_msg", "TEXT"),
            ("error_message", "TEXT"),
            ("attempt_count", "INTEGER DEFAULT 0"),
            ("browser_session_id", "TEXT"),
            ("started_at", "TIMESTAMP"),
            ("completed_at", "TIMESTAMP")
        ]
        for col, col_type in app_queue_cols:
            try:
                cursor.execute(f"ALTER TABLE application_queue ADD COLUMN {col} {col_type};")
                conn.commit()
            except Exception:
                conn.rollback()

        # Safely ensure indexes exist
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_queue_polling ON application_queue(status, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_queue_id ON application_audit_logs(queue_id, created_at);")
            conn.commit()
        except Exception:
            conn.rollback()

        conn.commit()
        logger.info("Database tables and indexes initialized successfully.")

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Database initialization failed: {e}")
        raise
    finally:
        if conn:
            conn.close()


def execute_db_with_retry(query_fn, max_retries: int = 5, initial_backoff: float = 0.05):
    """
    Executes a database function and retries on locking errors.
    """
    import time
    import random
    
    backoff = initial_backoff
    for attempt in range(max_retries + 1):
        conn = None
        try:
            conn = get_connection()
            result = query_fn(conn)
            return result
        except Exception as e:
            err_msg = str(e).lower()
            if "locked" in err_msg or "busy" in err_msg:
                if attempt < max_retries:
                    sleep_time = backoff + random.uniform(0.01, 0.05)
                    logger.warning(f"Database locked. Retrying in {sleep_time:.3f}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(sleep_time)
                    backoff *= 2.0
                    continue
            logger.error(f"Database operation failed: {e}")
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass


def add_candidate_answer(question_key: str, question_pattern: str, answer_value: str) -> str:
    """Adds or replaces a candidate answer rule in candidate_answers table."""
    import uuid
    ans_id = str(uuid.uuid4())

    def db_op(conn):
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO candidate_answers (id, question_key, question_pattern, answer_value)
            VALUES (?, ?, ?, ?)
        """, (ans_id, question_key, question_pattern, answer_value))
        conn.commit()
        return ans_id

    return execute_db_with_retry(db_op)


def get_all_candidate_answers() -> list:
    """Returns list of all pre-stored candidate Q&A rules."""
    def db_op(conn):
        cursor = conn.cursor()
        cursor.execute("SELECT id, question_key, question_pattern, answer_value, created_at FROM candidate_answers ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "question_key": r[1],
                "question_pattern": r[2],
                "answer_value": r[3],
                "created_at": r[4]
            } for r in rows
        ]

    return execute_db_with_retry(db_op) or []


def delete_candidate_answer(answer_id: str) -> bool:
    """Deletes a candidate answer rule by ID."""
    def db_op(conn):
        cursor = conn.cursor()
        cursor.execute("DELETE FROM candidate_answers WHERE id = ? OR question_key = ?", (answer_id, answer_id))
        conn.commit()
        return cursor.rowcount > 0

    return bool(execute_db_with_retry(db_op))

