import os
import json
import threading
import time
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
 
def compress_resume_for_llm(resume_dict: dict) -> dict:
    """
    Strips raw formatting, metadata, and empty fields from parsed resume
    to minimize token count sent to Groq.
    """
    if not isinstance(resume_dict, dict):
        return resume_dict

    compressed = {}
    if resume_dict.get("professional_summary"):
        compressed["summary"] = resume_dict["professional_summary"][:400]

    skills = resume_dict.get("skills", {})
    if isinstance(skills, dict):
        condensed_skills = {}
        for k, v in skills.items():
            if isinstance(v, list) and v:
                condensed_skills[k] = v[:15]
            elif isinstance(v, str) and v.strip():
                condensed_skills[k] = v
        if condensed_skills:
            compressed["skills"] = condensed_skills
    elif skills:
        compressed["skills"] = skills

    exps = resume_dict.get("experience", [])
    if isinstance(exps, list) and exps:
        condensed_exp = []
        for exp in exps[:4]:
            if isinstance(exp, dict):
                item = {
                    "role": exp.get("role", ""),
                    "company": exp.get("company", ""),
                    "duration": f"{exp.get('start_date', '')} to {exp.get('end_date', '')}"
                }
                resps = exp.get("responsibilities", [])
                if isinstance(resps, list) and resps:
                    item["highlights"] = [str(r)[:120] for r in resps[:3]]
                condensed_exp.append(item)
        if condensed_exp:
            compressed["experience"] = condensed_exp

    edu = resume_dict.get("education", [])
    if isinstance(edu, list) and edu:
        compressed["education"] = [
            {"degree": e.get("degree", ""), "field": e.get("specialization", "")}
            for e in edu if isinstance(e, dict)
        ]

    return compressed


def compress_jd_for_llm(jd_dict: dict) -> dict:
    """
    Strips boilerplate disclaimers, salary ranges, and empty fields from parsed JD
    to minimize token count sent to Groq.
    """
    if not isinstance(jd_dict, dict):
        return jd_dict

    compressed = {
        "title": jd_dict.get("title", "Unknown Title")
    }

    req_skills = jd_dict.get("required_skills", {})
    if isinstance(req_skills, dict):
        condensed_req = {}
        for k, v in req_skills.items():
            if isinstance(v, list) and v:
                condensed_req[k] = v[:12]
            elif isinstance(v, str) and v.strip():
                condensed_req[k] = v
        if condensed_req:
            compressed["required_skills"] = condensed_req
    elif req_skills:
        compressed["required_skills"] = req_skills

    pref = jd_dict.get("preferred_skills", [])
    if isinstance(pref, list) and pref:
        compressed["preferred_skills"] = [str(p)[:80] for p in pref[:8]]

    resps = jd_dict.get("responsibilities", [])
    if isinstance(resps, list) and resps:
        compressed["responsibilities"] = [str(r)[:150] for r in resps[:5]]

    reqs = jd_dict.get("requirements", {})
    if isinstance(reqs, dict) and reqs:
        compressed["requirements"] = {
            "experience": reqs.get("years_of_experience", ""),
            "education": reqs.get("education", "")
        }

    return compressed

class GroqRateLimiter:
    import threading
    _lock = threading.Lock()
    _last_request_time = 0.0
    MIN_INTERVAL = float(os.getenv("GROQ_MIN_INTERVAL", "1.0"))

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

# Global concurrency limiter: ensures only 1 active LLM request hits Groq at a time
_groq_semaphore = threading.Semaphore(1)

