import os
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional

from src.database.connection import execute_db_with_retry, get_connection

logger = logging.getLogger(__name__)

@dataclass
class CandidateProfile:
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    summary: str = ""
    work_authorization: str = "Authorized to work in the US without sponsorship"
    requires_sponsorship: str = "No"
    desired_salary: str = "Negotiable"
    notice_period: str = "2 weeks"
    relocation: str = "Open to relocation"
    education: List[Dict[str, Any]] = field(default_factory=list)
    experience: List[Dict[str, Any]] = field(default_factory=list)
    projects: List[Dict[str, Any]] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    resume_path: Optional[str] = None
    resume_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



class CandidateProfileBuilder:
    @staticmethod
    def _split_name(full_name: str) -> tuple[str, str]:
        if not full_name:
            return "", ""
        parts = full_name.strip().split()
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], " ".join(parts[1:])

    @classmethod
    def from_parsed_json(cls, parsed_json: Dict[str, Any], resume_path: str = None, resume_id: str = None) -> CandidateProfile:
        if not parsed_json:
            parsed_json = {}

        contact = parsed_json.get("contact_info", {})
        if not isinstance(contact, dict):
            contact = {}

        full_name = contact.get("name") or contact.get("full_name") or ""
        first_name, last_name = cls._split_name(full_name)

        # Extract skills as unified flat list
        raw_skills = parsed_json.get("skills", {})
        flat_skills = []
        if isinstance(raw_skills, dict):
            for cat, val in raw_skills.items():
                if isinstance(val, list):
                    flat_skills.extend([str(s) for s in val if s])
                elif isinstance(val, str):
                    flat_skills.append(val)
        elif isinstance(raw_skills, list):
            flat_skills = [str(s) for s in raw_skills if s]

        # Extract links
        links = contact.get("links", {})
        if not isinstance(links, dict):
            links = {}

        linkedin = contact.get("linkedin") or links.get("linkedin") or ""
        github = contact.get("github") or links.get("github") or ""
        portfolio = contact.get("portfolio") or contact.get("website") or links.get("portfolio") or ""

        return CandidateProfile(
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=contact.get("email", ""),
            phone=contact.get("phone", ""),
            location=contact.get("location") or contact.get("address", ""),
            linkedin=linkedin,
            github=github,
            portfolio=portfolio,
            summary=parsed_json.get("professional_summary") or parsed_json.get("summary", ""),
            education=parsed_json.get("education", []) if isinstance(parsed_json.get("education"), list) else [],
            experience=parsed_json.get("experience", []) if isinstance(parsed_json.get("experience"), list) else [],
            projects=parsed_json.get("projects", []) if isinstance(parsed_json.get("projects"), list) else [],
            skills=list(dict.fromkeys(flat_skills)),
            resume_path=resume_path,
            resume_id=resume_id
        )

    @classmethod
    def from_resume_id(cls, resume_id: str) -> Optional[CandidateProfile]:
        """
        Loads candidate parsed_json and filename from database by resume_id
        and constructs a normalized CandidateProfile instance.
        """
        def query_resume(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT filename, parsed_json FROM resumes WHERE id = ?", (resume_id,))
            row = cursor.fetchone()
            if not row:
                return None
            filename, json_str = row
            try:
                data = json.loads(json_str) if isinstance(json_str, str) else json_str
            except Exception as e:
                logger.error(f"Failed to parse resume JSON for {resume_id}: {e}")
                data = {}
            return filename, data

        result = execute_db_with_retry(query_resume)
        if not result:
            return None

        filename, parsed_data = result
        # Standard resume path lookup inside data/resumes or data/
        resume_path = os.path.join("data", "resumes", filename)
        if not os.path.exists(resume_path):
            resume_path = os.path.join("data", filename)

        return cls.from_parsed_json(parsed_data, resume_path=resume_path, resume_id=resume_id)
