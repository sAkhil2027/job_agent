import unittest
import time
import json
from unittest.mock import patch, MagicMock

from src.services.groq import compress_resume_for_llm, compress_jd_for_llm, _groq_semaphore
from src.services.job_search import JobSearchService, _search_cache

class TestFreeTierOptimizations(unittest.TestCase):
    def test_compress_resume_token_reduction(self):
        # Create a large resume payload
        large_resume = {
            "professional_summary": "A" * 1000,
            "skills": {
                "languages": [f"Lang_{i}" for i in range(50)],
                "frameworks": [f"Frame_{i}" for i in range(50)],
                "empty_cat": []
            },
            "experience": [
                {
                    "role": f"Role_{i}",
                    "company": f"Comp_{i}",
                    "start_date": "2020",
                    "end_date": "2022",
                    "responsibilities": [f"Resp_{j}_" + "X" * 200 for j in range(10)]
                }
                for i in range(10)
            ],
            "extra_boilerplate": {"some_metadata": "data" * 100}
        }

        compressed = compress_resume_for_llm(large_resume)
        
        orig_len = len(json.dumps(large_resume))
        comp_len = len(json.dumps(compressed))

        # Must achieve at least 50% token/size reduction
        self.assertLess(comp_len, orig_len * 0.5)
        self.assertNotIn("extra_boilerplate", compressed)
        self.assertLessEqual(len(compressed["skills"]["languages"]), 15)

    def test_compress_jd_token_reduction(self):
        large_jd = {
            "title": "Senior Python Engineer",
            "required_skills": {
                "languages": [f"Skill_{i}" for i in range(40)],
                "empty": []
            },
            "preferred_skills": [f"Pref_{i}" for i in range(30)],
            "responsibilities": [f"Resp_{i}_" + "Y" * 300 for i in range(15)],
            "requirements": {
                "years_of_experience": "5+",
                "education": "BS in CS"
            },
            "disclaimer_text": "Equal Opportunity Employer " * 50
        }

        compressed = compress_jd_for_llm(large_jd)

        orig_len = len(json.dumps(large_jd))
        comp_len = len(json.dumps(compressed))

        self.assertLess(comp_len, orig_len * 0.5)
        self.assertNotIn("disclaimer_text", compressed)
        self.assertLessEqual(len(compressed["required_skills"]["languages"]), 12)

    def test_groq_semaphore_serialization(self):
        # Ensure semaphore exists with initial value 1
        self.assertIsNotNone(_groq_semaphore)
        acquired = _groq_semaphore.acquire(blocking=False)
        self.assertTrue(acquired)
        # Second acquire should fail without waiting
        second_acquire = _groq_semaphore.acquire(blocking=False)
        self.assertFalse(second_acquire)
        _groq_semaphore.release()

    @patch("src.services.job_search.requests.get")
    def test_job_search_1_hour_cache(self, mock_requests_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "jobs": [
                {"title": "Backend Dev", "company_name": "Acme", "url": "http://acme.com", "description": "Python job"}
            ]
        }
        mock_requests_get.return_value = mock_resp

        # Clear cache for isolated test
        _search_cache.clear()

        # First call hits network
        jobs1 = JobSearchService.search_jobs(["Python"], limit=2)
        self.assertGreaterEqual(len(jobs1), 1)
        call_count_first = mock_requests_get.call_count

        # Second call within 1 hour should serve directly from cache
        jobs2 = JobSearchService.search_jobs(["Python"], limit=2)
        self.assertEqual(len(jobs2), len(jobs1))
        # mock_requests_get should NOT have been called again
        self.assertEqual(mock_requests_get.call_count, call_count_first)

if __name__ == "__main__":
    unittest.main()
