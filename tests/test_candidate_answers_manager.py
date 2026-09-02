import sys
import json
import unittest
sys.path.insert(0, '.')

from src.database.connection import (
    initialize_database,
    add_candidate_answer,
    get_all_candidate_answers,
    delete_candidate_answer
)
from src.services.field_mapper import FieldMapper

class TestCandidateAnswersManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()

    def test_candidate_answers_crud(self):
        # 1. Add custom project explanation answer rule
        q_key = "project_summary_test"
        q_pattern = "project|explain your project|tell me about your project"
        a_val = "I engineered an automated resume-job matching system using Python, Playwright, and SQLite."

        ans_id = add_candidate_answer(q_key, q_pattern, a_val)
        self.assertIsNotNone(ans_id)

        # 2. Get all rules
        all_ans = get_all_candidate_answers()
        self.assertTrue(any(a["question_key"] == q_key for a in all_ans))

        # 3. Test FieldMapper lookup
        matched_val = FieldMapper.get_database_answer("Please explain your project in detail")
        self.assertEqual(matched_val, a_val)

        # 4. Delete rule
        del_res = delete_candidate_answer(ans_id)
        self.assertTrue(del_res)

        # Verify deleted
        matched_after = FieldMapper.get_database_answer("Please explain your project in detail")
        self.assertNotEqual(matched_after, a_val)

if __name__ == "__main__":
    unittest.main()
