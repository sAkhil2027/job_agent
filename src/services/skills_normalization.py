import re
import unicodedata
import difflib
import logging
from src.services.skills_registry import SKILL_REGISTRY, Skill

logger = logging.getLogger(__name__)

# Compile alias to Skill mapping
_ALIAS_TO_SKILL = {}
for skill in SKILL_REGISTRY:
    for alias in skill.aliases:
        _ALIAS_TO_SKILL[alias.lower()] = skill

class SkillNormalizationService:
    @classmethod
    def clean_text(cls, text: str) -> str:
        """Applies basic unicode normalization and cleanups."""
        if not text:
            return ""
        # Unicode decomposition/normalization
        text = unicodedata.normalize("NFKD", text)
        return text

    @classmethod
    def normalize_single_skill_string(cls, raw_skill: str) -> str:
        """Normalizes a single skill string to a lowercased canonical key format."""
        if not raw_skill:
            return ""
        # Lowercase, strip outer punctuation/whitespace
        s = raw_skill.strip().lower()
        # Normalize separators: replace dashes, slashes, spaces with underscores
        s = re.sub(r'[\s\-/]+', '_', s)
        # Strip other non-alphanumeric punctuation
        s = re.sub(r'[^\w+##]', '', s) # Keep pluses/sharps for C++/C#
        return s

    @classmethod
    def resolve_canonical_skill(cls, raw_skill: str) -> Skill:
        """
        Resolves a single skill text to a canonical Skill object,
        with fuzzy matching fallback.
        """
        if not raw_skill:
            return None
            
        s_clean = raw_skill.strip().lower()
        
        # 1. Exact alias match
        if s_clean in _ALIAS_TO_SKILL:
            return _ALIAS_TO_SKILL[s_clean]
            
        # 2. Fuzzy match fallback (high threshold)
        all_aliases = list(_ALIAS_TO_SKILL.keys())
        matches = difflib.get_close_matches(s_clean, all_aliases, n=1, cutoff=0.90)
        if matches:
            matched_alias = matches[0]
            logger.debug(f"Fuzzy matched '{raw_skill}' to alias '{matched_alias}'")
            return _ALIAS_TO_SKILL[matched_alias]
            
        # 3. Create custom/unregistered skill object
        normalized_id = cls.normalize_single_skill_string(raw_skill)
        if not normalized_id:
            return None
        return Skill(
            skill_id=normalized_id,
            canonical_name=raw_skill.strip(),
            display_name=raw_skill.strip(),
            aliases=[raw_skill.strip().lower()],
            category="custom"
        )

    @classmethod
    def validate_context_for_r(cls, jd_text: str, match_start: int, match_end: int) -> bool:
        """
        Validates whether the extracted "r" character represents the R programming language.
        Checks a window of text before and after the match for explicit phrases or proximity to other languages.
        """
        # Check surrounding window for explicit R phrases
        window_size = 20
        start = max(0, match_start - window_size)
        end = min(len(jd_text), match_end + window_size)
        context_window = jd_text[start:end].lower()
        
        # 1. Check for explicit bigrams/phrases in the window
        explicit_patterns = [
            r'\br\s+(programming|language|developer|script|coding|studio|statistics|code|tool)\b',
            r'\b(programming|language|developer|script|coding|statistics)\s+in\s+r\b',
            r'\br\-programming\b',
            r'\brstudio\b'
        ]
        for pattern in explicit_patterns:
            if re.search(pattern, context_window):
                return True
                
        # 2. Check if positioned in a list of other languages/technologies (within 15 chars)
        languages_nearby = ["python", "java", "c++", "c#", "sql", "javascript", "typescript", "scala", "julia", "matlab"]
        narrow_start = max(0, match_start - 15)
        narrow_end = min(len(jd_text), match_end + 15)
        narrow_window = jd_text[narrow_start:narrow_end].lower()
        
        for lang in languages_nearby:
            if lang in narrow_window:
                return True
                
        return False

    @classmethod
    def extract_skills(cls, text: str) -> list[str]:
        """
        Extracts canonical skill names present in the raw text.
        Applies context validation for single-character skills.
        """
        if not text:
            return []
            
        cleaned = cls.clean_text(text)
        cleaned_lower = cleaned.lower()
        extracted_skills = set()
        
        # Check registered aliases first
        for alias, skill in _ALIAS_TO_SKILL.items():
            escaped_alias = re.escape(alias)
            pattern = r'(?<![a-zA-Z0-9])' + escaped_alias + r'(?![a-zA-Z0-9])'
            
            for m in re.finditer(pattern, cleaned_lower):
                # Context validation for single-character skill "R"
                if alias == "r":
                    if cls.validate_context_for_r(cleaned, m.start(), m.end()):
                        extracted_skills.add(skill.canonical_name)
                else:
                    extracted_skills.add(skill.canonical_name)
                    
        return sorted(list(extracted_skills))

