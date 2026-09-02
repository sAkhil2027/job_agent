import uuid
import datetime
import logging

from src.config import Config
from src.database.connection import execute_db_with_retry

logger = logging.getLogger(__name__)

def log_audit_event(
    queue_id: str,
    to_status: str,
    from_status: str = None,
    screenshot_path: str = None,
    submission_result: str = None,
    error_details: str = None
):
    """
    Logs a detailed audit record for an application status transition, screenshot artifact,
    or submission response into the application_audit_logs table.
    """
    audit_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()

    def insert_audit(conn):
        cursor = conn.cursor()
        # Fetch queue details if from_status, job_id, or resume_id are needed
        cursor.execute("SELECT job_id, resume_id, status FROM application_queue WHERE id = ?", (queue_id,))
        row = cursor.fetchone()
        if not row:
            logger.warning(f"Cannot log audit event: Queue ID {queue_id} not found.")
            return

        job_id, resume_id, current_status = row
        prev_status = from_status or current_status

        cursor.execute("""
            INSERT INTO application_audit_logs 
            (id, queue_id, job_id, resume_id, from_status, to_status, screenshot_path, submission_result, error_details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (audit_id, queue_id, job_id, resume_id, prev_status, to_status, screenshot_path, submission_result, error_details, now))
        conn.commit()

    try:
        execute_db_with_retry(insert_audit)
    except Exception as e:
        logger.error(f"Failed to log audit event for queue {queue_id}: {e}")

def get_application_audit_history(queue_id: str):
    """
    Retrieves the complete chronological audit trail history for an application.
    """
    def fetch_history(conn):
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, queue_id, job_id, resume_id, from_status, to_status, 
                   screenshot_path, submission_result, error_details, created_at
            FROM application_audit_logs
            WHERE queue_id = ?
            ORDER BY created_at ASC
        """, (queue_id,))
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "queue_id": r[1],
                "job_id": r[2],
                "resume_id": r[3],
                "from_status": r[4],
                "to_status": r[5],
                "screenshot_path": r[6],
                "submission_result": r[7],
                "error_details": r[8],
                "created_at": r[9]
            }
            for r in rows
        ]

    return execute_db_with_retry(fetch_history)

def recover_stale_applications():
    """
    Finds applications stuck in active processing states (RUNNING, PROCESSING, FORM_FILLING)
    where started_at exceeds APPLICATION_TIMEOUT, and resets them to RETRYING or FAILED.
    """
    def reset_stale(conn):
        cursor = conn.cursor()
        timeout_seconds = Config.APPLICATION_TIMEOUT
        max_retries = Config.MAX_APPLICATION_RETRIES
        now_dt = datetime.datetime.utcnow()
        cutoff_iso = (now_dt - datetime.timedelta(seconds=timeout_seconds)).isoformat()
        now_iso = now_dt.isoformat()

        # Find stuck tasks
        cursor.execute("""
            SELECT id, status, COALESCE(attempt_count, attempts, 0)
            FROM application_queue
            WHERE status IN ('RUNNING', 'PROCESSING', 'FORM_FILLING')
              AND started_at IS NOT NULL
              AND started_at < ?
        """, (cutoff_iso,))
        stale_rows = cursor.fetchall()

        for queue_id, current_status, attempts in stale_rows:
            new_attempts = attempts + 1
            if new_attempts >= max_retries:
                err_msg = 'Worker timeout exceeded (max retries reached)'
                logger.warning(f"[Queue Recovery] Task {queue_id[:8]} exceeded timeout ({timeout_seconds}s) and reached max retries. Marking FAILED.")
                cursor.execute("""
                    UPDATE application_queue
                    SET status = 'FAILED',
                        attempt_count = ?,
                        attempts = ?,
                        error_message = ?,
                        error_msg = ?,
                        completed_at = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (new_attempts, new_attempts, err_msg, err_msg, now_iso, now_iso, queue_id))
                conn.commit()
                log_audit_event(queue_id, to_status='FAILED', from_status=current_status, error_details=err_msg)
            else:
                err_msg = 'Worker timeout exceeded (scheduled for retry)'
                logger.info(f"[Queue Recovery] Task {queue_id[:8]} exceeded timeout ({timeout_seconds}s). Resetting to RETRYING (Attempt {new_attempts}/{max_retries}).")
                cursor.execute("""
                    UPDATE application_queue
                    SET status = 'RETRYING',
                        attempt_count = ?,
                        attempts = ?,
                        error_message = ?,
                        error_msg = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (new_attempts, new_attempts, err_msg, err_msg, now_iso, queue_id))
                conn.commit()
                log_audit_event(queue_id, to_status='RETRYING', from_status=current_status, error_details=err_msg)

    try:
        execute_db_with_retry(reset_stale)
    except Exception as e:
        logger.error(f"Error in recover_stale_applications: {e}")