class GroqService:
    _current_working_model = None

    @classmethod
    def get_api_url(cls) -> str:
        return getattr(Config, "LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")

    @classmethod
    def get_model(cls) -> str:
        if cls._current_working_model:
            return cls._current_working_model
        return getattr(Config, "LLM_MODEL", "openai/gpt-oss-20b")

    @classmethod
    def get_candidate_models(cls) -> list:
        """Returns ordered list of candidate models with deduplication."""
        candidates = []
        if cls._current_working_model and cls._current_working_model not in candidates:
            candidates.append(cls._current_working_model)
        primary = getattr(Config, "LLM_MODEL", None)
        if primary and primary not in candidates:
            candidates.append(primary)
        fallbacks = getattr(Config, "LLM_FALLBACK_MODELS", [])
        for fb in fallbacks:
            if fb and fb not in candidates:
                candidates.append(fb)
        return candidates

    @classmethod
    def _make_api_call(cls, payload: dict, headers: dict, timeout: int = 30, max_retries: int = 3) -> str:
        """
        Executes HTTP request to Groq API with multi-model fallback, retries, and exponential backoff.
        Serialized through _groq_semaphore to strictly limit concurrency to 1 request at a time.
        """
        import time
        import urllib.request
        import urllib.error
        import random

        # Acquire global single-request concurrency lock
        with _groq_semaphore:
            candidate_models = cls.get_candidate_models()
            requested_model = payload.get("model")
            if requested_model and requested_model in candidate_models:
                candidate_models.remove(requested_model)
                candidate_models.insert(0, requested_model)
            elif requested_model:
                candidate_models.insert(0, requested_model)

            last_error = None
            attempted_models = []

            for model_idx, model_name in enumerate(candidate_models):
                attempted_models.append(model_name)
                payload_copy = dict(payload)
                payload_copy["model"] = model_name
                req_data = json.dumps(payload_copy).encode("utf-8")
                req = urllib.request.Request(cls.get_api_url(), data=req_data, headers=headers, method="POST")

                backoff = 1.5
                model_failed = False

                for attempt in range(max_retries + 1):
                    try:
                        GroqRateLimiter.acquire()
                        with urllib.request.urlopen(req, timeout=timeout) as response:
                            res_data = response.read().decode("utf-8")
                            if cls._current_working_model != model_name:
                                logger.info(f"Model '{model_name}' active and responding successfully.")
                                cls._current_working_model = model_name
                            return res_data
                    except urllib.error.HTTPError as e:
                        try:
                            error_body = e.read().decode("utf-8")
                        except Exception:
                            error_body = "Could not read error body"

                        err_lower = error_body.lower()
                        is_model_error = (
                            e.code == 404 or 
                            "model_not_found" in err_lower or 
                            "does not exist" in err_lower or
                            "decommissioned" in err_lower or
                            ("invalid_request_error" in err_lower and "model" in err_lower)
                        )

                        if is_model_error:
                            logger.warning(
                                f"Groq model '{model_name}' unavailable ({e.code}). Trying fallback model..."
                            )
                            last_error = Exception(f"Model '{model_name}' error: {error_body}")
                            model_failed = True
                            break  # Immediately switch to next model

                        # 429 or 5xx server errors: retry with dynamic Retry-After parsing
                        if e.code == 429 or e.code >= 500:
                            if attempt < max_retries:
                                sleep_time = backoff + random.uniform(0.1, 0.5)
                                if e.code == 429:
                                    # Check Retry-After and rate limit reset headers
                                    retry_after = e.headers.get("Retry-After") or e.headers.get("x-ratelimit-reset-requests") or e.headers.get("x-ratelimit-reset-tokens")
                                    if retry_after:
                                        try:
                                            # If timestamp in seconds, parse float
                                            val = float(str(retry_after).replace("s", "").strip())
                                            sleep_time = max(val + 0.5, 1.0)
                                        except ValueError:
                                            pass
                                logger.warning(
                                    f"Groq API ({model_name}) returned HTTP {e.code}. "
                                    f"Retrying in {sleep_time:.2f}s... (Attempt {attempt + 1}/{max_retries})"
                                )
                                time.sleep(sleep_time)
                                backoff *= 2.0
                                continue

                        logger.error(f"Groq API HTTP Error on model '{model_name}': {e.code} - {error_body}")
                        last_error = Exception(f"Groq API Error ({model_name}): {error_body}")
                        model_failed = True
                        break

                    except (urllib.error.URLError, TimeoutError) as e:
                        if attempt < max_retries:
                            sleep_time = backoff + random.uniform(0, 0.5)
                            logger.warning(
                                f"Groq API communication error on model '{model_name}': {e}. "
                                f"Retrying in {sleep_time:.2f}s... (Attempt {attempt + 1}/{max_retries})"
                            )
                            time.sleep(sleep_time)
                            backoff *= 2.0
                            continue
                        logger.error(f"Failed to communicate with Groq API on model '{model_name}' after {max_retries} retries: {e}")
                        last_error = e
                        model_failed = True
                        break
                    except Exception as e:
                        logger.error(f"Unexpected error calling Groq API on model '{model_name}': {e}")
                        last_error = e
                        model_failed = True
                        break

                if model_failed:
                    if model_idx + 1 < len(candidate_models):
                        next_model = candidate_models[model_idx + 1]
                        logger.info(f"Switching from model '{model_name}' to fallback model '{next_model}'...")
                    continue

            error_msg = f"All attempted LLM models failed: {attempted_models}. Last error: {last_error}"
            logger.error(error_msg)
            raise Exception(error_msg)

    @classmethod 
    def parse_resume(cls, resume_text: str) -> dict:
        """
        Sends the extracted resume text to the Groq API to convert it into a
        highly structured, standardized JSON format.
        """
        if not Config.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set.")

        # Allow up to 16,000 characters to prevent truncating projects, experience, and links
        resume_text = resume_text[:16000] if len(resume_text) > 16000 else resume_text

        system_prompt = (
            "You are an expert resume parsing engine. Convert the unstructured resume text into a structured JSON conforming to the schema below. "
            "Output ONLY the valid JSON object. Do not include any pre-text, post-text, explanation, or markdown.\n\n"
            "SCHEMA DEFINITION:\n"
            "{\n"
            '  "contact_info": { "name": str, "email": str or null, "phone": str or null, "location": str or null, "linkedin": str or null, "github": str or null, "portfolio": str or null },\n'
            '  "professional_summary": str or null,\n'
            '  "skills": { "languages": [], "frameworks": [], "libraries": [], "ai_ml": [], "genai": [], "databases": [], "cloud": [], "devops": [], "tools": [], "web": [], "soft_skills": [] },\n'
            '  "experience": [ { "company": str, "role": str, "employment_type": str, "department": str, "location": str, "start_date": str, "end_date": str, "technologies": [], "tools": [], "description": [], "responsibilities": [], "achievements": [] } ],\n'
            '  "projects": [ { "name": str, "description": str, "url": str or null, "repository": str or null, "technologies": [], "start_date": str, "end_date": str } ],\n'
            '  "education": [ { "institution": str, "degree": str, "specialization": str, "location": str, "graduation_year": str, "start_date": str, "end_date": str, "cgpa_or_percentage": str, "coursework": [], "honors": [] } ],\n'
            '  "certifications": [ { "name": str, "issuer": str, "issue_date": str, "expiry_date": str, "credential_id": str, "url": str or null } ],\n'
            '  "achievements": [], "publications": [ { "title": str, "publisher": str, "date": str, "url": str or null } ], "patents": [], "languages": [], "awards": [], "volunteer_experience": [], "leadership": [], "hackathons": [],\n'
            '  "coding_profiles": { "leetcode": str or null, "codeforces": str or null, "hackerrank": str or null, "codechef": str or null }, "interests": [], "extracurriculars": [],\n'
            '  "metadata": { "parsed_at": str, "parser_version": "2.0", "pages": int or null, "language": str, "confidence": float, "parsing_time_ms": int or null }\n'
            "}\n\n"
            "CRITICAL EXTRACTION & TRUTHFULNESS RULES:\n"
            "1. ONLY INCLUDE DATA PRESENT IN THE RESUME. NEVER hallucinate, guess, or invent false details, mock data, or placeholder URLs.\n"
            "2. PORTFOLIO & LINKS:\n"
            "   - If the candidate does NOT have a portfolio website explicitly written or linked in the resume, you MUST set `contact_info.portfolio` to null.\n"
            "   - NEVER fabricate dummy links (e.g. 'https://portfolio.com', 'https://janedoe.dev', or general tutorial/documentation links).\n"
            "   - Extract LinkedIn, GitHub, or coding profiles (LeetCode, HackerRank, CodeChef, Codeforces) ONLY if explicitly provided in the text/hyperlinks; otherwise set to null.\n"
            "3. STUDENT PROJECTS & ACADEMIC WORK:\n"
            "   - Extract projects that are actually stated in the text.\n"
            "   - If a project does not have a live URL or repository explicitly listed, set `url` to null and `repository` to null.\n"
            "4. WORK EXPERIENCE & EDUCATION:\n"
            "   - Extract exact companies, roles, dates, degrees, and institutions present in the resume.\n"
            "5. Return empty arrays [] for empty list fields, and null for absent string/object fields."
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

        # Compress both payloads to save tokens on free tier
        compact_resume = compress_resume_for_llm(resume_json)
        compact_jd = compress_jd_for_llm(jd_json)

        user_content = f"Candidate Resume:\n{json.dumps(compact_resume, indent=2)}\n\nJob Description:\n{json.dumps(compact_jd, indent=2)}"

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