class SkillComparisonEngine:
    @classmethod
    def compare_skills(cls, resume_skills: list[str], jd_skills: list[str]) -> tuple[list[str], list[dict], list[str], list[str]]:
        """
        Compares lists of raw skill strings using canonical IDs and semantic relationships.
        Returns:
          - exact_matches (list[str]): Canonical display names of exact matches
          - soft_matches (list[dict]): List of dictionaries representing transferable matches
          - missing_skills (list[str]): Canonical display names of truly missing skills
          - extra_skills (list[str]): Canonical display names of additional resume skills
        """
        from src.services.skills_relationship import RELATIONSHIP_REGISTRY
        
        # Resolve all resume skills to canonical objects
        resume_objs = {}
        for rs in resume_skills:
            skill_obj = SkillNormalizationService.resolve_canonical_skill(rs)
            if skill_obj:
                resume_objs[skill_obj.skill_id] = skill_obj
                
        # Resolve all JD skills to canonical objects
        jd_objs = {}
        for js in jd_skills:
            skill_obj = SkillNormalizationService.resolve_canonical_skill(js)
            if skill_obj:
                jd_objs[skill_obj.skill_id] = skill_obj
                
        resume_ids = set(resume_objs.keys())
        jd_ids = set(jd_objs.keys())
        
        # 1. Exact Matches
        exact_ids = jd_ids.intersection(resume_ids)
        exact_matches = [resume_objs[sid].display_name for sid in exact_ids]
        
        # 2. Check for soft matches among the unmatched JD skills
        unmatched_jd_ids = jd_ids.difference(resume_ids)
        soft_matches = []
        missing_ids = set()
        
        for jid in unmatched_jd_ids:
            best_rel = None
            # Find the best relationship from any of the candidate's skills to the JD skill
            for rid in resume_ids:
                # Find if a directional relationship exists (rid -> jid)
                for rel in RELATIONSHIP_REGISTRY:
                    if rel.source_id == rid and rel.target_id == jid:
                        if best_rel is None or rel.transferability_score > best_rel.transferability_score:
                            best_rel = rel
                            best_rel_candidate_skill = resume_objs[rid].display_name
            
            if best_rel:
                soft_matches.append({
                    "required_skill": jd_objs[jid].display_name,
                    "candidate_skill": best_rel_candidate_skill,
                    "relationship_type": best_rel.relationship_type,
                    "transferability_score": best_rel.transferability_score,
                    "explanation": best_rel.description
                })
            else:
                missing_ids.add(jid)
                
        missing_skills = [jd_objs[sid].display_name for sid in missing_ids]
        
        # 3. Extra Resume Skills
        extra_ids = resume_ids.difference(jd_ids)
        extra_skills = [resume_objs[sid].display_name for sid in extra_ids]
        
        return sorted(exact_matches), soft_matches, sorted(missing_skills), sorted(extra_skills)
