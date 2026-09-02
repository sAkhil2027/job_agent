import sqlite3
import json
import unittest
from src.services.cache import PARSER_VERSION, MATCH_VERSION, calculate_sha256
from src.database.connection import get_connection, initialize_database

class TestCacheInvalidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        initialize_database()

    def test_hashing_consistency(self):
        text = "Sample Job Description with Python, AWS, Docker."
        hash1 = calculate_sha256(text)
        hash2 = calculate_sha256(text)
        self.assertEqual(hash1, hash2)
        
        text_modified = "Sample Job Description with Python, AWS, Docker. Updated."
        hash_modified = calculate_sha256(text_modified)
        self.assertNotEqual(hash1, hash_modified)

    def test_db_schema_columns(self):
        conn = get_connection()
        cursor = conn.cursor()
        
        # Verify columns exist in jobs
        cursor.execute("PRAGMA table_info(jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        self.assertIn("jd_hash", columns)
        self.assertIn("parser_version", columns)
        
        # Verify columns exist in matches
        cursor.execute("PRAGMA table_info(matches)")
        columns = [row[1] for row in cursor.fetchall()]
        self.assertIn("match_version", columns)
        self.assertIn("resume_hash", columns)
        
        conn.close()

if __name__ == "__main__":
    unittest.main()
