import os
import unittest

os.environ["ENABLE_IN_PROCESS_WORKERS"] = "false"
os.environ["ENVIRONMENT"] = "development"

from fastapi.testclient import TestClient
from src.server.app import app

class TestFastAPIServer(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "healthy"})

    def test_candidate_answers_flow(self):
        # Create
        res = self.client.post("/api/candidate-answers", json={
            "question_key": "test_auth_question",
            "question_pattern": "do you have experience with fastapi",
            "answer_value": "Yes, 4 years"
        })
        self.assertEqual(res.status_code, 200)
        ans_id = res.json().get("id")
        self.assertIsNotNone(ans_id)

        # Get
        res_get = self.client.get("/api/candidate-answers")
        self.assertEqual(res_get.status_code, 200)
        answers = res_get.json().get("answers", [])
        self.assertTrue(any(a["id"] == ans_id for a in answers))

        # Delete
        res_del = self.client.delete(f"/api/candidate-answers/{ans_id}")
        self.assertEqual(res_del.status_code, 200)

    def test_upload_invalid_pdf_header(self):
        # Upload plain text disguised as PDF
        response = self.client.post(
            "/api/parse-resume",
            files={"file": ("fake.pdf", b"This is not a pdf file", "application/pdf")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid file format", response.json().get("detail", ""))

    def test_upload_oversized_file(self):
        # Create an oversized payload > 10MB
        oversized_data = b"%PDF-" + b"0" * (11 * 1024 * 1024)
        response = self.client.post(
            "/api/parse-resume",
            files={"file": ("large.pdf", oversized_data, "application/pdf")}
        )
        self.assertEqual(response.status_code, 413)
        self.assertIn("File too large", response.json().get("detail", ""))

if __name__ == "__main__":
    unittest.main()
