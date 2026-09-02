import json
import urllib.request
import urllib.error
import logging
import re
from src.config import Config

logger = logging.getLogger(__name__)

def clean_and_parse_json(content_str: str) -> dict:
    """
    Cleans raw LLM response strings before parsing JSON to handle:
    - Markdown code fences (```json ... ```)
    - Trailing commas before closing braces/brackets (e.g. {"a": 1,})
    - Leading/trailing whitespace
    - Fallback regex extraction of outermost JSON object
    """
    if not isinstance(content_str, str):
        return content_str

    cleaned = content_str.strip()

    # 1. Remove markdown code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    # 2. Extract outermost JSON object/array if there is extra pre/post text
    match = re.search(r"(\{.*\}|\[.*\])", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(1).strip()

    # 3. Fix trailing commas before closing braces/brackets
    cleaned = re.sub(r",\s*([\}\]])", r"\1", cleaned)

    # 4. Parse with json.loads
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Fallback: replace single quotes around key property names if any
        fixed = re.sub(r"'([a-zA-Z0-9_]+)'\s*:", r'"\1":', cleaned)
        return json.loads(fixed)
 
class GroqRateLimiter:
    import threading
    _lock = threading.Lock()
    _last_request_time = 0.0
    MIN_INTERVAL = 10.0

    @classmethod
    def acquire(cls):
        import time
        with cls._lock:
            now = time.time()
            elapsed = now - cls._last_request_time
            if elapsed < cls.MIN_INTERVAL:
                wait_time = cls.MIN_INTERVAL - elapsed
                time.sleep(wait_time)
            cls._last_request_time = time.time()

class GroqService:
    @classmethod
    def get_api_url(cls) -> str:
        return getattr(Config, "LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")

    @classmethod
    def get_model(cls) -> str:
        return getattr(Config, "LLM_MODEL", "llama-3.1-8b-instant")

    @classmethod
    def _make_api_call(cls, payload: dict, headers: dict, timeout: int = 30, max_retries: int = 5) -> str:
        """
        Executes HTTP request to Groq API with retries and exponential backoff.
        """
        import time
        import urllib.request
        import urllib.error
        import random

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(cls.get_api_url(), data=req_data, headers=headers, method="POST")

        backoff = 2.0
        for attempt in range(max_retries + 1):
            try:
                # Global rate limiting acquisition before sending the request
                GroqRateLimiter.acquire()
                with urllib.request.urlopen(req, timeout=timeout) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                # Read response body for better logging
                try:
                    error_body = e.read().decode("utf-8")
                except Exception:
                    error_body = "Could not read error body"
                
                # Check for 429 (Too Many Requests) or 5xx server errors
                if e.code == 429 or e.code >= 500:
                    if attempt < max_retries:
                        sleep_time = backoff + random.uniform(0, 1.0)
                        if e.code == 429:
                            retry_after = e.headers.get("Retry-After")
                            if retry_after:
                                try:
                                    sleep_time = float(retry_after) + 0.5
                                except ValueError:
                                    pass
                        logger.warning(f"Groq API returned HTTP {e.code}. Retrying in {sleep_time:.2f}s... (Attempt {attempt + 1}/{max_retries})")
                        time.sleep(sleep_time)
                        backoff *= 2.0
                        continue
                logger.error(f"Groq API HTTP Error: {e.code} - {error_body}")
                raise Exception(f"Groq API Error: {error_body}")
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < max_retries:
                    sleep_time = backoff + random.uniform(0, 1.0)
                    logger.warning(f"Groq API communication error: {e}. Retrying in {sleep_time:.2f}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(sleep_time)
                    backoff *= 2.0
                    continue
                logger.error(f"Failed to communicate with Groq API after {max_retries} retries: {e}")
                raise
            except Exception as e:
                logger.error(f"Unexpected error calling Groq API: {e}")
                raise

    @classmethod 
    def parse_resume(cls, resume_text: str) -> dict:
        """
        Sends the extracted resume text to the Groq API to convert it into a
        highly structured, standardized JSON format.
        """
        if not Config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")

        resume_text = resume_text[:3500] if len(resume_text) > 3500 else resume_text

        system_prompt = (
            "You are an expert resume parsing engine. Convert the unstructured resume text into a structured JSON conforming to the schema below. "
            "Output ONLY the valid JSON object. Do not include any pre-text, post-text, explanation, or markdown.\n\n"
            "SCHEMA DEFINITION:\n"
            "{\n"
            '  "contact_info": { "name": str, "email": str, "phone": str, "location": str, "linkedin": str, "github": str, "portfolio": str },\n'
            '  "professional_summary": str or null,\n'
            '  "skills": { "languages": [], "frameworks": [], "libraries": [], "ai_ml": [], "genai": [], "databases": [], "cloud": [], "devops": [], "tools": [], "web": [], "soft_skills": [] },\n'
            '  "experience": [ { "company": str, "role": str, "employment_type": str, "department": str, "location": str, "start_date": str, "end_date": str, "technologies": [], "tools": [], "description": [], "responsibilities": [], "achievements": [] } ],\n'
            '  "projects": [ { "name": str, "description": str, "url": str, "repository": str, "technologies": [] } ],\n'
            '  "education": [ { "institution": str, "degree": str, "specialization": str, "location": str, "graduation_year": str, "start_date": str, "end_date": str, "cgpa_or_percentage": str, "coursework": [], "honors": [] } ],\n'
            '  "certifications": [ { "name": str, "issuer": str, "issue_date": str, "expiry_date": str, "credential_id": str, "url": str } ],\n'
            '  "achievements": [], "publications": [ { "title": str, "publisher": str, "date": str, "url": str } ], "patents": [], "languages": [], "awards": [], "volunteer_experience": [], "leadership": [], "hackathons": [],\n'
            '  "coding_profiles": { "leetcode": str, "codeforces": str, "hackerrank": str }, "interests": [], "extracurriculars": [],\n'
            '  "metadata": { "parsed_at": str, "parser_version": "2.0", "pages": int or null, "language": str, "confidence": float, "parsing_time_ms": int or null }\n'
            "}\n\n"
            "CRITICAL RULES:\n"
            "1. Output valid JSON. Do not include markdown formatting.\n"
            "2. Extract actual contact details and URLs (no placeholders).\n"
            "3. Group skills accurately. Return empty arrays [] for empty list/array fields, or null for empty string/object fields.\n"
            "4. Normalize dates to ISO-8601 (YYYY-MM) where possible.\n"
            "5. NO INFERENCES/HALLUCINATIONS: Do not guess, assume, or invent any information. If a field (e.g. location, department, or technologies inside experience/projects/education) is not explicitly stated in the resume text, you MUST set it to null or an empty array [].\n"
            "6. SOFT SKILLS: Actively extract any soft skills mentioned in the resume (e.g., communication, leadership, teamwork, problem solving, organization, adaptability) and populate them inside the \"soft_skills\" array under the \"skills\" object."
        )

        user_content = f"Parse the following resume text:\n\n{resume_text}"

        headers = {
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        payload = {
            "model": cls.get_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            res_body = cls._make_api_call(payload, headers, timeout=30)
            res_json = json.loads(res_body)
            content = res_json["choices"][0]["message"]["content"]
            return clean_and_parse_json(content)
        except Exception as e:
            logger.error(f"Failed to parse resume via Groq API: {e}")
            raise

    @classmethod
    def parse_jd(cls, jd_text: str) -> dict:
        """
        Sends the extracted Job Description (JD) text to the Groq API to convert it into a
        structured JSON format suitable for embedding and matching against resumes.
        """
        if not Config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")

        jd_text = jd_text[:3500] if len(jd_text) > 3500 else jd_text

        system_prompt = (
            "You are an expert HR parsing engine. Your job is to extract unstructured Job Description (JD) text "
            "and convert it into a strict, structured JSON format conforming to the IDEAL JD SCHEMA.\n"
            "Output ONLY a valid JSON object. Do not include any markdown formatting.\n\n"
            "CRITICAL EXTRACTION RULES:\n"
            "1. REQUIRED SKILLS: Extract mandatory technical and soft skills. Group them correctly.\n"
            "2. PREFERRED SKILLS: Extract optional/bonus skills.\n"
            "3. RESPONSIBILITIES: Extract the core day-to-day responsibilities into a list.\n"
            "4. REQUIREMENTS: Extract minimum years of experience, education level, and other hard requirements.\n\n"
            "IDEAL JD SCHEMA:\n"
            "{\n"
            '  "title": "Extracted Job Title",\n'
            '  "required_skills": {\n'
            '    "languages": ["Python"],\n'
            '    "frameworks": ["React"],\n'
            '    "databases": ["PostgreSQL"],\n'
            '    "cloud_devops": ["AWS"],\n'
            '    "tools": ["Git"],\n'
            '    "soft_skills": ["Communication"]\n'
            '  },\n'
            '  "preferred_skills": ["Bonus Skill 1", "Bonus Skill 2"],\n'
            '  "responsibilities": ["Responsibility 1", "Responsibility 2"],\n'
            '  "requirements": {\n'
            '    "years_of_experience": "Number or range (e.g., 3-5)",\n'
            '    "education": "Required degree (e.g., Bachelor\'s in CS)",\n'
            '    "other": ["Must be US Citizen"]\n'
            '  }\n'
            "}"
        )

        user_content = f"Parse the following Job Description text:\n\n{jd_text}"

        headers = {
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        payload = {
            "model": cls.get_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            res_body = cls._make_api_call(payload, headers, timeout=30)
            res_json = json.loads(res_body)
            content = res_json["choices"][0]["message"]["content"]
            return clean_and_parse_json(content)
        except Exception as e:
            logger.error(f"Failed to communicate with Groq API for JD parsing: {e}")
            raise

    @classmethod
    def generate_match_analysis(cls, resume_json: dict, jd_json: dict) -> dict:
        """
        Performs a context-aware matching analysis between the resume and JD JSONs.
        Follows strict recruiter guidelines:
        - Synonym matching (JS/JavaScript, Postgres/PostgreSQL, Sklearn/Scikit-learn)
        - Strict technology distinction (TensorFlow != PyTorch, React != Angular, Postgres != MySQL, Docker != Kubernetes)
        - Experience depth evaluation (projects, internships, years of experience, certifications)
        - Missing skills guidelines (don't flag if related equivalent exists)
        """
        if not Config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")

        system_prompt = (
            "You are a technical recruiter. Evaluate the resume against the JD JSON. Output ONLY valid JSON matching the schema.\n\n"
            "RULES:\n"
            "1. SKILLS: Differentiate required from optional. Penalize heavily for missing required skills. Allow synonyms (JS/JavaScript, Postgres/PostgreSQL) but keep strict distinctions. "
            "Do NOT match distinct technologies (e.g., SQL != NoSQL, Java != JavaScript, Git != GitOps, .NET != Internet, TensorFlow != PyTorch, React != Angular, Postgres != MySQL).\n"
            "2. EVIDENCE over Keywords: Do not give full credit for skills listed without context. Prefer: Work Exp > Production Projects > Research/Internships > Personal Projects > Certifications.\n"
            "3. RELEVANCY/RECENCY: Value recent experience (last 2-3 years) and depth (scale, architecture, deployment) over tutorial-level work.\n"
            "4. SCORING: Calculate weighted score (0.0 to 1.0): core requirements (60%), experience depth (30%), optional skills (10%).\n"
            "5. NO HALLUCINATIONS: Do not assume or infer skills not explicitly documented.\n\n"
            "JSON SCHEMA:\n"
            "{\n"
            '  "match_score": 0.85,\n'
            '  "matched_skills": ["React", "Python"],\n'
            '  "missing_skills": ["AWS"],\n'
            '  "reasoning": "### Strengths:\\n- ...\\n\\n### Gaps:\\n- ...\\n\\n### Recommendation:\\n- ..."\n'
            "}"
        )

        user_content = f"Candidate Resume:\n{json.dumps(resume_json)}\n\nJob Description:\n{json.dumps(jd_json)}"

        headers = {
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Job-Matcher/1.0"
        }

        payload = {
            "model": cls.get_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }

        try:
            res_body = cls._make_api_call(payload, headers, timeout=25)
            res_json = json.loads(res_body)
            content = res_json["choices"][0]["message"]["content"]
            return clean_and_parse_json(content)
        except Exception as e:
            logger.error(f"Failed to generate match analysis via Groq API: {e}")
            return {
                "match_score": -1.0,
                "matched_skills": [],
                "missing_skills": [],
                "reasoning": "Could not generate reasoning due to API rate limit/error."
            }

    @classmethod
    def completion(cls, prompt: str, system_prompt: str = "You are a helpful assistant.", response_json: bool = False) -> str:
        """
        Runs a generic chat completion request against the Groq API.
        """
        if not Config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")

        headers = {
            "Authorization": f"Bearer {Config.GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Job-Matcher/1.0"
        }

        payload = {
            "model": cls.get_model(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        try:
            res_body = cls._make_api_call(payload, headers, timeout=25)
            res_json = json.loads(res_body)
            return res_json["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"Groq API completion failed: {e}")
            raise

