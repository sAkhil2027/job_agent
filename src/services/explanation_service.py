import json
import logging
import uuid
from src.database.connection import execute_db_with_retry
from src.services.groq import GroqService
from src.services.scoring_pipeline import ScoringPipeline

logger = logging.getLogger(__name__)

class DetailedExplanationService:
    @classmethod
    def get_detailed_explanation(cls, resume_id: str, job_id: str) -> str:
        """
        On-demand detailed AI analysis of the match between a Resume and Job Description.
        Checks the ai_explanations cache table first.
        On miss, builds a compact evidence context, prompts Groq, and caches the result.
        """
        # 1. Check explanation cache
        def check_cache(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT explanation FROM ai_explanations WHERE resume_id = ? AND job_id = ?", (resume_id, job_id))
            row = cursor.fetchone()
            return row[0] if row else None
            
        try:
            cached_exp = execute_db_with_retry(check_cache)
            if cached_exp:
                logger.info("AI Explanation Cache Hit.")
                return cached_exp
        except Exception as e:
            logger.error(f"Error checking AI explanation cache: {e}")

        # 2. Fetch Resume and Job from DB
        def fetch_data(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT parsed_json FROM resumes WHERE id = ?", (resume_id,))
            resume_row = cursor.fetchone()
            cursor.execute("SELECT jd_parsed FROM jobs WHERE id = ?", (job_id,))
            job_row = cursor.fetchone()
            return (resume_row[0] if resume_row else None, job_row[0] if job_row else None)

        try:
            resume_json, job_json = execute_db_with_retry(fetch_data)
        except Exception as e:
            logger.error(f"Failed to fetch resume/job for detailed analysis: {e}")
            raise Exception("Resume or Job not found in database.")

        if not resume_json or not job_json:
            raise Exception("Resume or Job parsed JSON not found in database.")

        resume_parsed = json.loads(resume_json)
        jd_parsed = json.loads(job_json)

        # 3. Calculate match to get the evidence breakdown
        match_result = ScoringPipeline.match(
            resume=resume_parsed,
            jd=jd_parsed,
            options={"resume_id": resume_id, "job_id": job_id, "use_llm": True}
        )

        # 4. Build Compact Evidence Context
        compact_context = {
            "base_score": match_result.base_score,
            "match_score": match_result.match_score * 100.0,
            "confidence": match_result.confidence * 100.0,
            "matched_skills": match_result.matched_skills,
            "missing_skills": match_result.missing_skills,
            "experience_details": {
                "candidate_years": match_result.score_breakdown.get("candidate_experience_years", 0.0),
                "required_years": match_result.score_breakdown.get("required_experience_years", 0.0)
            }
        }

        # 5. Call LLM
        system_prompt = (
            "You are a professional technical recruiter and talent advisor.\n"
            "Provide a comprehensive, high-quality detailed match analysis based ONLY on the evidence provided.\n"
            "Respond in clean, formatted Markdown."
        )

        prompt = (
            f"Analyze this match context and generate a detailed report with these sections:\n"
            f"1. Candidate Strengths\n"
            f"2. Important Gaps\n"
            f"3. Why Transferable Skills Matter (if applicable)\n"
            f"4. Contextual Experience Assessment\n"
            f"5. Resume Improvement Suggestions\n\n"
            f"Context:\n{json.dumps(compact_context)}"
        )

        try:
            explanation = GroqService.completion(prompt, system_prompt, response_json=False)
        except Exception as e:
            logger.error(f"Groq Detailed Explanation call failed: {e}")
            explanation = (
                f"### AI Explanation Unavailable\n"
                f"Detailed matching analysis could not be generated due to an error: {e}"
            )
            # Do not cache error fallbacks
            return explanation

        # 6. Store in Cache
        def save_explanation(conn):
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO ai_explanations (id, resume_id, job_id, explanation)
                VALUES (?, ?, ?, ?)
            """, (str(uuid.uuid4()), resume_id, job_id, explanation))
            conn.commit()

        try:
            execute_db_with_retry(save_explanation)
        except Exception as e:
            logger.error(f"Failed to cache detailed explanation: {e}")

        return explanation
