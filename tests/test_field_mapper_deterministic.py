import sys
import unittest
sys.path.insert(0, '.')

from src.services.candidate_profile import CandidateProfile
from src.services.field_mapper import FieldMapper
from src.database.connection import execute_db_with_retry, get_connection

class TestFieldMapperDeterministic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create candidate_answers table if not exists
        def init_db(conn):
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidate_answers (
                id TEXT PRIMARY KEY,
                question_key TEXT UNIQUE NOT NULL,
                question_pattern TEXT NOT NULL,
                answer_value TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cursor.execute("INSERT OR REPLACE INTO candidate_answers (id, question_key, question_pattern, answer_value) VALUES ('1', 'relocation', 'relocat', 'Yes, open to relocation')")
            conn.commit()

        execute_db_with_retry(init_db)

    def test_candidate_profile_payload(self):
        profile = CandidateProfile(
            full_name="Jane Doe",
            first_name="Jane",
            last_name="Doe",
            email="jane@example.com",
            phone="123-456-7890",
            location="San Francisco, CA",
            linkedin="https://linkedin.com/in/janedoe",
            github="https://github.com/janedoe",
            resume_path="data/resumes/jane_resume.pdf",
            projects=[{"name": "AI Job Matcher", "description": "Automated pipeline"}]
        )

        payload = FieldMapper.get_candidate_form_payload(profile)
        self.assertEqual(payload["full_name"], "Jane Doe")
        self.assertEqual(payload["email"], "jane@example.com")
        self.assertIn("AI Job Matcher", payload["summary"])
        self.assertEqual(payload["work_authorization"], "Authorized to work in the US without sponsorship")

    def test_match_input_to_field(self):
        m1 = FieldMapper.match_input_to_field({"name": "first_name", "type": "text", "label": "First Name"})
        self.assertEqual(m1, "first_name")

        m2 = FieldMapper.match_input_to_field({"name": "applicant_email", "type": "email", "label": "Email Address"})
        self.assertEqual(m2, "email")

        m3 = FieldMapper.match_input_to_field({"name": "salary_expectation", "type": "text", "label": "Desired Salary"})
        self.assertEqual(m3, "desired_salary")

    def test_database_answer_lookup(self):
        db_answer = FieldMapper.get_database_answer("Are you open to relocation?")
        self.assertEqual(db_answer, "Yes, open to relocation")

        unmatched = FieldMapper.get_database_answer("What is your favorite color?")
        self.assertIsNone(unmatched)

if __name__ == "__main__":
    unittest.main()
