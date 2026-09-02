import re
import logging
from typing import Dict, Any, List, Optional
from src.services.candidate_profile import CandidateProfile
from src.database.connection import execute_db_with_retry

logger = logging.getLogger(__name__)

class FieldMapper:
    """
    100% Deterministic & Database-Driven Form Field Mapper.
    Translates candidate profile fields and pre-stored database answers
    into candidate HTML input values for browser automation. Zero LLM calls.
    """
    
    FIELD_SELECTORS: Dict[str, List[str]] = {
        "full_name": [
            "input[name*='name' i]", "input[id*='name' i]", "input[autocomplete='name']",
            "input[aria-label*='full name' i]", "input[placeholder*='full name' i]"
        ],
        "first_name": [
            "input[name*='first_name' i]", "input[name*='firstname' i]", "input[id*='first_name' i]",
            "input[autocomplete='given-name']", "input[aria-label*='first name' i]", "input[placeholder*='first name' i]"
        ],
        "last_name": [
            "input[name*='last_name' i]", "input[name*='lastname' i]", "input[id*='last_name' i]",
            "input[autocomplete='family-name']", "input[aria-label*='last name' i]", "input[placeholder*='last name' i]"
        ],
        "email": [
            "input[type='email']", "input[name*='email' i]", "input[id*='email' i]",
            "input[autocomplete='email']", "input[placeholder*='email' i]"
        ],
        "phone": [
            "input[type='tel']", "input[name*='phone' i]", "input[id*='phone' i]",
            "input[name*='mobile' i]", "input[autocomplete='tel']", "input[placeholder*='phone' i]"
        ],
        "location": [
            "input[name*='location' i]", "input[name*='city' i]", "input[id*='location' i]",
            "input[aria-label*='location' i]", "input[placeholder*='city' i]"
        ],
        "linkedin": [
            "input[name*='linkedin' i]", "input[id*='linkedin' i]", "input[aria-label*='linkedin' i]",
            "input[placeholder*='linkedin' i]"
        ],
        "github": [
            "input[name*='github' i]", "input[id*='github' i]", "input[aria-label*='github' i]",
            "input[placeholder*='github' i]"
        ],
        "portfolio": [
            "input[name*='portfolio' i]", "input[name*='website' i]", "input[id*='portfolio' i]",
            "input[placeholder*='portfolio' i]", "input[placeholder*='website' i]"
        ],
        "resume_file": [
            "input[type='file'][name*='resume' i]", "input[type='file'][id*='resume' i]",
            "input[type='file'][accept*='pdf' i]", "input[type='file']"
        ],
        "summary": [
            "textarea[name*='cover' i]", "textarea[name*='summary' i]", "textarea[name*='note' i]",
            "textarea[id*='cover' i]", "textarea"
        ]
    }

    @classmethod
    def get_candidate_form_payload(cls, profile: CandidateProfile) -> Dict[str, Any]:
        """
        Extracts a clean, ready-to-fill form data dictionary from candidate profile.
        """
        if not profile:
            return {}

        project_summary = ""
        if profile.projects and len(profile.projects) > 0:
            p = profile.projects[0]
            p_name = p.get("name", "Key Project")
            p_desc = p.get("description") or p.get("summary") or ""
            project_summary = f"Project: {p_name} - {p_desc}".strip()

        return {
            "full_name": profile.full_name,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "location": profile.location,
            "linkedin": profile.linkedin,
            "github": profile.github,
            "portfolio": profile.portfolio,
            "summary": profile.summary or project_summary,
            "work_authorization": profile.work_authorization,
            "requires_sponsorship": profile.requires_sponsorship,
            "desired_salary": profile.desired_salary,
            "notice_period": profile.notice_period,
            "relocation": profile.relocation,
            "resume_file": profile.resume_path
        }

    @classmethod
    def match_input_to_field(cls, input_element_meta: Dict[str, str]) -> Optional[str]:
        """
        Heuristic matcher that takes an HTML element metadata (name, id, type, placeholder, label)
        and predicts which CandidateProfile field key it corresponds to.
        """
        elem_name = (input_element_meta.get("name") or "").lower()
        elem_id = (input_element_meta.get("id") or "").lower()
        elem_type = (input_element_meta.get("type") or "").lower()
        placeholder = (input_element_meta.get("placeholder") or "").lower()
        label = (input_element_meta.get("label") or "").lower()

        combined = f"{elem_name} {elem_id} {placeholder} {label}"

        if elem_type == "file" or "resume" in combined or "cv" in combined:
            return "resume_file"
        if elem_type == "email" or "email" in combined:
            return "email"
        if elem_type == "tel" or "phone" in combined or "mobile" in combined:
            return "phone"
        if "linkedin" in combined:
            return "linkedin"
        if "github" in combined:
            return "github"
        if "portfolio" in combined or "website" in combined:
            return "portfolio"
        if "first" in combined and "name" in combined:
            return "first_name"
        if "last" in combined and "name" in combined:
            return "last_name"
        if "full name" in combined or "name" in combined:
            return "full_name"
        if "location" in combined or "city" in combined or "address" in combined:
            return "location"
        if "cover" in combined or "summary" in combined or "note" in combined or "project" in combined:
            return "summary"
        if "authoriz" in combined or "work auth" in combined:
            return "work_authorization"
        if "sponsor" in combined:
            return "requires_sponsorship"
        if "salary" in combined or "compensation" in combined:
            return "desired_salary"
        if "notice" in combined:
            return "notice_period"
        if "relocat" in combined:
            return "relocation"

        return None

    @classmethod
    def get_database_answer(cls, field_label: str) -> Optional[str]:
        """
        Queries candidate_answers table in SQLite database to match custom application questions.
        Returns pre-stored answer string if pattern matches, else None.
        """
        if not field_label:
            return None

        clean_label = field_label.strip().lower()

        def query_answer(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT question_pattern, answer_value FROM candidate_answers")
            rows = cursor.fetchall()
            for pattern, answer in rows:
                try:
                    if re.search(pattern, clean_label, re.IGNORECASE):
                        return answer
                except Exception as e:
                    logger.warning(f"Invalid pattern in candidate_answers ({pattern}): {e}")
            return None

        try:
            return execute_db_with_retry(query_answer)
        except Exception as e:
            logger.error(f"[FieldMapper] Database answer lookup failed: {e}")
            return None
