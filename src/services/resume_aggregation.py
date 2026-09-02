import re
from dataclasses import dataclass, field
from src.services.skills_normalization import SkillNormalizationService, _ALIAS_TO_SKILL
from src.services.skills_registry import Skill

@dataclass
class UnifiedSkill:
    skill_id: str
    display_name: str
    sources: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    confidence: float = 0.0
    occurrence_count: int = 0

@dataclass
class ResumeSkillProfile:
    skills: dict[str, UnifiedSkill] = field(default_factory=dict)

class ResumeSkillAggregationService:
    @classmethod
    def _split_into_sentences(cls, text: str) -> list[str]:
        """Helper to split block of text into individual sentences."""
        if not text:
            return []
        # Split on sentence boundaries: periods, exclamation/question marks followed by whitespace
        return [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]

    @classmethod
    def _add_skill(cls, profile: ResumeSkillProfile, skill_name: str, source: str, confidence: float, evidence_sentence: str = None):
        """Helper to resolve, deduplicate and append a skill to the profile."""
        if not skill_name:
            return
            
        skill_obj = SkillNormalizationService.resolve_canonical_skill(skill_name)
        if not skill_obj:
            return
            
        skill_id = skill_obj.skill_id
        
        if skill_id not in profile.skills:
            profile.skills[skill_id] = UnifiedSkill(
                skill_id=skill_id,
                display_name=skill_obj.display_name,
                sources=[],
                evidence=[],
                confidence=0.0,
                occurrence_count=0
            )
            
        item = profile.skills[skill_id]
        
        if source not in item.sources:
            item.sources.append(source)
            
        if evidence_sentence:
            clean_sentence = evidence_sentence.strip()
            if clean_sentence and clean_sentence not in item.evidence:
                item.evidence.append(clean_sentence)
                
        # Take the highest confidence score among all sources
        item.confidence = max(item.confidence, confidence)
        item.occurrence_count += 1

    @classmethod
    def build_profile(cls, resume_parsed: dict, raw_text: str = None) -> ResumeSkillProfile:
        """
        Aggregates technical skills from all structured and unstructured areas
        of the resume to build a Unified Resume Skill Profile.
        """
        profile = ResumeSkillProfile()
        if not resume_parsed:
            return profile

        # 1. Top-Level Skills Section (Confidence: 1.0)
        skills_obj = resume_parsed.get("skills", {})
        if isinstance(skills_obj, dict):
            for category, list_val in skills_obj.items():
                if isinstance(list_val, list):
                    for skill in list_val:
                        if isinstance(skill, str):
                            cls._add_skill(profile, skill, "Skills Section", 1.00)
                elif isinstance(list_val, str):
                    cls._add_skill(profile, list_val, "Skills Section", 1.00)
        elif isinstance(skills_obj, list):
            for item in skills_obj:
                if isinstance(item, str):
                    cls._add_skill(profile, item, "Skills Section", 1.00)

        # 2. Work Experience (Confidence: 0.95)
        experience = resume_parsed.get("experience", [])
        if isinstance(experience, list):
            for exp in experience:
                if not isinstance(exp, dict):
                    continue
                # Extract directly from structured arrays or strings
                techs = exp.get("technologies", [])
                if isinstance(techs, list):
                    for tech in techs:
                        if tech:
                            cls._add_skill(profile, str(tech), "Work Experience", 0.95)
                elif isinstance(techs, str):
                    cls._add_skill(profile, techs, "Work Experience", 0.95)

                tools = exp.get("tools", [])
                if isinstance(tools, list):
                    for tool in tools:
                        if tool:
                            cls._add_skill(profile, str(tool), "Work Experience", 0.95)
                elif isinstance(tools, str):
                    cls._add_skill(profile, tools, "Work Experience", 0.95)
                    
                # Scan job description/responsibilities for other skills
                desc = exp.get("description", [])
                if isinstance(desc, list):
                    desc_text = " ".join([str(x) for x in desc if x])
                elif isinstance(desc, str):
                    desc_text = desc
                else:
                    desc_text = ""

                resp = exp.get("responsibilities", [])
                if isinstance(resp, list):
                    resp_text = " ".join([str(x) for x in resp if x])
                elif isinstance(resp, str):
                    resp_text = resp
                else:
                    resp_text = ""

                combined_text = f"{desc_text} {resp_text}".strip()
                
                for sentence in cls._split_into_sentences(combined_text):
                    detected = SkillNormalizationService.extract_skills(sentence)
                    for skill in detected:
                        cls._add_skill(profile, skill, "Work Experience", 0.95, sentence)

        # 3. Projects (Confidence: 0.90)
        projects = resume_parsed.get("projects", [])
        if isinstance(projects, list):
            for proj in projects:
                if not isinstance(proj, dict):
                    continue
                # Extract directly from structured arrays or strings
                techs = proj.get("technologies", [])
                if isinstance(techs, list):
                    for tech in techs:
                        if tech:
                            cls._add_skill(profile, str(tech), "Projects", 0.90)
                elif isinstance(techs, str):
                    cls._add_skill(profile, techs, "Projects", 0.90)
                    
                # Scan project descriptions
                desc_val = proj.get("description", "")
                if isinstance(desc_val, list):
                    desc_text = " ".join([str(x) for x in desc_val if x])
                elif isinstance(desc_val, str):
                    desc_text = desc_val
                else:
                    desc_text = ""

                if desc_text:
                    for sentence in cls._split_into_sentences(desc_text):
                        detected = SkillNormalizationService.extract_skills(sentence)
                        for skill in detected:
                            cls._add_skill(profile, skill, "Projects", 0.90, sentence)

        # 4. Certifications (Confidence: 0.90)
        certifications = resume_parsed.get("certifications", [])
        if isinstance(certifications, list):
            for cert in certifications:
                cert_name = ""
                if isinstance(cert, dict):
                    cert_name = str(cert.get("name", ""))
                elif isinstance(cert, str):
                    cert_name = cert
                
                if cert_name:
                    detected = SkillNormalizationService.extract_skills(cert_name)
                    for skill in detected:
                        cls._add_skill(profile, skill, "Certifications", 0.90, f"Certification: {cert_name}")

        # 5. Education (Confidence: 0.80)
        education = resume_parsed.get("education", [])
        if isinstance(education, list):
            for edu in education:
                if not isinstance(edu, dict):
                    continue
                courses = edu.get("coursework", [])
                if isinstance(courses, list):
                    for course in courses:
                        if course:
                            detected = SkillNormalizationService.extract_skills(str(course))
                            for skill in detected:
                                cls._add_skill(profile, skill, "Education", 0.80, f"Coursework: {course}")
                elif isinstance(courses, str):
                    detected = SkillNormalizationService.extract_skills(courses)
                    for skill in detected:
                        cls._add_skill(profile, skill, "Education", 0.80, f"Coursework: {courses}")

        # 6. Raw Resume Text Fallback (Confidence: 0.60)
        if raw_text:
            for sentence in cls._split_into_sentences(raw_text):
                detected = SkillNormalizationService.extract_skills(sentence)
                for skill in detected:
                    cls._add_skill(profile, skill, "Raw Resume Text", 0.60, sentence)

        return profile
