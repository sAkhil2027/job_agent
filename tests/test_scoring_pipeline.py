import unittest
import json
from unittest.mock import patch
from src.database.connection import initialize_database
from src.services.scoring_pipeline import (
    ScoringPipeline,
    calculate_experience_match,
    parse_required_experience,
    evaluate_education_match
)

# Run migrations at test startup
initialize_database()

class TestScoringPipeline(unittest.TestCase):
    def setUp(self):
        self.resume_parsed = {
            "professional_summary": "Experienced Python Software Engineer.",
            "skills": {
                "languages": ["Python", "C++"],
                "frameworks": ["Django"],
                "databases": ["PostgreSQL"],
                "cloud": ["AWS"],
                "tools": ["Git"]
            },
            "experience": [
                {"role": "Developer", "start_date": "2020-01", "end_date": "2023-01"}, # 3 years
                {"role": "Senior Developer", "start_date": "2023-01", "end_date": "present"} # ~3.5 years (up to 2026-07)
            ],
            "education": [
                {"degree": "Bachelor of Science", "specialization": "Computer Science"}
            ]
        }
        
        self.jd_parsed = {
            "title": "Backend Python Developer",
            "required_skills": {
                "languages": ["Python"],
                "frameworks": ["Django"],
                "databases": ["PostgreSQL"]
            },
            "requirements": {
                "years_of_experience": "5+ years",
                "education": "Bachelor's Degree"
            }
        }

    def test_calculate_experience_match(self):
        match_info = calculate_experience_match(self.resume_parsed, self.jd_parsed)
        # 2020-01 to 2023-01 = 36 months
        # 2023-01 to 2026-07 = 42 months
        # Total = 78 months = 6.5 years
        self.assertGreaterEqual(match_info["estimated_relevant_years"], 6.0)
        self.assertEqual(match_info["score"], 1.0)

    def test_parse_required_experience(self):
        req_exp = parse_required_experience(self.jd_parsed)
        self.assertEqual(req_exp, 5.0)
        
        jd_range = {"requirements": {"years_of_experience": "3-5 years"}}
        self.assertEqual(parse_required_experience(jd_range), 3.0)

    def test_evaluate_education_match(self):
        edu_match = evaluate_education_match(self.resume_parsed, self.jd_parsed)
        self.assertEqual(edu_match, 1.0) # Candidate has BS, JD requires BS

    def test_local_scoring_no_llm(self):
        res = ScoringPipeline.match(
            resume=self.resume_parsed,
            jd=self.jd_parsed,
            options={"use_llm": False}
        )
        self.assertTrue(hasattr(res, "match_score"))
        self.assertTrue(hasattr(res, "base_score"))
        self.assertEqual(res.llm_adjustment, 0.0)

    def test_normalization_service(self):
        from src.services.normalization import NormalizationService
        norm = NormalizationService.normalize(self.resume_parsed)
        self.assertIn("python", norm["skills"])
        self.assertIn("bachelor", norm["education"])
        self.assertIn("swe", norm["job_titles"])

    def test_score_breakdown(self):
        res = ScoringPipeline.match(
            resume=self.resume_parsed,
            jd=self.jd_parsed,
            options={"use_llm": False}
        )
        self.assertIn("required_skills", res.score_breakdown)
        self.assertIn("preferred_skills", res.score_breakdown)
        self.assertIn("experience", res.score_breakdown)
        self.assertIn("responsibilities", res.score_breakdown)
        self.assertIn("role_title", res.score_breakdown)
        self.assertIn("education_certifications", res.score_breakdown)
        self.assertIn("domain_relevance", res.score_breakdown)

    def test_confidence_score(self):
        res = ScoringPipeline.match(
            resume=self.resume_parsed,
            jd=self.jd_parsed,
            options={"use_llm": False}
        )
        self.assertTrue(hasattr(res, "confidence"))
        self.assertTrue(0.0 <= res.confidence <= 1.0)

    def test_two_level_cache(self):
        from unittest.mock import patch
        
        try:
            from src.database.connection import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM matches")
            cursor.execute("DELETE FROM llm_cache")
            cursor.execute("INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json) VALUES (?, ?, ?, ?)",
                           ("test-resume-123", "test.pdf", "", "{}"))
            cursor.execute("INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed) VALUES (?, ?, ?, ?, ?, ?)",
                           ("test-job-456", "Test Title", "Test Company", "http://test.url", "", "{}"))
            conn.commit()
            conn.close()
        except Exception:
            pass

        options = {
            "resume_id": "test-resume-123",
            "job_id": "test-job-456",
            "use_llm": False
        }

        res1 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        self.assertTrue(res1.base_score > 0.0)

        with patch("src.services.capability_matcher.CapabilityMatchingEngine.match_capabilities") as mock_match:
            mock_match.return_value = {
                "matched_capabilities": [],
                "missing_skills": []
            }
            res2 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            mock_match.assert_not_called()
            self.assertEqual(res2.base_score, res1.base_score)

    def test_llm_routing(self):
        from src.services.scoring_pipeline import should_route_to_llm
        
        # Scenario A: High confidence (0.95), no borderline, no transferable
        matched_caps = [{"requirement": "Python", "match_type": "exact", "score": 1.0}]
        should_route = should_route_to_llm(
            base_score_pct=85.0,
            confidence_val=0.95,
            matched_caps=matched_caps,
            missing_skills=[],
            cand_exp=5.0,
            req_exp=3.0,
            exp_confidence=1.0
        )
        self.assertFalse(should_route) # SKIP LLM

        # Scenario B: Borderline semantic match exists
        matched_caps_borderline = [
            {"requirement": "FastAPI", "match_type": "semantic", "is_borderline": True, "score": 0.60}
        ]
        should_route_borderline = should_route_to_llm(
            base_score_pct=80.0,
            confidence_val=0.75,
            matched_caps=matched_caps_borderline,
            missing_skills=[],
            cand_exp=5.0,
            req_exp=3.0,
            exp_confidence=1.0
        )
        self.assertTrue(should_route_borderline) # ROUTE TO LLM

    @patch("src.services.groq.GroqService.completion")
    def test_llm_contextual_analyzer(self, mock_completion):
        try:
            from src.database.connection import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM matches")
            cursor.execute("DELETE FROM llm_cache")
            cursor.execute("INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json) VALUES (?, ?, ?, ?)",
                           ("test-resume-123", "test.pdf", "", "{}"))
            cursor.execute("INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed) VALUES (?, ?, ?, ?, ?, ?)",
                           ("test-job-456", "Test Title", "Test Company", "http://test.url", "", "{}"))
            conn.commit()
            conn.close()
        except Exception:
            pass

        # LLM returns valid structured signals conforming to the new schema
        mock_response = {
            "context_fit": 0.80,
            "transferable_skill_fit": 0.75,
            "responsibility_fit": 0.85,
            "experience_quality": 0.70,
            "confidence": 0.90,
            "reasoning": "Strong match with minor gaps"
        }
        mock_completion.return_value = json.dumps(mock_response)

        options = {
            "resume_id": "test-resume-123",
            "job_id": "test-job-456",
            "use_llm": True
        }
        
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            self.assertTrue(res.is_llm_used)
            # cf_delta = (0.80 - 0.70) * 2.0 = 0.2
            # tf_delta = (0.75 - 0.70) * 1.0 = 0.05
            # rf_delta = (0.85 - 0.70) * 1.0 = 0.15
            # eq_delta = (0.70 - 0.70) * 1.0 = 0.0
            # total delta = 0.40
            # raw = 0.40 * 0.90 * 2.5 = 0.90
            self.assertEqual(res.llm_adjustment, 0.9)

    @patch("src.services.groq.GroqService.completion")
    def test_llm_failure_graceful_handling(self, mock_completion):
        # Mock completion to raise an exception (simulating rate limit or timeout)
        mock_completion.side_effect = Exception("API rate limit exceeded")

        options = {
            "use_llm": True
        }
        
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            self.assertTrue(res.is_llm_used)
            self.assertEqual(res.processing_mode, "deterministic_fallback")
            self.assertEqual(res.llm_adjustment, 0.0)
            self.assertEqual(res.match_score, round(res.base_score / 100.0, 4))

    def test_generate_deterministic_explanation(self):
        from src.services.scoring_pipeline import generate_deterministic_explanation
        score_breakdown = {
            "required_skills": 80.0,
            "preferred_skills": 70.0,
            "experience": 90.0,
            "responsibilities": 85.0,
            "role_title": 95.0,
            "education_certifications": 100.0,
            "domain_relevance": 60.0
        }
        matched_caps = [
            {"requirement": "Python", "match_type": "exact", "score": 1.0},
            {"requirement": "FastAPI", "match_type": "semantic", "resume_evidence": "Built FastAPI APIs", "similarity": 0.85, "score": 0.85}
        ]
        
        explanation = generate_deterministic_explanation(
            final_score=83.0,
            base_score_pct=80.0,
            adjustment=3.0,
            processing_mode="hybrid",
            confidence_val=0.88,
            matched_caps=matched_caps,
            missing_skills=["Kubernetes"],
            req_names_lower={"python", "kubernetes"},
            cand_exp=2.5,
            req_exp=3.0,
            responsibility_score=0.85,
            title_score=0.95,
            education_score=1.0,
            domain_relevance_score=0.60,
            score_breakdown=score_breakdown
        )
        
        self.assertIn("Match Score: 83%", explanation)
        self.assertIn("Base Score: 80%", explanation)
        self.assertIn("LLM Adjustment: +3.0", explanation)
        self.assertIn("Processing Mode: hybrid", explanation)
        self.assertIn("Confidence: 88%", explanation)
        self.assertIn("- Python", explanation)
        self.assertIn("- \"Built FastAPI APIs\" -> \"FastAPI\" (Similarity: 0.85)", explanation)
        self.assertIn("Missing Required Skills:\n- Kubernetes", explanation)
        self.assertIn("Experience:\n- Required: 3.0 years\n- Estimated Relevant Experience: 2.5 years\n- Experience Gap: 0.5 years", explanation)

    @patch("src.services.groq.GroqService.completion")
    def test_detailed_explanation_service(self, mock_completion):
        from src.services.explanation_service import DetailedExplanationService
        try:
            from src.database.connection import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM resumes")
            cursor.execute("DELETE FROM jobs")
            cursor.execute("DELETE FROM matches")
            cursor.execute("DELETE FROM ai_explanations")
            cursor.execute("INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json) VALUES (?, ?, ?, ?)",
                           ("test-resume-123", "test.pdf", "", "{}"))
            cursor.execute("INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed) VALUES (?, ?, ?, ?, ?, ?)",
                           ("test-job-456", "Test Title", "Test Company", "http://test.url", "", "{}"))
            conn.commit()
            conn.close()
        except Exception:
            pass

        mock_completion.return_value = "Detailed AI Match Report"

        exp1 = DetailedExplanationService.get_detailed_explanation("test-resume-123", "test-job-456")
        self.assertEqual(exp1, "Detailed AI Match Report")
        mock_completion.assert_called_once()

        mock_completion.reset_mock()

        exp2 = DetailedExplanationService.get_detailed_explanation("test-resume-123", "test-job-456")
        self.assertEqual(exp2, "Detailed AI Match Report")
        mock_completion.assert_not_called()

    def test_standard_match_result_schema(self):
        options = {
            "use_llm": False
        }
        res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        data = res.to_dict()
        
        self.assertIn("base_score", data)
        self.assertIn("final_score", data)
        self.assertIn("confidence", data)
        self.assertIn("llm_adjustment", data)
        self.assertIn("processing_mode", data)
        self.assertIn("score_breakdown", data)
        self.assertIn("exact_matches", data)
        self.assertIn("taxonomy_matches", data)
        self.assertIn("transferable_matches", data)
        self.assertIn("semantic_matches", data)
        self.assertIn("missing_required_skills", data)
        self.assertIn("missing_preferred_skills", data)
        self.assertIn("experience_analysis", data)
        self.assertIn("explanation", data)
        self.assertIn("cache", data)
        
        self.assertEqual(data["processing_mode"], "deterministic")
        self.assertIn("local_hit", data["cache"])
        self.assertIn("llm_hit", data["cache"])

    def test_metrics_tracker(self):
        from src.services.metrics import MetricsTracker
        
        # Reset counters first
        MetricsTracker.total_matches = 0
        MetricsTracker.llm_calls = 0
        MetricsTracker.llm_calls_skipped = 0
        MetricsTracker.local_cache_hits = 0
        MetricsTracker.llm_cache_hits = 0
        MetricsTracker.total_local_match_time = 0.0
        MetricsTracker.total_embedding_time = 0.0
        MetricsTracker.total_llm_time = 0.0
        MetricsTracker.confidence_sum = 0.0
        MetricsTracker.processing_modes = {"deterministic": 0, "hybrid": 0, "deterministic_fallback": 0}

        options = {
            "use_llm": False
        }
        ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        
        metrics = MetricsTracker.get_metrics()
        self.assertEqual(metrics["total_matches_processed"], 1)
        self.assertEqual(metrics["llm_calls"], 0)
        self.assertEqual(metrics["llm_calls_skipped"], 1)
        self.assertEqual(metrics["llm_avoidance_rate"], 1.0)

    def test_double_count_prevention(self):
        res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, {"use_llm": False})
        exact_reqs = [m["requirement"] for m in res.exact_matches]
        semantic_reqs = [m["requirement"] for m in res.semantic_matches]
        taxonomy_reqs = [m["requirement"] for m in res.taxonomy_matches]
        
        for skill in exact_reqs:
            self.assertNotIn(skill, semantic_reqs)
            self.assertNotIn(skill, taxonomy_reqs)

    def test_scoring_weights_and_bounds(self):
        res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, {"use_llm": False})
        score = res.match_score * 100.0
        self.assertTrue(0.0 <= score <= 100.0)
        self.assertTrue(0.0 <= res.base_score <= 100.0)

    @patch("src.services.groq.GroqService.completion")
    def test_bounded_combiner_adjustments(self, mock_completion):
        mock_completion.return_value = json.dumps({
            "context_fit": 1.0,
            "transferable_skill_fit": 1.0,
            "responsibility_fit": 1.0,
            "experience_quality": 1.0,
            "confidence": 1.0,
            "reasoning": "Excellent candidate."
        })
        
        options = {
            "use_llm": True
        }
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            with patch("src.services.scoring_pipeline.MAX_LLM_ADJUSTMENT", 3.0):
                res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
                self.assertEqual(res.llm_adjustment, 3.0)
            
        mock_completion.return_value = json.dumps({
            "context_fit": 0.0,
            "transferable_skill_fit": 0.0,
            "responsibility_fit": 0.0,
            "experience_quality": 0.0,
            "confidence": 1.0,
            "reasoning": "Poor candidate fit."
        })
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            with patch("src.services.scoring_pipeline.MAX_LLM_ADJUSTMENT", 3.0):
                res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
                self.assertEqual(res.llm_adjustment, -3.0)

    @patch("src.services.groq.GroqService.completion")
    def test_llm_various_failures(self, mock_completion):
        mock_completion.side_effect = Exception("Groq API Timeout")
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, {"use_llm": True})
            self.assertEqual(res.processing_mode, "deterministic_fallback")
            self.assertEqual(res.llm_adjustment, 0.0)

        mock_completion.side_effect = None
        mock_completion.return_value = "Not JSON string"
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, {"use_llm": True})
            self.assertEqual(res.processing_mode, "deterministic_fallback")
            self.assertEqual(res.llm_adjustment, 0.0)

        mock_completion.return_value = json.dumps({"context_fit": 0.90})
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, {"use_llm": True})
            self.assertEqual(res.processing_mode, "deterministic_fallback")
            self.assertEqual(res.llm_adjustment, 0.0)

    @patch("src.services.groq.GroqService.completion")
    def test_cache_invalidation_rules(self, mock_completion):
        mock_completion.return_value = json.dumps({
            "context_fit": 0.8,
            "transferable_skill_fit": 0.8,
            "responsibility_fit": 0.8,
            "experience_quality": 0.8,
            "confidence": 0.8,
            "reasoning": "Fits well."
        })
        
        try:
            from src.database.connection import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM matches")
            cursor.execute("DELETE FROM llm_cache")
            cursor.execute("INSERT OR REPLACE INTO resumes (id, filename, raw_text, parsed_json) VALUES (?, ?, ?, ?)",
                           ("test-r", "t.pdf", "res text", "{}"))
            cursor.execute("INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed) VALUES (?, ?, ?, ?, ?, ?)",
                           ("test-j", "t job", "c", "http://u", "jd text", "{}"))
            conn.commit()
            conn.close()
        except Exception:
            pass

        options = {
            "resume_id": "test-r",
            "job_id": "test-j",
            "resume_raw_text": "res text",
            "jd_raw_text": "jd text",
            "use_llm": True
        }
        
        res1 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        self.assertFalse(res1.cache["local_hit"])
        self.assertFalse(res1.cache["llm_hit"])
        
        res2 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        self.assertTrue(res2.cache["local_hit"])
        
        from src.config import Config
        with patch.object(Config, "MATCHER_VERSION", "v9.9"):
            res3 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            self.assertFalse(res3.cache["local_hit"])
            
        with patch.object(Config, "TAXONOMY_VERSION", "v9.9"):
            res4 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            self.assertFalse(res4.cache["local_hit"])
            
        with patch.object(Config, "EMBEDDING_MODEL_VERSION", "v9.9"):
            res5 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            self.assertFalse(res5.cache["local_hit"])

        with patch.object(Config, "SCORING_CONFIG_VERSION", "v9.9"):
            res6 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
            self.assertFalse(res6.cache["local_hit"])
            
        try:
            from src.database.connection import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed) VALUES (?, ?, ?, ?, ?, ?)",
                           ("test-j2", "t job 2", "c", "http://u2", "jd text 2", "{}"))
            conn.commit()
            conn.close()
        except Exception:
            pass
            
        options2 = {
            "resume_id": "test-r",
            "job_id": "test-j2",
            "resume_raw_text": "res text",
            "jd_raw_text": "jd text 2",
            "use_llm": True
        }
        
        with patch("src.services.scoring_pipeline.should_route_to_llm", return_value=True):
            res_llm1 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options2)
            self.assertFalse(res_llm1.cache["llm_hit"])
            
            res_llm2 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options2)
            self.assertTrue(res_llm2.cache["llm_hit"])
            
            with patch.object(Config, "PROMPT_VERSION", "v9.9"):
                res_llm3 = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options2)
                self.assertFalse(res_llm3.cache["llm_hit"])

    def test_concurrent_matching_safety(self):
        import concurrent.futures
        try:
            from src.database.connection import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM matches")
            for i in range(5):
                cursor.execute("""
                    INSERT OR REPLACE INTO jobs (id, title, company, url, jd_raw, jd_parsed)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (f"job-{i}", f"Title {i}", "Company", f"http://url-{i}", f"jd raw {i}", "{}"))
            conn.commit()
            conn.close()
        except Exception:
            pass

        options_list = []
        for i in range(5):
            options_list.append({
                "resume_id": "test-resume-123",
                "job_id": f"job-{i}",
                "use_llm": False
            })

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(ScoringPipeline.match, self.resume_parsed, self.jd_parsed, opts): opts for opts in options_list}
            for future in concurrent.futures.as_completed(futures):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as e:
                    self.fail(f"Concurrent matching raised exception: {e}")

        self.assertEqual(len(results), 5)
        for r in results:
            self.assertTrue(r.match_score > 0.0)

    def test_application_decision_engine(self):
        from src.services.application_decision_engine import ApplicationDecisionEngine
        
        # Test case: AUTO_APPLY (score >= 85 and confidence >= 0.90)
        dec1 = ApplicationDecisionEngine.evaluate(85.0, 0.90)
        self.assertEqual(dec1.decision, "AUTO_APPLY")
        self.assertIn("Excellent fit score", dec1.reason)
        self.assertEqual(dec1.confidence, 0.90)
        
        # Test case: REVIEW (score >= 75)
        dec2 = ApplicationDecisionEngine.evaluate(75.0, 0.85)
        self.assertEqual(dec2.decision, "REVIEW")
        self.assertIn("Good fit score", dec2.reason)
        
        # Test case: REJECT
        dec3 = ApplicationDecisionEngine.evaluate(74.0, 0.95)
        self.assertEqual(dec3.decision, "REJECT")
        self.assertIn("does not meet", dec3.reason)
        
        # Test integrated Matching Result has decision
        options = {
            "resume_id": "test-resume-123",
            "job_id": "test-job-123",
            "use_llm": False
        }
        res = ScoringPipeline.match(self.resume_parsed, self.jd_parsed, options)
        self.assertIn("application_decision", res.to_dict())
        decision_dict = res.application_decision
        self.assertIn("decision", decision_dict)
        self.assertIn("reason", decision_dict)
        self.assertIn("confidence", decision_dict)

if __name__ == "__main__":
    unittest.main()
