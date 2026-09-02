import unittest
import sqlite3
import urllib.error
import urllib.request
import io
import time
from unittest.mock import patch, MagicMock

from src.services.application_decision_engine import ApplicationDecisionEngine
from src.services.groq import GroqService, GroqRateLimiter
from src.database.connection import execute_db_with_retry

class TestMissingUnits(unittest.TestCase):
    
    # 1. ApplicationDecisionEngine Tests
    def test_decision_engine_auto_apply(self):
        dec = ApplicationDecisionEngine.evaluate(85.0, 0.90)
        self.assertEqual(dec.decision, "AUTO_APPLY")
        
        dec2 = ApplicationDecisionEngine.evaluate(90.0, 0.95)
        self.assertEqual(dec2.decision, "AUTO_APPLY")

    def test_decision_engine_review(self):
        # Score >= 75
        dec = ApplicationDecisionEngine.evaluate(75.0, 0.80)
        self.assertEqual(dec.decision, "REVIEW")
        
        dec2 = ApplicationDecisionEngine.evaluate(84.0, 0.95)
        self.assertEqual(dec2.decision, "REVIEW")
        
        dec3 = ApplicationDecisionEngine.evaluate(85.0, 0.89)
        self.assertEqual(dec3.decision, "REVIEW")

    def test_decision_engine_reject(self):
        # Score < 75
        dec = ApplicationDecisionEngine.evaluate(74.9, 0.95)
        self.assertEqual(dec.decision, "REJECT")
        
        dec2 = ApplicationDecisionEngine.evaluate(50.0, 0.50)
        self.assertEqual(dec2.decision, "REJECT")

    # 2. Groq Retries & Rate Limiter Tests
    @patch("urllib.request.urlopen")
    def test_groq_service_retry_on_429(self, mock_urlopen):
        # Set up mock response that fails first with 429, then succeeds
        mock_headers = MagicMock()
        mock_headers.get.return_value = "0.1" # Retry-After: 0.1 seconds
        
        err_response = urllib.error.HTTPError(
            url="https://api.groq.com/openai/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=mock_headers,
            fp=None
        )
        
        # Mock reading error body
        err_response.read = MagicMock(return_value=b'{"error": "Rate limit exceeded"}')
        
        # Success response
        success_response = MagicMock()
        success_response.read.return_value = b'{"choices": [{"message": {"content": "{\\"test\\": true}"}}]}'
        success_response.__enter__.return_value = success_response
        
        # Make the mock raise HTTPError first, then return success response
        mock_urlopen.side_effect = [err_response, success_response]
        
        payload = {"messages": []}
        headers = {"Authorization": "Bearer test"}
        
        with patch.object(GroqRateLimiter, "acquire") as mock_acquire:
            response_body = GroqService._make_api_call(payload, headers, max_retries=2)
            self.assertIn("choices", response_body)
            self.assertEqual(mock_urlopen.call_count, 2)
            self.assertEqual(mock_acquire.call_count, 2)

    # 3. Database Retry Logic Tests
    def test_execute_db_with_retry_locks(self):
        # Mock function simulating operational error database locked
        query_fn = MagicMock()
        query_fn.side_effect = [
            sqlite3.OperationalError("database is locked"),
            sqlite3.OperationalError("database is locked"),
            "Success"
        ]
        
        # Patch get_connection to return a mock connection
        mock_conn = MagicMock()
        with patch("src.database.connection.get_connection", return_value=mock_conn):
            result = execute_db_with_retry(query_fn, max_retries=3, initial_backoff=0.01)
            self.assertEqual(result, "Success")
            self.assertEqual(query_fn.call_count, 3)

if __name__ == "__main__":
    unittest.main()
