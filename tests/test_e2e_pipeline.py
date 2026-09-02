import unittest
import json
import sqlite3
import time
from unittest.mock import patch, MagicMock

from src.database.connection import initialize_database, get_connection
from src.parsers.resume import ResumeParser
from src.services.agent import AutonomousAgent
from src.workers.application_worker import ApplicationWorker

# Ensure database is initialized
initialize_database()

class TestE2EPipeline(unittest.TestCase):
    def setUp(self):
        # Clear tables
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM application_queue")
        cursor.execute("DELETE FROM matches")
        cursor.execute("DELETE FROM jobs")
        cursor.execute("DELETE FROM resumes")
        cursor.execute("DELETE FROM semantic_cache")
        cursor.execute("DELETE FROM llm_cache")
        conn.commit()
        conn.close()

    @patch("src.parsers.pdf.PDFParser.extract_text")
    @patch("src.services.groq.GroqService.parse_resume")
    @patch("src.services.groq.GroqService.parse_jd")
    @patch("src.services.job_search.JobSearchService.search_jobs")
    @patch("src.services.embedding.EmbeddingService.generate_embedding")
    @patch("src.services.embedding.EmbeddingService.generate_embeddings")
    @patch("src.services.application_decision_engine.ApplicationDecisionEngine.evaluate")
    def test_end_to_end_pipeline_workflow(self, mock_evaluate, mock_embeds, mock_embed, mock_search, mock_parse_jd, mock_parse_resume, mock_pdf_extract):
        """
        End-to-End Test: Resume Upload -> Parse -> Agent Match Run -> Auto-Enqueue -> Worker Process Task -> Complete.
        """
        from src.services.application_decision_engine import ApplicationDecision
        mock_evaluate.return_value = ApplicationDecision(
            decision="AUTO_APPLY",
            reason="Mocked high score for E2E workflow",
            confidence=0.95
        )
        # 1. Mock PDF Text Extraction
        mock_pdf_extract.return_value = "John Doe. python developer. Email: john@doe.com Github: github.com/johndoe"
        
        # 2. Mock Groq Resume Parsing Response
        mock_resume_parsed = {
            "contact_info": {"name": "John Doe", "email": "john@doe.com", "github": "https://github.com/johndoe"},
            "professional_summary": "Python Developer",
            "skills": {"languages": ["Python", "Go"]},
            "experience": [{"role": "Senior Engineer", "start_date": "2020-01", "end_date": "2023-01"}], # 3.0 years
            "education": [{"degree": "Bachelor of Science", "specialization": "Computer Science"}]
        }
        mock_parse_resume.return_value = mock_resume_parsed

        # 3. Mock Job Board Feed Discovery
        mock_search.return_value = [{
            "title": "Python Developer",
            "company": "Tech Corp",
            "url": "http://techcorp.com/apply/python-dev",
            "jd_raw": "We need a Python Developer with Go skills. 3 years of experience. Bachelor's degree required."
        }]

        # 4. Mock Groq JD Parsing Response
        mock_jd_parsed = {
            "title": "Python Developer",
            "required_skills": {
                "languages": ["Python"]
            },
            "preferred_skills": ["Go"],
            "responsibilities": ["Write code in Python"],
            "requirements": {
                "years_of_experience": "3 years",
                "education": "Bachelor's Degree",
                "other": []
            }
        }
        mock_parse_jd.return_value = mock_jd_parsed

        # 5. Mock Embeddings to return identical vectors (perfect matching score)
        mock_embed.return_value = [0.1] * 384
        mock_embeds.return_value = [[0.1] * 384]

        # === STEP A: UPLOAD & PARSE RESUME ===
        parser = ResumeParser()
        upload_result = parser.parse_and_save("my_resume.pdf", b"mock pdf bytes")
        resume_id = upload_result["id"]
        
        self.assertIsNotNone(resume_id)
        self.assertEqual(upload_result["filename"], "my_resume.pdf")
        
        # Verify saved in resumes table
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT filename, parsed_json FROM resumes WHERE id = ?", (resume_id,))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "my_resume.pdf")
        self.assertEqual(json.loads(row[1])["contact_info"]["email"], "john@doe.com")

        # === STEP B: RUN BACKGROUND MATCHING AGENT CYCLE ===
        agent = AutonomousAgent()
        agent.running = True
        agent._run_matching_cycle()

        # Verify job was parsed and saved
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, company FROM jobs WHERE url = ?", ("http://techcorp.com/apply/python-dev",))
        job_row = cursor.fetchone()
        self.assertIsNotNone(job_row)
        job_id = job_row[0]

        # Verify matching score evaluations
        cursor.execute("SELECT match_score FROM matches WHERE resume_id = ? AND job_id = ?", (resume_id, job_id))
        match_row = cursor.fetchone()
        self.assertIsNotNone(match_row)
        # Score should be high (>85%) because details match perfectly
        self.assertGreaterEqual(match_row[0] * 100.0, 85.0)

        # Verify it got auto-enqueued in the queue table
        cursor.execute("SELECT id, status, attempts FROM application_queue WHERE resume_id = ? AND job_id = ?", (resume_id, job_id))
        queue_row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(queue_row)
        queue_id = queue_row[0]
        self.assertIn(queue_row[1], ["QUEUED", "PROCESSING", "COMPLETED"])
        self.assertGreaterEqual(queue_row[2], 0)

        # === STEP C: WORKER PROCESSES THE TASK ===
        worker = ApplicationWorker(interval_seconds=0.1, simulate_failure_rate=0.0)
        worker.running = True
        
        # Read the queued item (which transitions it to PROCESSING atomically)
        task = {
            "id": queue_id,
            "resume_id": resume_id,
            "job_id": job_id,
            "attempts": 0
        }
        
        # Execute processing
        worker.process_task(task)

        # Verify final completed status
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT status, attempts FROM application_queue WHERE id = ?", (queue_id,))
        final_row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(final_row)
        self.assertEqual(final_row[0], "COMPLETED")
        self.assertEqual(final_row[1], 1)

if __name__ == "__main__":
    unittest.main()
