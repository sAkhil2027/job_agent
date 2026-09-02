import unittest
import time
from unittest.mock import patch
from src.database.connection import initialize_database, get_connection
from src.services.application_queue import (
    enqueue_application,
    get_next_queued_application,
    update_status
)
from src.workers.application_worker import ApplicationWorker
from src.services.scoring_pipeline import ScoringPipeline

# Ensure schema is initialized
initialize_database()

class TestApplicationQueue(unittest.TestCase):
    def setUp(self):
        # Reset DB tables
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM application_queue")
        cursor.execute("DELETE FROM matches")
        cursor.execute("DELETE FROM jobs")
        cursor.execute("DELETE FROM resumes")
        
        # Insert a dummy resume
        cursor.execute("""
            INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json)
            VALUES (?, ?, ?, ?)
        """, ("test-r", "r.pdf", "Python Dev", "{}"))
        
        # Insert a dummy job
        cursor.execute("""
            INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("test-j", "Title", "Company", "http://url", "JD Text", "{}"))
        
        conn.commit()
        conn.close()

    def test_enqueue_and_atomic_retrieval(self):
        # 1. Enqueue
        qid = enqueue_application("test-r", "test-j")
        self.assertIsNotNone(qid)
        
        # Check DB status is QUEUED
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, attempts FROM application_queue WHERE id = ?", (qid,))
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row[0], "QUEUED")
        self.assertEqual(row[1], 0)
        
        # 2. Retrieve (atomically sets status to PROCESSING)
        task = get_next_queued_application()
        self.assertIsNotNone(task)
        self.assertEqual(task["id"], qid)
        self.assertEqual(task["attempts"], 0)
        
        # Check status is now RUNNING or PROCESSING
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM application_queue WHERE id = ?", (qid,))
        row = cursor.fetchone()
        conn.close()
        self.assertIn(row[0], ["RUNNING", "PROCESSING"])


    def test_worker_processing_success(self):
        # Enqueue task
        qid = enqueue_application("test-r", "test-j")
        
        # Start worker thread
        worker = ApplicationWorker(interval_seconds=0.1, simulate_failure_rate=0.0)
        worker.running = True
        
        # Process one task manually to avoid background timing races
        task = get_next_queued_application()
        self.assertIsNotNone(task)
        worker.process_task(task)
        
        # Check status is now COMPLETED
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, attempts FROM application_queue WHERE id = ?", (qid,))
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row[0], "COMPLETED")
        self.assertEqual(row[1], 1)

    def test_worker_retry_to_failure(self):
        # Enqueue task
        qid = enqueue_application("test-r", "test-j")
        
        # Start worker with 100% failure rate
        worker = ApplicationWorker(interval_seconds=0.1, simulate_failure_rate=1.0)
        
        # Process task first time -> should transition to RETRY (attempts=1)
        task1 = get_next_queued_application()
        self.assertIsNotNone(task1)
        worker.process_task(task1)
        
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, attempts FROM application_queue WHERE id = ?", (qid,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "RETRY")
        self.assertEqual(row[1], 1)
        
        # Process task second time -> should transition to RETRY (attempts=2)
        task2 = get_next_queued_application()
        self.assertIsNotNone(task2)
        worker.process_task(task2)
        cursor.execute("SELECT status, attempts FROM application_queue WHERE id = ?", (qid,))
        row = cursor.fetchone()
        self.assertEqual(row[0], "RETRY")
        self.assertEqual(row[1], 2)
        
        # Process task third time -> should transition to FAILED (attempts=3)
        task3 = get_next_queued_application()
        self.assertIsNotNone(task3)
        worker.process_task(task3)
        cursor.execute("SELECT status, attempts FROM application_queue WHERE id = ?", (qid,))
        row = cursor.fetchone()
        conn.close()
        self.assertEqual(row[0], "FAILED")
        self.assertEqual(row[1], 3)

    @patch("src.services.application_decision_engine.ApplicationDecisionEngine.evaluate")
    def test_auto_enqueue_on_matching(self, mock_evaluate):
        from src.services.application_decision_engine import ApplicationDecision
        mock_evaluate.return_value = ApplicationDecision(
            decision="AUTO_APPLY",
            reason="Mocked high score for testing auto-enqueue",
            confidence=0.95
        )
        
        resume_parsed = {
            "professional_summary": "Experienced Engineer",
            "skills": {"languages": ["Python", "Go"]},
            "experience": [{"role": "Senior Engineer", "start_date": "2020-01", "end_date": "2023-01"}],
            "education": [{"degree": "Bachelor of Science", "specialization": "Computer Science"}]
        }
        jd_parsed = {
            "title": "Python Developer",
            "required_skills": {"languages": ["Python"]},
            "preferred_skills": ["Go"],
            "requirements": {"years_of_experience": "3 years", "education": "Bachelor's Degree"}
        }
        
        options = {
            "resume_id": "test-r",
            "job_id": "test-j",
            "use_llm": False
        }
        
        # Score is 92, confidence is high, should trigger AUTO_APPLY and auto-enqueue
        res = ScoringPipeline.match(resume_parsed, jd_parsed, options)
        self.assertEqual(res.application_decision["decision"], "AUTO_APPLY")
        
        # Verify it exists in the application_queue table
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM application_queue WHERE resume_id = ? AND job_id = ?", ("test-r", "test-j"))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertIn(row[0], ["QUEUED", "PROCESSING", "COMPLETED"])


if __name__ == "__main__":
    unittest.main()
