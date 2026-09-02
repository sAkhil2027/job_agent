import unittest
import socket
import threading
import json
import time
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from src.database.connection import initialize_database, get_connection
from src.server.router import Router
from src.services.scoring_pipeline import ScoringPipeline
from src.services.agent import AutonomousAgent

# Ensure database is initialized
initialize_database()

def find_free_port():
    s = socket.socket()
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Find a free port and start the server
        cls.port = find_free_port()
        cls.server_address = ('127.0.0.1', cls.port)
        cls.httpd = ThreadingHTTPServer(cls.server_address, Router)
        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()
        # Wait a bit for server to start
        time.sleep(0.5)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        # Start patchers to prevent external HTTP requests
        self.search_patcher = patch("src.services.job_search.JobSearchService.search_jobs")
        self.mock_search = self.search_patcher.start()
        self.mock_search.return_value = [{
            "title": "Python Developer",
            "company": "Test Corp",
            "url": "http://test-corp.com/jd",
            "jd_raw": "Python Developer Go"
        }]

        self.embed_patcher = patch("src.services.embedding.EmbeddingService.generate_embedding")
        self.mock_embed = self.embed_patcher.start()
        self.mock_embed.return_value = [0.1] * 384
        
        self.embeds_patcher = patch("src.services.embedding.EmbeddingService.generate_embeddings")
        self.mock_embeds = self.embeds_patcher.start()
        self.mock_embeds.return_value = [[0.1] * 384]

        self.groq_jd_patcher = patch("src.services.groq.GroqService.parse_jd")
        self.mock_groq_jd = self.groq_jd_patcher.start()
        self.mock_groq_jd.return_value = {
            "title": "Python Developer",
            "required_skills": {"languages": ["Python"]},
            "preferred_skills": ["Go"],
            "requirements": {"years_of_experience": "3 years", "education": "Bachelor's Degree"}
        }

        self.groq_completion_patcher = patch("src.services.groq.GroqService.completion")
        self.mock_groq_completion = self.groq_completion_patcher.start()
        self.mock_groq_completion.return_value = json.dumps({
            "transferable_skill_fit": "Strong match in Python and Go.",
            "career_growth_alignment": "Good trajectory.",
            "overall_suitability_summary": "Highly recommended candidate.",
            "score_adjustment": 2.0
        })

        # Reset DB tables
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM matches")
        cursor.execute("DELETE FROM jobs")
        cursor.execute("DELETE FROM resumes")
        cursor.execute("DELETE FROM ai_explanations")
        
        # Insert a dummy resume
        self.resume_parsed = {
            "professional_summary": "Experienced Software Engineer",
            "skills": {"languages": ["Python", "Go"]},
            "experience": [{"role": "Senior Engineer", "start_date": "2020-01", "end_date": "2023-01"}],
            "education": [{"degree": "Bachelor of Science", "specialization": "Computer Science"}]
        }
        cursor.execute("""
            INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json)
            VALUES (?, ?, ?, ?)
        """, ("test-resume-id", "resume.pdf", "Python Go Developer", json.dumps(self.resume_parsed)))
        
        # Insert a dummy job description
        self.jd_parsed = {
            "title": "Python Developer",
            "required_skills": {"languages": ["Python"]},
            "preferred_skills": ["Go"],
            "requirements": {"years_of_experience": "3 years", "education": "Bachelor's Degree"}
        }
        cursor.execute("""
            INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("test-job-id", "Python Developer", "Test Corp", "http://test-corp.com/jd", "Python Developer Go", json.dumps(self.jd_parsed)))
        
        conn.commit()
        conn.close()

    def tearDown(self):
        self.search_patcher.stop()
        self.embed_patcher.stop()
        self.embeds_patcher.stop()
        self.groq_jd_patcher.stop()
        self.groq_completion_patcher.stop()

    def test_http_matching_flow(self):
        # 1. Test POST /api/match-jobs path
        url = f"http://127.0.0.1:{self.port}/api/match-jobs"
        req_body = json.dumps({"resume_id": "test-resume-id"}).encode("utf-8")
        req = urllib.request.Request(url, data=req_body, headers={"Content-Type": "application/json"}, method="POST")
        
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res_data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("resume_id", res_data)
            self.assertIn("matches", res_data)
            matches = res_data["matches"]
            self.assertGreater(len(matches), 0)
            
            # Check standard result schema is present
            match = matches[0]
            self.assertIn("final_score", match)
            self.assertIn("base_score", match)
            self.assertIn("exact_matches", match)
            self.assertIn("missing_required_skills", match)
            self.assertIn("cache", match)

    def test_background_agent_flow(self):
        # 2. Test Background Agent Matching Cycle
        agent = AutonomousAgent()
        
        # Trigger the agent match run cycle
        agent._run_matching_cycle()
        
        # Verify match table contains the record
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT match_score, reasoning FROM matches WHERE resume_id = ? AND job_id = ?", ("test-resume-id", "test-job-id"))
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertGreater(row[0], 0.0)

    def test_equivalence_deterministic(self):
        # Verify that foreground (http) and background (agent) calls evaluate to identical scores
        options = {
            "resume_id": "test-resume-id",
            "job_id": "test-job-id",
            "use_llm": False
        }
        res_http = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        res_agent = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        
        self.assertEqual(res_http.match_score, res_agent.match_score)
        self.assertEqual(res_http.base_score, res_agent.base_score)
        self.assertEqual(res_http.confidence, res_agent.confidence)

if __name__ == "__main__":
    unittest.main()
