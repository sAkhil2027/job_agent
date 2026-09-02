import unittest
import json
import sqlite3
from unittest.mock import patch, MagicMock

from src.database.connection import initialize_database, get_connection
from src.services.agent import AutonomousAgent
from src.services.scoring_pipeline import ScoringPipeline

# Ensure database is initialized
initialize_database()

class TestIntegrationAgentQueue(unittest.TestCase):
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
        
        # Insert a valid active resume
        self.resume_parsed = {
            "professional_summary": "Experienced Python Software Engineer",
            "skills": {"languages": ["Python", "Go"]},
            "experience": [{"role": "Senior Engineer", "start_date": "2020-01", "end_date": "2023-01"}],
            "education": [{"degree": "Bachelor of Science", "specialization": "Computer Science"}]
        }
        cursor.execute("""
            INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json)
            VALUES (?, ?, ?, ?)
        """, ("test-r", "r.pdf", "Python Go Developer", json.dumps(self.resume_parsed)))
        
        conn.commit()
        conn.close()

    @patch("src.services.groq.GroqService.parse_jd")
    @patch("src.services.job_search.JobSearchService.search_jobs")
    @patch("src.services.embedding.EmbeddingService.generate_embedding")
    @patch("src.services.embedding.EmbeddingService.generate_embeddings")
    @patch("src.services.application_decision_engine.ApplicationDecisionEngine.evaluate")
    def test_agent_discovery_to_enqueue_flow(self, mock_evaluate, mock_embeds, mock_embed, mock_search, mock_parse_jd):
        from src.services.application_decision_engine import ApplicationDecision
        
        mock_parse_jd.return_value = {
            "title": "Python Developer",
            "required_skills": {"languages": ["Python"]},
            "preferred_skills": ["Go"],
            "requirements": {"years_of_experience": "3 years", "education": "Bachelor's Degree"}
        }

        # 1. Setup mock search response (discover a job matching the resume)
        mock_search.return_value = [{
            "title": "Python Developer",
            "company": "Test Corp",
            "url": "http://test-corp.com/python-job",
            "jd_raw": "Looking for Python Developer with Go skills."
        }]
        
        # 2. Setup mock embedding values (return identical lists so similarity = 1.0)
        mock_embed.return_value = [0.1] * 384
        mock_embeds.return_value = [[0.1] * 384]

        # 3. Setup mock decision engine to return AUTO_APPLY
        mock_evaluate.return_value = ApplicationDecision(
            decision="AUTO_APPLY",
            reason="Mocked high score",
            confidence=0.95
        )

        # 4. Instantiation of agent and running matching cycle synchronously
        agent = AutonomousAgent()
        agent.running = True
        
        agent._run_matching_cycle()

        # 5. Verify the job was discovered, parsed, and saved
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, company FROM jobs WHERE url = ?", ("http://test-corp.com/python-job",))
        job_row = cursor.fetchone()
        self.assertIsNotNone(job_row)
        job_id = job_row[0]

        # 6. Verify that it resulted in a match record in DB
        cursor.execute("SELECT match_score FROM matches WHERE resume_id = ? AND job_id = ?", ("test-r", job_id))
        match_row = cursor.fetchone()
        self.assertIsNotNone(match_row)

        # 7. Verify the decision auto-enqueued the job into application_queue
        cursor.execute("SELECT status, attempts FROM application_queue WHERE resume_id = ? AND job_id = ?", ("test-r", job_id))
        queue_row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(queue_row)
        self.assertIn(queue_row[0], ["QUEUED", "PROCESSING", "COMPLETED"])
        self.assertGreaterEqual(queue_row[1], 0)

    @patch("src.services.scoring_pipeline.should_route_to_llm")
    @patch("src.services.groq.GroqService.completion")
    @patch("src.services.embedding.EmbeddingService.generate_embedding")
    @patch("src.services.embedding.EmbeddingService.generate_embeddings")
    def test_llm_failure_matching_fallback(self, mock_embeds, mock_embed, mock_completion, mock_should_route):
        # 1. Setup mock embeddings
        mock_embed.return_value = [0.1] * 384
        mock_embeds.return_value = [[0.1] * 384]
        
        # Force routing to LLM
        mock_should_route.return_value = True

        # 2. Mock GroqService to fail (Timeout / API issues)
        mock_completion.side_effect = MagicMock(side_effect=Exception("Groq Service Timeout Exception"))

        # 3. Setup parsed JD
        jd_parsed = {
            "title": "Python Developer",
            "required_skills": {
                "languages": ["Python"]
            },
            "requirements": {
                "years_of_experience": "5 years",
                "education": "Bachelor's Degree"
            }
        }

        # 4. Trigger match execution using use_llm=True (which normally routes to Groq)
        options = {
            "resume_id": "test-r",
            "job_id": "test-j-fail",
            "use_llm": True
        }
        
        # Save a dummy job record to avoid constraint failures
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("test-j-fail", "Python Developer", "Test Corp", "http://test-corp.com/jd-fail", "Python Go Developer", json.dumps(jd_parsed)))
        conn.commit()
        conn.close()

        try:
            res = ScoringPipeline.match(self.resume_parsed, jd_parsed, options)
            self.assertTrue(res.match_score > 0.0)
            self.assertEqual(res.processing_mode, "deterministic_fallback")
            self.assertTrue(res.is_llm_used)
        except Exception as e:
            self.fail(f"ScoringPipeline failed to fall back on LLM timeout/failure: {e}")

if __name__ == "__main__":
    unittest.main()
