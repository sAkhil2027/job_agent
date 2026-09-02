import re
import logging
from src.services.skills_normalization import SkillNormalizationService

logger = logging.getLogger(__name__)

# Basic dictionary for normalizing job titles deterministically
TITLE_NORMALIZATION_MAP = {
    "software engineer": "swe",
    "software developer": "swe",
    "swe": "swe",
    "developer": "swe",
    "qa engineer": "qa",
    "quality assurance": "qa",
    "machine learning engineer": "mle",
    "ml engineer": "mle",
    "data scientist": "data_scientist",
    "product manager": "pm",
    "project manager": "pm",
    "devops engineer": "devops",
    "systems administrator": "sysadmin",
    "database administrator": "dba",
    "db engineer": "dba"
}

# Basic dictionary for normalizing education deterministically
EDUCATION_NORMALIZATION_MAP = {
    "phd": "phd", "ph.d": "phd", "doctorate": "phd", "doctor": "phd",
    "master": "master", "msc": "master", "ms": "master", "mba": "master", "postgraduate": "master",
    "bachelor": "bachelor", "bsc": "bachelor", "bs": "bachelor", "ba": "bachelor", "degree": "bachelor", "undergraduate": "bachelor",
    "diploma": "diploma", "associate": "diploma"
}

class NormalizationService:
    @classmethod
    def normalize_title(cls, title: str) -> str:
        """Normalize job titles to canonical keys."""
        if not title:
            return "unknown"
        t = title.strip().lower()
        # Remove suffixes like Senior, Junior, Lead, Staff, Principal, etc.
        t = re.sub(r'\b(senior|junior|lead|staff|principal|associate|trainee|intern|mid|ii|iii|iv|v)\b', '', t)
        t = re.sub(r'[\s\-_]+', ' ', t).strip()
        
        # Check against lookup map
        for pattern, canonical in TITLE_NORMALIZATION_MAP.items():
            if pattern in t:
                return canonical
        return re.sub(r'\s+', '_', t)

    @classmethod
    def normalize_education(cls, degree: str) -> str:
        """Normalize education degree levels to canonical values."""
        if not degree:
            return "unknown"
        d = degree.strip().lower()
        for pattern, canonical in EDUCATION_NORMALIZATION_MAP.items():
            if pattern in d:
                return canonical
        return "other"

    @classmethod
    def normalize(cls, parsed_data: dict) -> dict:
        """
        Predictably normalize parsed Resume or JD data locally.
        Returns:
            {
                "skills": list[str] (canonical skill IDs),
                "experience": float (total experience years),
                "job_titles": list[str] (normalized role titles),
                "education": list[str] (normalized education levels),
                "certifications": list[str] (normalized certification names)
            }
        """
        # 1. Normalize Skills
        raw_skills = []
        
        # Handle Resume schema skills structure
        skills_obj = parsed_data.get("skills", {})
        if isinstance(skills_obj, dict):
            for cat, s_list in skills_obj.items():
                if isinstance(s_list, list):
                    raw_skills.extend(s_list)
        elif isinstance(skills_obj, list):
            raw_skills.extend(skills_obj)

        # Handle Job Description schema required/preferred skills
        req_skills_obj = parsed_data.get("required_skills", {})
        if isinstance(req_skills_obj, dict):
            for cat, s_list in req_skills_obj.items():
                if isinstance(s_list, list):
                    raw_skills.extend(s_list)
        elif isinstance(req_skills_obj, list):
            raw_skills.extend(req_skills_obj)
            
        pref_skills = parsed_data.get("preferred_skills", [])
        if isinstance(pref_skills, list):
            raw_skills.extend(pref_skills)

        # Resolve skill list to canonical skill IDs
        normalized_skills = []
        for s in raw_skills:
            if not s or not isinstance(s, str):
                continue
            canonical_skill = SkillNormalizationService.resolve_canonical_skill(s)
            if canonical_skill and canonical_skill.skill_id not in normalized_skills:
                normalized_skills.append(canonical_skill.skill_id)

        # 2. Normalize Experience
        experience_list = parsed_data.get("experience", [])
        normalized_titles = []
        total_exp_years = 0.0

        if isinstance(experience_list, list):
            # Resolve titles in experience
            for exp in experience_list:
                if isinstance(exp, dict) and exp.get("role"):
                    norm_role = cls.normalize_title(exp.get("role"))
                    if norm_role not in normalized_titles:
                        normalized_titles.append(norm_role)
            
            # Calculate cumulative experience years
            from src.services.scoring_pipeline import calculate_resume_experience_years
            total_exp_years = calculate_resume_experience_years(parsed_data)
        else:
            # For JDs, check required years of experience
            from src.services.scoring_pipeline import parse_required_experience
            total_exp_years = parse_required_experience(parsed_data)

        # 3. Normalize Education
        education_list = parsed_data.get("education", [])
        normalized_edu = []
        if isinstance(education_list, list):
            for edu in education_list:
                if isinstance(edu, dict) and edu.get("degree"):
                    norm_deg = cls.normalize_education(edu.get("degree"))
                    if norm_deg not in normalized_edu:
                        normalized_edu.append(norm_deg)
        else:
            # For JDs, read required education
            jd_edu = parsed_data.get("requirements", {}).get("education", "")
            if jd_edu:
                normalized_edu.append(cls.normalize_education(jd_edu))

        # 4. Normalize Certifications
        certs = parsed_data.get("certifications", [])
        normalized_certs = []
        if isinstance(certs, list):
            for cert in certs:
                if isinstance(cert, dict) and cert.get("name"):
                    c_name = cert.get("name").strip().lower()
                    c_clean = re.sub(r'[\s\-_]+', '_', c_name)
                    if c_clean not in normalized_certs:
                        normalized_certs.append(c_clean)
                elif isinstance(cert, str):
                    c_clean = re.sub(r'[\s\-_]+', cert.strip().lower())
                    if c_clean not in normalized_certs:
                        normalized_certs.append(c_clean)

        # 5. Extract additional titles (e.g. Target Job Title)
        target_title = parsed_data.get("title")
        if target_title:
            norm_target = cls.normalize_title(target_title)
            if norm_target not in normalized_titles:
                normalized_titles.append(norm_target)

        return {
            "skills": sorted(normalized_skills),
            "experience": [total_exp_years],
            "job_titles": sorted(normalized_titles),
            "education": sorted(normalized_edu),
            "certifications": sorted(normalized_certs)
        }