def enqueue_application(resume_id: str, job_id: str) -> str:
    """
    Enqueues a resume-job application into the queue with 'QUEUED' status.
    """
    queue_id = str(uuid.uuid4())
    now = datetime.datetime.utcnow().isoformat()
    
    def insert_queue(conn):
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO application_queue 
            (id, job_id, resume_id, status, attempt_count, attempts, created_at, updated_at)
            VALUES (?, ?, ?, 'QUEUED', 0, 0, ?, ?)
        """, (queue_id, job_id, resume_id, now, now))
        conn.commit()

        # Retrieve actual queue ID if record already existed
        cursor.execute("SELECT id FROM application_queue WHERE resume_id = ? AND job_id = ?", (resume_id, job_id))
        row = cursor.fetchone()
        actual_id = row[0] if row else queue_id
        return actual_id

    qid = execute_db_with_retry(insert_queue)
    log_audit_event(qid, to_status='QUEUED', from_status=None)
    return qid

def get_next_queued_application():
    """
    Retrieves the next application marked as QUEUED, RETRYING, or RETRY.
    Recovers stale workers first, then updates status to RUNNING atomically.
    """
    # 1. First recover any hung/stale workers
    recover_stale_applications()

    def select_and_lock(conn):
        cursor = conn.cursor()
        max_retries = Config.MAX_APPLICATION_RETRIES
        cursor.execute("""
            SELECT id, resume_id, job_id, status, COALESCE(attempt_count, attempts, 0)
            FROM application_queue
            WHERE status IN ('QUEUED', 'RETRYING', 'RETRY')
              AND COALESCE(attempt_count, attempts, 0) < ?
            ORDER BY created_at ASC LIMIT 1
        """, (max_retries,))
        row = cursor.fetchone()
        if not row:
            return None
            
        queue_id, resume_id, job_id, old_status, attempts = row
        now = datetime.datetime.utcnow().isoformat()
        session_id = str(uuid.uuid4())
        
        cursor.execute("""
            UPDATE application_queue
            SET status = 'RUNNING',
                started_at = ?,
                browser_session_id = ?,
                updated_at = ?
            WHERE id = ?
        """, (now, session_id, now, queue_id))
        conn.commit()
        
        return {
            "id": queue_id,
            "resume_id": resume_id,
            "job_id": job_id,
            "old_status": old_status,
            "attempts": attempts,
            "attempt_count": attempts,
            "browser_session_id": session_id,
            "started_at": now
        }

    task = execute_db_with_retry(select_and_lock)
    if task:
        log_audit_event(task["id"], to_status='RUNNING', from_status=task.get("old_status", "QUEUED"))
    return task

def update_status(
    queue_id: str,
    status: str,
    error_msg: str = None,
    attempts: int = None,
    browser_session_id: str = None,
    error_message: str = None,
    attempt_count: int = None,
    screenshot_path: str = None,
    submission_result: str = None
):
    """
    Updates the queue item status, attempts, error details, and completed_at timestamps,
    and logs an audit trail event.
    """
    now = datetime.datetime.utcnow().isoformat()
    err_text = error_message or error_msg
    attempt_val = attempt_count if attempt_count is not None else attempts

    def update_item(conn):
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM application_queue WHERE id = ?", (queue_id,))
        row = cursor.fetchone()
        old_status = row[0] if row else None

        completed_at = now if status in ('COMPLETED', 'FAILED') else None

        cursor.execute("""
            UPDATE application_queue
            SET status = ?,
                attempt_count = COALESCE(?, attempt_count),
                attempts = COALESCE(?, attempts),
                error_message = COALESCE(?, error_message),
                error_msg = COALESCE(?, error_msg),
                browser_session_id = COALESCE(?, browser_session_id),
                completed_at = COALESCE(?, completed_at),
                updated_at = ?
            WHERE id = ?
        """, (status, attempt_val, attempt_val, err_text, err_text, browser_session_id, completed_at, now, queue_id))
        conn.commit()

        return old_status

    old_status = execute_db_with_retry(update_item)
    log_audit_event(
        queue_id=queue_id,
        to_status=status,
        from_status=old_status,
        screenshot_path=screenshot_path,
        submission_result=submission_result,
        error_details=err_text
    )
