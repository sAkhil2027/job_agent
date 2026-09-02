import unittest
from unittest.mock import patch
import json
from src.services.skills_registry import Skill, validate_registry
from src.services.skills_normalization import SkillNormalizationService, SkillComparisonEngine
from src.services.resume_aggregation import ResumeSkillAggregationService
from src.services.skills_relationship import SkillRelationship, validate_relationships
from src.services.capability_graph import validate_capability_graph, find_capability_path
from src.services.capability_matcher import CapabilityMatchingEngine
from src.services.groq import GroqService, GroqRateLimiter
from src.services.llm_reasoning import LLMReasoningService
from src.database.connection import get_connection

class TestSkillsPipeline(unittest.TestCase):
    def test_alias_normalization(self):
        # JD contains aliases like "js", "postgres", "aws", "reactjs"
        jd = "We are looking for a software engineer skilled in JS, Postgres, AWS, and ReactJS."
        skills = SkillNormalizationService.extract_skills(jd)
        
        self.assertIn("JavaScript", skills)
        self.assertIn("PostgreSQL", skills)
        self.assertIn("AWS", skills)
        self.assertIn("React", skills)
        
    def test_tricky_boundaries_and_r_context(self):
        # Tricky cases: C++, C#, Docker vs Dockerized/Dock, Git vs GitOps
        # "r." should not match R language because there is no programming/language context in it.
        # "R programming" should match.
        jd1 = "Required: C++ developer, C# experience. We use git. Candidate must not be dock/dockerized or gitops developer. Bullet point: r."
        skills1 = SkillNormalizationService.extract_skills(jd1)
        
        self.assertIn("C++", skills1)
        self.assertIn("C#", skills1)
        self.assertIn("Git", skills1)
        self.assertNotIn("Docker", skills1)
        self.assertNotIn("R", skills1) # Rejected due to lack of R context
        
        jd2 = "Required: R programming language experience and python."
        skills2 = SkillNormalizationService.extract_skills(jd2)
        self.assertIn("R", skills2) # Accepted due to R context
        self.assertIn("Python", skills2)
        
    def test_comparison_engine_casing_and_synonyms(self):
        # Unregistered/custom skill case-insensitivity: PySpark vs pyspark
        # Synonym matching: REST vs REST API (both canonicalize to REST API)
        resume_skills = ["Python", "SQL", "Docker", "PySpark", "REST"]
        jd_skills = ["python", "SQL", "AWS", "pyspark", "REST API"]
        
        exact, soft, missing, extra = SkillComparisonEngine.compare_skills(resume_skills, jd_skills)
        
        self.assertIn("Python", exact)
        self.assertIn("SQL", exact)
        self.assertIn("PySpark", exact) # Resolved case-insensitively
        self.assertIn("REST API", exact) # Synonym matched
        self.assertNotIn("AWS", exact)
        self.assertIn("AWS", missing)
        self.assertIn("Docker", extra)

    def test_fuzzy_matching(self):
        # Spacing variations matching to canonical via fuzzy fallback
        res_skill = SkillNormalizationService.resolve_canonical_skill("Tensor Flow")
        self.assertEqual(res_skill.skill_id, "tensorflow")

    def test_registry_validation(self):
        # Good registry
        self.assertTrue(validate_registry())
        
        # Duplicate canonical ID validation
        bad_registry_1 = [
            Skill("python", "Python", "Python", ["py"]),
            Skill("python", "Python2", "Python2", ["py2"])
        ]
        with self.assertRaises(ValueError):
            validate_registry(bad_registry_1)
            
        # Duplicate alias validation
        bad_registry_2 = [
            Skill("python", "Python", "Python", ["py"]),
            Skill("py-lang", "PyLang", "PyLang", ["py"])
        ]
        with self.assertRaises(ValueError):
            validate_registry(bad_registry_2)

    def test_resume_skill_aggregation(self):
        # Mock structured parsed resume JSON
        resume_parsed = {
            "skills": {
                "languages": ["Python", "SQL"]
            },
            "experience": [
                {
                    "company": "Google",
                    "technologies": ["Go"],
                    "tools": ["Git"],
                    "description": ["Developed REST APIs in Go. Used postgres for storage."]
                }
            ],
            "projects": [
                {
                    "name": "App",
                    "technologies": ["React"],
                    "description": "Built UI using React."
                }
            ],
            "certifications": [
                "AWS Certified Solutions Architect"
            ],
            "education": [
                {
                    "coursework": ["Intro to Machine Learning"]
                }
            ]
        }
        raw_text = "Other details: Redis database experience."
        
        profile = ResumeSkillAggregationService.build_profile(resume_parsed, raw_text)
        skills = profile.skills
        
        # Assert python (Skills Section) has confidence 1.0
        self.assertIn("python", skills)
        self.assertEqual(skills["python"].confidence, 1.0)
        self.assertIn("Skills Section", skills["python"].sources)
        
        # Assert Go (Work Experience) has confidence 0.95
        self.assertIn("go", skills)
        self.assertEqual(skills["go"].confidence, 0.95)
        self.assertIn("Work Experience", skills["go"].sources)
        self.assertIn("Developed REST APIs in Go.", skills["go"].evidence)
        
        # Assert PostgreSQL/postgres extracted from description sentence
        self.assertIn("postgresql", skills)
        self.assertEqual(skills["postgresql"].confidence, 0.95)
        self.assertIn("Used postgres for storage.", skills["postgresql"].evidence)

        # Assert React (Projects) has confidence 0.90
        self.assertIn("react", skills)
        self.assertEqual(skills["react"].confidence, 0.90)
        self.assertIn("Projects", skills["react"].sources)
        self.assertIn("Built UI using React.", skills["react"].evidence)
        
        # Assert AWS (Certifications) has confidence 0.90
        self.assertIn("aws", skills)
        self.assertEqual(skills["aws"].confidence, 0.90)
        self.assertIn("Certifications", skills["aws"].sources)
        
        # Assert Machine Learning (Education) has confidence 0.80
        self.assertIn("machine_learning", skills)
        self.assertEqual(skills["machine_learning"].confidence, 0.80)
        self.assertIn("Education", skills["machine_learning"].sources)

        # Assert Redis (Raw Text Fallback) has confidence 0.60
        self.assertIn("redis", skills)
        self.assertEqual(skills["redis"].confidence, 0.60)
        self.assertIn("Raw Resume Text", skills["redis"].sources)

    def test_skill_relationships_and_soft_matching(self):
        # Candidate has GCP and FastAPI
        # JD requires AWS and Django
        resume_skills = ["GCP", "FastAPI"]
        jd_skills = ["AWS", "Django"]
        
        exact, soft, missing, extra = SkillComparisonEngine.compare_skills(resume_skills, jd_skills)
        
        self.assertEqual(len(exact), 0)
        self.assertEqual(len(missing), 0)
        
        # We expect AWS matched through GCP, and Django matched through FastAPI
        aws_match = next((s for s in soft if s["required_skill"] == "AWS"), None)
        self.assertIsNotNone(aws_match)
        self.assertEqual(aws_match["candidate_skill"], "GCP")
        self.assertEqual(aws_match["transferability_score"], 0.90)
        
        django_match = next((s for s in soft if s["required_skill"] == "Django"), None)
        self.assertIsNotNone(django_match)
        self.assertEqual(django_match["candidate_skill"], "FastAPI")
        self.assertEqual(django_match["transferability_score"], 0.80)

    def test_relationships_validation(self):
        self.assertTrue(validate_relationships())
        
        # Invalid source ID
        bad_rel_1 = [SkillRelationship("invalid_id", "aws", "Cloud Platform", 0.90, "Explanation")]
        with self.assertRaises(ValueError):
            validate_relationships(bad_rel_1)
            
        # Invalid transferability score
        bad_rel_2 = [SkillRelationship("gcp", "aws", "Cloud Platform", 1.5, "Explanation")]
        with self.assertRaises(ValueError):
            validate_relationships(bad_rel_2)
            
        # Duplicate relationships
        bad_rel_3 = [
            SkillRelationship("gcp", "aws", "Cloud Platform", 0.90, "Explanation"),
            SkillRelationship("gcp", "aws", "Cloud Platform", 0.85, "Another explanation")
        ]
        with self.assertRaises(ValueError):
            validate_relationships(bad_rel_3)

    def test_capability_graph_validation_and_traversal(self):
        # Verify graph is valid
        self.assertTrue(validate_capability_graph())
        
        # Test traversal: spark -> distributed_computing -> data_pipelines
        score, path_desc = find_capability_path("spark", "data_pipelines")
        self.assertAlmostEqual(score, 0.95 * 0.90)
        self.assertEqual(len(path_desc), 2)
        self.assertIn("Apache Spark is a distributed cluster-computing framework", path_desc[0])
        
        # Unreachable nodes
        score_bad, path_bad = find_capability_path("spark", "react")
        self.assertEqual(score_bad, 0.0)
        self.assertEqual(len(path_bad), 0)

    def test_capability_matching_engine_pipeline(self):
        # Mock resume with Spark and LangChain
        resume_parsed = {
            "skills": {},
            "experience": [
                {
                    "company": "Company A",
                    "technologies": ["Spark"],
                    "description": ["Developed ETL pipelines using Spark."]
                }
            ],
            "projects": [
                {
                    "name": "Project A",
                    "technologies": ["LangChain"],
                    "description": "Built a RAG-based AI chatbot using LangChain."
                }
            ]
        }
        # JD requiring Data Pipelines and LLM Engineering
        jd_parsed = {
            "required_skills": {
                "languages": ["Data Pipelines", "LLM Engineering"]
            }
        }
        
        result = CapabilityMatchingEngine.match_capabilities(
            resume_parsed=resume_parsed,
            jd_parsed=jd_parsed
        )
        
        # Verify matched capabilities
        matched = result["matched_capabilities"]
        self.assertEqual(len(matched), 2)
        
        # Verify Spark matched Data Pipelines via graph path
        pipeline_match = next((m for m in matched if m["requirement"] == "Data Pipelines"), None)
        self.assertIsNotNone(pipeline_match)
        self.assertEqual(pipeline_match["match_type"], "transferable")
        self.assertAlmostEqual(pipeline_match["score"], 0.85)
        
        # Verify LangChain matched LLM Engineering via graph path
        llm_match = next((m for m in matched if m["requirement"] == "LLM Engineering"), None)
        self.assertIsNotNone(llm_match)
        self.assertEqual(llm_match["match_type"], "transferable")
        self.assertAlmostEqual(llm_match["score"], 0.95)

    @patch("src.services.groq.GroqService.completion")
    def test_llm_reasoning_fallback_success_and_batching(self, mock_completion):
        # Mock the JSON batched completion response using new required_id contract
        mock_response = {
            "results": [
                {
                    "required_id": "llm_security",
                    "matched": True,
                    "confidence": 0.85,
                    "reasoning": "Candidate built a secure chatbot",
                    "evidence": "Built a RAG-based AI chatbot using LangChain."
                },
                {
                    "required_id": "kubernetes",
                    "matched": True,
                    "confidence": 0.90,
                    "reasoning": "Candidate knows k8s",
                    "evidence": "This sentence does not exist in resume." # Invalid evidence!
                }
            ]
        }
        mock_completion.return_value = json.dumps(mock_response)

        resume_parsed = {
            "skills": {},
            "experience": [],
            "projects": [
                {
                    "name": "Project A",
                    "description": "Built a RAG-based AI chatbot using LangChain."
                }
            ]
        }
        jd_parsed = {
            "required_skills": {
                "languages": ["LLM Security", "Kubernetes"]
            }
        }

        # Clear any prior semantic cache for test predictability
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM semantic_cache")
            conn.commit()
            conn.close()
        except Exception:
            pass

        # Run with use_llm=True
        result = CapabilityMatchingEngine.match_capabilities(
            resume_parsed=resume_parsed,
            jd_parsed=jd_parsed,
            use_llm=True
        )

        matched = result["matched_capabilities"]
        # LLM Security should match because the evidence exists
        llm_match = next((m for m in matched if m["requirement"] == "LLM Security"), None)
        self.assertIsNotNone(llm_match)
        self.assertEqual(llm_match["match_type"], "semantic")
        self.assertEqual(llm_match["score"], 0.85)

        # Kubernetes should be rejected because the evidence doesn't exist in the resume
        k8s_match = next((m for m in matched if m["requirement"] == "Kubernetes"), None)
        self.assertIsNone(k8s_match)
        self.assertIn("Kubernetes", result["missing_skills"])

        # Check that completion was called exactly once (batched!)
        mock_completion.assert_called_once()

    @patch("src.services.groq.GroqService.completion")
    def test_llm_reasoning_fallback_failure_circuit_breaker(self, mock_completion):
        # Mock completion to raise an Exception (provider down)
        mock_completion.side_effect = Exception("API Connection Refused")

        resume_parsed = {"skills": {}}
        jd_parsed = {
            "required_skills": {
                "languages": ["LLM Engineering", "Kubernetes"]
            }
        }

        # Clear semantic cache
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM semantic_cache")
            conn.commit()
            conn.close()
        except Exception:
            pass

        # Run match with use_llm=True
        result = CapabilityMatchingEngine.match_capabilities(
            resume_parsed=resume_parsed,
            jd_parsed=jd_parsed,
            use_llm=True
        )

        # Matching must not crash, must return remaining deterministic matches (empty here) and missing
        self.assertEqual(len(result["matched_capabilities"]), 0)
        self.assertEqual(len(result["missing_skills"]), 2)
        # Verify call was attempted but handled gracefully
        mock_completion.assert_called_once()

    @patch("src.services.groq.GroqService.completion")
    def test_semantic_caching_reads_and_writes(self, mock_completion):
        # Mock the LLM output
        mock_response = {
            "results": [
                {
                    "required_id": "llm_security",
                    "matched": True,
                    "confidence": 0.95,
                    "reasoning": "Candidate knows security features",
                    "evidence": "Built a RAG-based AI chatbot using LangChain."
                }
            ]
        }
        mock_completion.return_value = json.dumps(mock_response)

        resume_parsed = {
            "skills": {},
            "experience": [],
            "projects": [
                {
                    "name": "Project A",
                    "description": "Built a RAG-based AI chatbot using LangChain."
                }
            ]
        }
        jd_parsed = {
            "required_skills": {
                "languages": ["LLM Security"]
            }
        }

        # Clear semantic cache
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM semantic_cache")
            conn.commit()
            conn.close()
        except Exception:
            pass

        # 1. First Run: Should write to Cache and trigger GroqService.completion
        result1 = CapabilityMatchingEngine.match_capabilities(
            resume_parsed=resume_parsed,
            jd_parsed=jd_parsed,
            use_llm=True
        )
        self.assertEqual(len(result1["matched_capabilities"]), 1)
        self.assertEqual(result1["matched_capabilities"][0]["match_type"], "semantic")
        mock_completion.assert_called_once()
 
        # Reset mock call stats
        mock_completion.reset_mock()
 
        # 2. Second Run: Should read from Cache and skip calling GroqService.completion entirely!
        result2 = CapabilityMatchingEngine.match_capabilities(
            resume_parsed=resume_parsed,
            jd_parsed=jd_parsed,
            use_llm=True
        )
        self.assertEqual(len(result2["matched_capabilities"]), 1)
        self.assertEqual(result2["matched_capabilities"][0]["match_type"], "semantic")
        mock_completion.assert_not_called()

if __name__ == "__main__":
    unittest.main()
