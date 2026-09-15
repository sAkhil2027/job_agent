import json
import logging
import re
import uuid
import datetime
import time
from src.config import Config
from src.services.embedding import EmbeddingService
from src.services.capability_matcher import CapabilityMatchingEngine
from src.services.groq import GroqService
from src.database.connection import execute_db_with_retry
from src.services.cache import PARSER_VERSION, MATCH_VERSION, calculate_sha256

logger = logging.getLogger(__name__)

# Safe bounds for LLM score adjustments (±5 points)
MAX_LLM_ADJUSTMENT = Config.MAX_LLM_ADJUSTMENT
PIPELINE_VERSION = "v4"

def parse_date(date_str: str) -> datetime.date:
    """Safely parse date string into datetime.date object."""
    if not date_str:
        return None
    date_str_clean = date_str.strip().lower()
    if date_str_clean in ("present", "current", "now", "today", "active", "till date"):
        return datetime.date.today()
    
    match = re.search(r'(\d{4})[-\s/](\d{1,2})', date_str_clean)
    if match:
        try:
            return datetime.date(int(match.group(1)), int(match.group(2)), 1)
        except ValueError:
            pass
            
    match_year = re.search(r'(\d{4})', date_str_clean)
    if match_year:
        try:
            return datetime.date(int(match_year.group(1)), 1, 1)
        except ValueError:
            pass
            
    return None

def calculate_resume_experience_years(resume_parsed: dict) -> float:
    """Calculate cumulative years of experience from resume work history."""
    if not isinstance(resume_parsed, dict):
        return 0.0
        
    experience = resume_parsed.get("experience", [])
    if not experience or not isinstance(experience, list):
        return 0.0

    intervals = []
    for job in experience:
        if not isinstance(job, dict):
            continue
        start = parse_date(job.get("start_date"))
        end = parse_date(job.get("end_date"))
        if start and end:
            if start > end:
                start, end = end, start
            intervals.append((start, end))

    if not intervals:
        return 0.0

    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]
    for curr_start, curr_end in intervals[1:]:
        prev_start, prev_end = merged[-1]
        if curr_start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, curr_end))
        else:
            merged.append((curr_start, curr_end))

    total_months = sum((end.year - start.year) * 12 + (end.month - start.month) for start, end in merged)
    return round(max(0.0, total_months / 12.0), 1)


def parse_required_experience(jd_parsed: dict) -> float:
    """Extract required years of experience from parsed job description."""
    reqs = jd_parsed.get("requirements", {})
    if not reqs or not isinstance(reqs, dict):
        return 0.0
    exp_str = reqs.get("years_of_experience", "")
    if not exp_str:
        return 0.0
        
    num_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    for word, num in num_map.items():
        exp_str = re.sub(rf'\b{word}\b', str(num), exp_str, flags=re.IGNORECASE)
        
    match_range = re.search(r'(\d+)\s*-\s*(\d+)', exp_str)
    if match_range:
        return float(match_range.group(1))
        
    match_plus = re.search(r'(\d+)\s*\+', exp_str)
    if match_plus:
        return float(match_plus.group(1))
        
    match_num = re.search(r'(\d+)', exp_str)
    if match_num:
        return float(match_num.group(0))
        
    return 0.0

def calculate_experience_match(resume_parsed: dict, jd_parsed: dict) -> dict:
    """
    Evaluates experience matching beyond total-duration.
    Returns:
        {
            "required_years": float,
            "estimated_relevant_years": float,
            "score": float,
            "confidence": float
        }
    """
    required_years = parse_required_experience(jd_parsed)
    if required_years == 0.0:
        return {
            "required_years": 0.0,
            "estimated_relevant_years": 0.0,
            "score": 1.0,
            "confidence": 1.0
        }
        
    experience = resume_parsed.get("experience", [])
    if not experience or not isinstance(experience, list):
        return {
            "required_years": required_years,
            "estimated_relevant_years": 0.0,
            "score": 0.0,
            "confidence": 0.5
        }

    # Extract required skills & titles to determine job relevance
    req_skills = set()
    r_skills = jd_parsed.get("required_skills", {})
    if isinstance(r_skills, dict):
        for lst in r_skills.values():
            if isinstance(lst, list):
                req_skills.update(str(s).lower().strip() for s in lst if s)
    elif isinstance(r_skills, list):
        req_skills.update(str(s).lower().strip() for s in r_skills if s)

    jd_title_words = set(jd_parsed.get("title", "").lower().split())

    relevant_intervals = []
    has_missing_dates = False
    has_overlapping_dates = False
    total_parsed_jobs = 0
    valid_parsed_jobs = 0

    for job in experience:
        if not isinstance(job, dict):
            continue
        total_parsed_jobs += 1
        start_str = job.get("start_date")
        end_str = job.get("end_date")
        
        if not start_str or not end_str:
            has_missing_dates = True
            continue

        start = parse_date(start_str)
        end = parse_date(end_str)
        if not start or not end:
            has_missing_dates = True
            continue

        valid_parsed_jobs += 1
        if start > end:
            start, end = end, start

        role = str(job.get("role", "")).lower()
        d_val = job.get("description", [])
        r_val = job.get("responsibilities", [])
        d_list = [d_val] if isinstance(d_val, str) else (d_val if isinstance(d_val, list) else [])
        r_list = [r_val] if isinstance(r_val, str) else (r_val if isinstance(r_val, list) else [])
        desc_text = " ".join([str(x) for x in d_list + r_list if x]).lower()
        tech_val = job.get("technologies", [])
        tech_list = [tech_val] if isinstance(tech_val, str) else (tech_val if isinstance(tech_val, list) else [])
        techs = [str(t).lower() for t in tech_list if t]

        is_relevant = False
        role_words = set(role.split())
        if jd_title_words.intersection(role_words):
            is_relevant = True
        elif any(s in desc_text or s in techs for s in req_skills):
            is_relevant = True
        elif not req_skills:
            is_relevant = True

        if is_relevant:
            relevant_intervals.append((start, end))

    if not relevant_intervals:
        for job in experience:
            if isinstance(job, dict):
                start = parse_date(job.get("start_date"))
                end = parse_date(job.get("end_date"))
                if start and end:
                    relevant_intervals.append((start, end))
                    
    estimated_relevant_years = 0.0
    if relevant_intervals:
        relevant_intervals.sort(key=lambda x: x[0])
        merged = [relevant_intervals[0]]
        for current in relevant_intervals[1:]:
            prev_start, prev_end = merged[-1]
            curr_start, curr_end = current
            if curr_start <= prev_end:
                has_overlapping_dates = True
                merged[-1] = (prev_start, max(prev_end, curr_end))
            else:
                merged.append(current)
                
        total_months = 0
        for start, end in merged:
            months = (end.year - start.year) * 12 + (end.month - start.month)
            total_months += max(1, months)
        estimated_relevant_years = round(total_months / 12.0, 1)

    if estimated_relevant_years >= required_years:
        score = 1.0
    else:
        score = estimated_relevant_years / required_years

    confidence = 1.0
    if has_missing_dates:
        confidence -= 0.15
    if has_overlapping_dates:
        confidence -= 0.10
    if total_parsed_jobs > 0 and valid_parsed_jobs == 0:
        confidence -= 0.25
        
    confidence = round(max(0.1, min(1.0, confidence)), 2)

    return {
        "required_years": required_years,
        "estimated_relevant_years": estimated_relevant_years,
        "score": round(score, 2),
        "confidence": confidence
    }

def evaluate_education_match(resume_parsed: dict, jd_parsed: dict) -> float:
    """Evaluate education requirements match (returns 0.0 to 1.0)."""
    jd_req = jd_parsed.get("requirements", {}).get("education", "")
    if not jd_req:
        return 1.0
        
    jd_req_lower = jd_req.lower()
    req_level = 0
    if "phd" in jd_req_lower or "ph.d" in jd_req_lower or "doctorate" in jd_req_lower:
        req_level = 4
    elif "master" in jd_req_lower or "msc" in jd_req_lower or "ms" in jd_req_lower or "postgraduate" in jd_req_lower:
        req_level = 3
    elif "bachelor" in jd_req_lower or "bsc" in jd_req_lower or "bs" in jd_req_lower or "degree" in jd_req_lower or "graduate" in jd_req_lower:
        req_level = 2
    elif "diploma" in jd_req_lower or "associate" in jd_req_lower:
        req_level = 1
        
    candidate_education = resume_parsed.get("education", [])
    if not candidate_education or not isinstance(candidate_education, list):
        return 0.5 if req_level > 0 else 1.0
        
    max_cand_level = 0
    for edu in candidate_education:
        if not isinstance(edu, dict):
            continue
        degree = edu.get("degree", "").lower()
        specialization = edu.get("specialization", "").lower()
        text = f"{degree} {specialization}"
        
        if "phd" in text or "ph.d" in text or "doctorate" in text:
            max_cand_level = max(max_cand_level, 4)
        elif "master" in text or "msc" in text or "ms" in text or "postgraduate" in text:
            max_cand_level = max(max_cand_level, 3)
        elif "bachelor" in text or "bsc" in text or "bs" in text or "degree" in text or "graduate" in text:
            max_cand_level = max(max_cand_level, 2)
        elif "diploma" in text or "associate" in text:
            max_cand_level = max(max_cand_level, 1)
            
    if max_cand_level >= req_level:
        return 1.0
    elif max_cand_level == req_level - 1:
        return 0.7
    return 0.3

def calculate_confidence_score(matched_caps: list, missing_skills: list, exp_confidence: float, title_score: float, responsibility_score: float) -> float:
    """
    Calculate a deterministic confidence score based on signals:
    - Exact match coverage
    - Taxonomy match coverage
    - Borderline semantic matches
    - Experience confidence
    - Role/title confidence
    - Responsibility confidence
    """
    total_skills = len(matched_caps) + len(missing_skills)
    
    exact_count = sum(1 for m in matched_caps if m.get("match_type") == "exact")
    tax_count = sum(1 for m in matched_caps if m.get("match_type") == "taxonomy")
    borderline_count = sum(1 for m in matched_caps if m.get("is_borderline"))
    
    exact_coverage = exact_count / total_skills if total_skills > 0 else 1.0
    taxonomy_coverage = tax_count / total_skills if total_skills > 0 else 1.0
    
    borderline_penalty = min(0.25, borderline_count * 0.05)
    
    exact_signal = exact_coverage
    taxonomy_signal = (exact_count + tax_count) / total_skills if total_skills > 0 else 1.0
    exp_signal = exp_confidence
    title_signal = max(0.0, min(1.0, title_score))
    resp_signal = max(0.0, min(1.0, responsibility_score))
    
    w = Config.CONFIDENCE_WEIGHTS
    confidence = (
        w.get("exact_match_coverage", 0.30) * exact_signal +
        w.get("taxonomy_match_coverage", 0.20) * taxonomy_signal +
        w.get("experience_confidence", 0.20) * exp_signal +
        w.get("role_title_confidence", 0.15) * title_signal +
        w.get("responsibility_confidence", 0.15) * resp_signal
    )
    
    confidence -= borderline_penalty
    
    return round(max(0.1, min(1.0, confidence)), 2)

def should_route_to_llm(base_score_pct: float, confidence_val: float, matched_caps: list, missing_skills: list, cand_exp: float, req_exp: float, exp_confidence: float) -> bool:
    """
    Decides whether to route the match evaluation to the LLM.
    Uses configurable thresholds.
    """
    high_conf_thresh = Config.HIGH_CONFIDENCE_THRESHOLD
    low_score_thresh = Config.LOW_BASE_SCORE_THRESHOLD
    high_score_thresh = Config.HIGH_BASE_SCORE_THRESHOLD
    
    borderline_count = sum(1 for m in matched_caps if m.get("is_borderline"))
    transferable_count = sum(1 for m in matched_caps if m.get("match_type") == "transferable")
    
    # 1. High confidence and no ambiguities/borderline matches
    if confidence_val >= high_conf_thresh and transferable_count == 0 and borderline_count == 0:
        logger.info("Router: High confidence and zero ambiguities. Skipping LLM.")
        return False
        
    # 2. Extremely low base score and high confidence
    if base_score_pct <= low_score_thresh and confidence_val >= high_conf_thresh:
        logger.info("Router: Extremely low base score with high confidence. Skipping LLM.")
        return False
        
    # 3. Extremely high base score and high confidence
    if base_score_pct >= high_score_thresh and confidence_val >= high_conf_thresh:
        logger.info("Router: Extremely high base score with high confidence. Skipping LLM.")
        return False
        
    # 4. No meaningful unresolved contextual question
    has_experience_ambiguity = (exp_confidence < 0.80)
    has_transferable_ambiguity = any(m.get("score", 0.0) < 0.85 for m in matched_caps if m.get("match_type") == "transferable")
    
    if (borderline_count == 0 and 
        not has_experience_ambiguity and 
        not has_transferable_ambiguity and 
        cand_exp >= req_exp):
        logger.info("Router: No meaningful unresolved contextual questions. Skipping LLM.")
        return False
        
    logger.info("Router: Unresolved contextual questions or low confidence detected. Routing to LLM.")
    return True

def generate_deterministic_explanation(
    final_score: float,
    base_score_pct: float,
    adjustment: float,
    processing_mode: str,
    confidence_val: float,
    matched_caps: list[dict],
    missing_skills: list[str],
    req_names_lower: set[str],
    cand_exp: float,
    req_exp: float,
    responsibility_score: float,
    title_score: float,
    education_score: float,
    domain_relevance_score: float,
    score_breakdown: dict
) -> str:
    # 1. Matched Skills
    exact_matched = [m["requirement"] for m in matched_caps if m.get("match_type") == "exact"]
    
    # 2. Taxonomy Matches
    taxonomy_matches = []
    for m in matched_caps:
        if m.get("match_type") == "taxonomy":
            taxonomy_matches.append(f"{m.get('resume_evidence')} -> {m.get('requirement')}")
            
    # 3. Transferable Matches
    transferable_matches = []
    for m in matched_caps:
        if m.get("match_type") == "transferable":
            transferable_matches.append(f"{m.get('resume_evidence')} -> {m.get('requirement')}")
            
    # 4. Semantic Matches
    semantic_matches = []
    for m in matched_caps:
        if m.get("match_type") == "semantic":
            semantic_matches.append(f"\"{m.get('resume_evidence')}\" -> \"{m.get('requirement')}\" (Similarity: {m.get('similarity', 0.0):.2f})")

    # 5. Missing Skills
    from src.services.skills_normalization import SkillNormalizationService
    missing_req = []
    missing_pref = []
    for ms in missing_skills:
        ms_lower = ms.lower().strip()
        canonical_skill = SkillNormalizationService.resolve_canonical_skill(ms_lower)
        cid = canonical_skill.skill_id if canonical_skill else ms_lower
        
        is_req = False
        if ms_lower in req_names_lower:
            is_req = True
        else:
            for rs in req_names_lower:
                r_can = SkillNormalizationService.resolve_canonical_skill(rs)
                if r_can and r_can.skill_id == cid:
                    is_req = True
                    break
        if is_req:
            missing_req.append(ms)
        else:
            missing_pref.append(ms)

    lines = [
        f"Match Score: {int(final_score)}%",
        f"Base Score: {int(base_score_pct)}%",
        f"LLM Adjustment: {adjustment:+.1f}",
        f"Processing Mode: {processing_mode}",
        f"Confidence: {int(confidence_val * 100)}%",
        "",
        "Matched Skills:"
    ]
    if exact_matched:
        lines.extend([f"- {s}" for s in exact_matched])
    else:
        lines.append("- None")

    lines.append("\nTaxonomy Matches:")
    if taxonomy_matches:
        lines.extend([f"- {m}" for m in taxonomy_matches])
    else:
        lines.append("- None")

    lines.append("\nTransferable Matches:")
    if transferable_matches:
        lines.extend([f"- {m}" for m in transferable_matches])
    else:
        lines.append("- None")

    lines.append("\nSemantic Matches:")
    if semantic_matches:
        lines.extend([f"- {m}" for m in semantic_matches])
    else:
        lines.append("- None")

    lines.append("\nMissing Required Skills:")
    if missing_req:
        lines.extend([f"- {s}" for s in missing_req])
    else:
        lines.append("- None")

    lines.append("\nMissing Preferred Skills:")
    if missing_pref:
        lines.extend([f"- {s}" for s in missing_pref])
    else:
        lines.append("- None")

    lines.append("\nExperience:")
    lines.append(f"- Required: {req_exp} years")
    lines.append(f"- Estimated Relevant Experience: {cand_exp} years")
    if cand_exp < req_exp:
        lines.append(f"- Experience Gap: {round(req_exp - cand_exp, 1)} years")
    else:
        lines.append("- Experience Gap: None")

    lines.append(f"\nRole/Title Match Score: {int(title_score * 100)}%")
    lines.append(f"Education/Certification Match Score: {int(education_score * 100)}%")
    
    lines.append("\nScore Breakdown:")
    for k, v in score_breakdown.items():
        if k not in ("experience_confidence", "candidate_experience_years", "required_experience_years"):
            display_name = k.replace("_", " ").title()
            lines.append(f"- {display_name}: {v}%")

    return "\n".join(lines)

class MatchResult:
    def __init__(self, match_score: float, base_score: float, llm_adjustment: float, matched_skills: list[str], missing_skills: list[str], reasoning: str, matched_capabilities: list[dict], confidence: float, is_llm_used: bool, score_breakdown: dict = None, processing_mode: str = "deterministic",
                 exact_matches: list = None, taxonomy_matches: list = None, transferable_matches: list = None, semantic_matches: list = None,
                 missing_required_skills: list = None, missing_preferred_skills: list = None, experience_analysis: dict = None, explanation: dict = None, cache: dict = None, application_decision: dict = None):
        self.match_score = match_score
        self.base_score = base_score
        self.llm_adjustment = llm_adjustment
        self.matched_skills = matched_skills
        self.missing_skills = missing_skills
        self.reasoning = reasoning
        self.matched_capabilities = matched_capabilities
        self.confidence = confidence
        self.is_llm_used = is_llm_used
        self.score_breakdown = score_breakdown if score_breakdown else {}
        self.processing_mode = processing_mode
        self.exact_matches = exact_matches if exact_matches else []
        self.taxonomy_matches = taxonomy_matches if taxonomy_matches else []
        self.transferable_matches = transferable_matches if transferable_matches else []
        self.semantic_matches = semantic_matches if semantic_matches else []
        self.missing_required_skills = missing_required_skills if missing_required_skills else []
        self.missing_preferred_skills = missing_preferred_skills if missing_preferred_skills else []
        self.experience_analysis = experience_analysis if experience_analysis else {}
        self.explanation = explanation if explanation else {}
        self.cache = cache if cache else {"local_hit": False, "llm_hit": False}
        self.application_decision = application_decision if application_decision else {}

    def to_dict(self) -> dict:
        return {
            "match_score": self.match_score,
            "final_score": round(self.match_score * 100.0, 1),
            "base_score": self.base_score,
            "llm_adjustment": self.llm_adjustment,
            "matched_skills": self.matched_skills,
            "missing_skills": self.missing_skills,
            "reasoning": self.reasoning,
            "matched_capabilities": self.matched_capabilities,
            "confidence": self.confidence,
            "is_llm_used": self.is_llm_used,
            "score_breakdown": self.score_breakdown,
            "processing_mode": self.processing_mode,
            "exact_matches": self.exact_matches,
            "taxonomy_matches": self.taxonomy_matches,
            "transferable_matches": self.transferable_matches,
            "semantic_matches": self.semantic_matches,
            "missing_required_skills": self.missing_required_skills,
            "missing_preferred_skills": self.missing_preferred_skills,
            "experience_analysis": self.experience_analysis,
            "explanation": self.explanation,
            "cache": self.cache,
            "application_decision": self.application_decision
        }

class ScoringPipeline:
    @classmethod
    def match(cls, resume: dict, jd: dict, options: dict = None) -> MatchResult:
        """
        Unified entrypoint orchestrating Resume ↔ JD matching.
        """
        if options is None:
            options = {}

        resume_id = options.get("resume_id")
        job_id = options.get("job_id")
        resume_raw_text = options.get("resume_raw_text", "")
        jd_raw_text = options.get("jd_raw_text", "")
        use_llm = options.get("use_llm", False)

        resume_hash = options.get("resume_hash") or calculate_sha256(resume_raw_text or json.dumps(resume))
        jd_hash = options.get("jd_hash") or calculate_sha256(jd_raw_text or json.dumps(jd))

        # Generate Level 1 and Level 2 Cache Keys
        level1_raw = f"{resume_hash}:{jd_hash}:{Config.PARSER_VERSION}:{Config.MATCHER_VERSION}:{Config.TAXONOMY_VERSION}:{Config.EMBEDDING_MODEL_VERSION}:{Config.SCORING_CONFIG_VERSION}"
        level1_key = calculate_sha256(level1_raw)

        level2_raw = f"{resume_hash}:{jd_hash}:{Config.MATCHER_VERSION}:{Config.PROMPT_VERSION}:{Config.LLM_MODEL}:{Config.LLM_CONTEXT_SCHEMA_VERSION}"
        level2_key = calculate_sha256(level2_raw)

        # Observability Latency Trackers
        local_latency = 0.0
        embedding_latency = 0.0
        llm_latency = 0.0
        llm_failed = False
        local_start = 0.0

        # 1. Level 1 Cache Lookup (Local Match Cache)
        local_hit = False
        llm_hit = False
        matched_caps = []
        missing_skills = []
        base_score_pct = 0.0
        score_breakdown = {}
        confidence_val = 0.0
        reasoning = ""
        soft_matches = []
        exact_matches = []
        cand_exp = 0.0
        req_exp = 0.0

        if resume_id and job_id:
            def check_level1_cache(conn):
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT match_score, matched_skills, missing_skills, reasoning, soft_matches, matched_capabilities, score_breakdown
                    FROM matches
                    WHERE level1_key = ?
                """, (level1_key,))
                return cursor.fetchone()

            try:
                row_match = execute_db_with_retry(check_level1_cache)
                if row_match:
                    logger.info("Level 1 Cache Hit (Local Match Cache). Reusing local match data.")
                    base_score_pct = round(row_match[0] * 100.0, 1)
                    missing_skills = json.loads(row_match[2]) if row_match[2] else []
                    reasoning = row_match[3]
                    soft_matches = json.loads(row_match[4]) if row_match[4] else []
                    matched_caps = json.loads(row_match[5]) if row_match[5] else []
                    score_breakdown = json.loads(row_match[6]) if row_match[6] else {}
                    
                    exact_matches = [m["requirement"] for m in matched_caps if m.get("match_type") == "exact"]
                    
                    exp_confidence = score_breakdown.get("experience_confidence", 1.0)
                    title_score = score_breakdown.get("role_title", 0.0) / 100.0
                    responsibility_score = score_breakdown.get("responsibilities", 0.0) / 100.0
                    cand_exp = score_breakdown.get("candidate_experience_years", 0.0)
                    req_exp = score_breakdown.get("required_experience_years", 0.0)
                    
                    confidence_val = calculate_confidence_score(
                        matched_caps=matched_caps,
                        missing_skills=missing_skills,
                        exp_confidence=exp_confidence,
                        title_score=title_score,
                        responsibility_score=responsibility_score
                    )
                    local_hit = True
            except Exception as cache_err:
                logger.error(f"Level 1 Cache lookup failed (non-critical): {cache_err}")

        if not local_hit:
            local_start = time.time()
            # 1.5 Local Normalization Layer (zero tokens consumed)
            from src.services.normalization import NormalizationService
            normalized_resume = NormalizationService.normalize(resume)
            normalized_jd = NormalizationService.normalize(jd)
            logger.info(f"Normalized Resume Profile: {json.dumps(normalized_resume)}")
            logger.info(f"Normalized Job Requirements: {json.dumps(normalized_jd)}")

            # 2. Local Matching Engine (use_llm=False)
            local_match_res = CapabilityMatchingEngine.match_capabilities(
                resume_parsed=resume,
                jd_parsed=jd,
                resume_raw_text=resume_raw_text,
                jd_raw_text=jd_raw_text,
                use_llm=False
            )
            
            matched_caps = local_match_res.get("matched_capabilities", [])
            missing_skills = local_match_res.get("missing_skills", [])
            
            # Separate required and preferred skills
            req_matched = []
            pref_matched = []
            req_missing = []
            pref_missing = []
            
            req_names_lower = set()
            r_skills = jd.get("required_skills", {})
            if isinstance(r_skills, dict):
                for lst in r_skills.values():
                    if isinstance(lst, list):
                        req_names_lower.update(str(s).lower().strip() for s in lst if s)
            elif isinstance(r_skills, list):
                req_names_lower.update(str(s).lower().strip() for s in r_skills if s)
                
            from src.services.skills_normalization import SkillNormalizationService
            for m in matched_caps:
                req_name = m.get("requirement", "").lower().strip()
                canonical_skill = SkillNormalizationService.resolve_canonical_skill(req_name)
                cid = canonical_skill.skill_id if canonical_skill else req_name
                
                is_req = False
                if req_name in req_names_lower:
                    is_req = True
                else:
                    for rs in req_names_lower:
                        r_can = SkillNormalizationService.resolve_canonical_skill(rs)
                        if r_can and r_can.skill_id == cid:
                            is_req = True
                            break
                if is_req:
                    req_matched.append(m)
                else:
                    pref_matched.append(m)
                    
            for ms in missing_skills:
                ms_lower = ms.lower().strip()
                canonical_skill = SkillNormalizationService.resolve_canonical_skill(ms_lower)
                cid = canonical_skill.skill_id if canonical_skill else ms_lower
                
                is_req = False
                if ms_lower in req_names_lower:
                    is_req = True
                else:
                    for rs in req_names_lower:
                        r_can = SkillNormalizationService.resolve_canonical_skill(rs)
                        if r_can and r_can.skill_id == cid:
                            is_req = True
                            break
                if is_req:
                    req_missing.append(ms)
                else:
                    pref_missing.append(ms)
                    
            total_req_skills = len(req_matched) + len(req_missing)
            required_skills_score = 1.0
            if total_req_skills > 0:
                required_skills_score = sum(m.get("score", 0.0) for m in req_matched) / total_req_skills
                
            total_pref_skills = len(pref_matched) + len(pref_missing)
            preferred_skills_score = 1.0
            if total_pref_skills > 0:
                preferred_skills_score = sum(m.get("score", 0.0) for m in pref_matched) / total_pref_skills
                
            exp_match = calculate_experience_match(resume, jd)
            cand_exp = exp_match["estimated_relevant_years"]
            req_exp = exp_match["required_years"]
            experience_score = exp_match["score"]
            exp_confidence = exp_match["confidence"]
                
            education_score = evaluate_education_match(resume, jd)

            jd_responsibilities = jd.get("responsibilities", [])
            candidate_jobs = resume.get("experience", [])
            responsibility_score = 1.0
            
            if jd_responsibilities and candidate_jobs:
                resp_similarities = []
                cand_exp_texts = []
                for job in candidate_jobs:
                    if isinstance(job, dict):
                        desc_list = job.get("description", [])
                        if isinstance(desc_list, list):
                            cand_exp_texts.extend([str(d) for d in desc_list if d])
                        resp_list = job.get("responsibilities", [])
                        if isinstance(resp_list, list):
                            cand_exp_texts.extend([str(r) for r in resp_list if r])
                
                if cand_exp_texts:
                    try:
                        emb_start = time.time()
                        jd_resp_embs = EmbeddingService.generate_embeddings(jd_responsibilities[:3])
                        cand_exp_embs = EmbeddingService.generate_embeddings(cand_exp_texts[:8])
                        embedding_latency += time.time() - emb_start
                        
                        for r_emb in jd_resp_embs:
                            max_sim = 0.0
                            for c_emb in cand_exp_embs:
                                sim = EmbeddingService.compute_similarity(r_emb, c_emb)
                                if sim > max_sim:
                                    max_sim = sim
                            resp_similarities.append(max_sim)
                        
                        if resp_similarities:
                            responsibility_score = sum(resp_similarities) / len(resp_similarities)
                    except Exception as e:
                        logger.error(f"Failed responsibility matching: {e}")
                        responsibility_score = 0.5

            jd_title = jd.get("title", "")
            title_score = 0.5
            if jd_title and candidate_jobs:
                try:
                    emb_start = time.time()
                    jd_title_emb = EmbeddingService.generate_embedding(jd_title)
                    max_title_sim = 0.0
                    for job in candidate_jobs:
                        if isinstance(job, dict) and job.get("role"):
                            role_emb = EmbeddingService.generate_embedding(job.get("role"))
                            sim = EmbeddingService.compute_similarity(jd_title_emb, role_emb)
                            if sim > max_title_sim:
                                max_title_sim = sim
                    title_score = max_title_sim
                    embedding_latency += time.time() - emb_start
                except Exception as e:
                    logger.error(f"Failed title matching: {e}")
                    title_score = 0.5
            elif not jd_title:
                title_score = 1.0

            # Domain relevance calculation
            domain_relevance_score = 1.0
            jd_company = jd.get("company", "").lower()
            jd_description = jd_raw_text.lower() if jd_raw_text else ""
            domains = ["healthcare", "finance", "medical", "banking", "retail", "ecommerce", "automotive", "insurance", "telecom", "security", "saas"]
            matched_domains = []
            for d in domains:
                if d in jd_description or d in jd_company:
                    exp_texts = []
                    for job in resume.get("experience", []):
                        if isinstance(job, dict):
                            d_v = job.get("description", [])
                            r_v = job.get("responsibilities", [])
                            d_l = [d_v] if isinstance(d_v, str) else (d_v if isinstance(d_v, list) else [])
                            r_l = [r_v] if isinstance(r_v, str) else (r_v if isinstance(r_v, list) else [])
                            exp_texts.append(" ".join([str(x) for x in d_l + r_l if x]))
                    cand_experience_text = " ".join(exp_texts).lower()
                    if d in cand_experience_text:
                        matched_domains.append(d)
            target_domains_count = sum(1 for d in domains if d in jd_description or d in jd_company)
            if target_domains_count > 0:
                domain_relevance_score = len(matched_domains) / target_domains_count

            # 3. Deterministic Base Scoring Engine
            w = Config.SCORING_WEIGHTS
            base_score = (
                w.get("required_skills", 0.35) * required_skills_score +
                w.get("preferred_skills", 0.10) * preferred_skills_score +
                w.get("experience", 0.20) * experience_score +
                w.get("responsibilities", 0.15) * responsibility_score +
                w.get("role_title", 0.10) * title_score +
                w.get("education_certifications", 0.05) * education_score +
                w.get("domain_relevance", 0.05) * domain_relevance_score
            )
            base_score_pct = round(base_score * 100.0, 1)
            
            # 4. Confidence Engine
            exact_matches = [m["requirement"] for m in matched_caps if m["match_type"] == "exact"]
            soft_matches = [m for m in matched_caps if m["match_type"] in ("taxonomy", "transferable", "semantic")]
            
            confidence_val = calculate_confidence_score(
                matched_caps=matched_caps,
                missing_skills=missing_skills,
                exp_confidence=exp_confidence,
                title_score=title_score,
                responsibility_score=responsibility_score
            )
            
            skills_matched_str = ", ".join(exact_matches[:4]) if exact_matches else "None"
            skills_missing_str = ", ".join(missing_skills[:4]) if missing_skills else "None"
            soft_matched_str = ", ".join([sm["requirement"] for sm in soft_matches[:3]]) if soft_matches else "None"
            
            reasoning = (
                f"### Deterministic Match Profile:\n"
                f"* **Exact Skills Matched**: {skills_matched_str}\n"
                f"* **Soft/Concept Skills Matched**: {soft_matched_str}\n"
                f"* **Experience Match**: Candidate has {cand_exp} years vs required {req_exp} years.\n"
                f"* **Gaps Identified**: {skills_missing_str}\n"
                f"* **Base Matching Confidence**: {int(confidence_val * 100)}%\n"
            )

            score_breakdown = {
                "required_skills": round(required_skills_score * 100.0, 1),
                "preferred_skills": round(preferred_skills_score * 100.0, 1),
                "experience": round(experience_score * 100.0, 1),
                "responsibilities": round(responsibility_score * 100.0, 1),
                "role_title": round(title_score * 100.0, 1),
                "education_certifications": round(education_score * 100.0, 1),
                "domain_relevance": round(domain_relevance_score * 100.0, 1),
                "experience_confidence": exp_confidence,
                "candidate_experience_years": cand_exp,
                "required_experience_years": req_exp
            }

            # Save to Level 1 Cache (Local Match Cache)
            if resume_id and job_id:
                try:
                    def save_level1_cache(conn):
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM matches WHERE resume_id = ? AND job_id = ?", (resume_id, job_id))
                        match_exists = cursor.fetchone()
                        
                        sim_score_val = round(base_score_pct / 100.0, 4)
                        matched_skills_serialized = json.dumps(exact_matches + [sm["requirement"] for sm in soft_matches])
                        if not match_exists:
                            match_id = str(uuid.uuid4())
                            cursor.execute("""
                                INSERT INTO matches (id, resume_id, job_id, match_score, matched_skills, missing_skills, reasoning, match_version, resume_hash, soft_matches, matched_capabilities, score_breakdown, level1_key)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (match_id, resume_id, job_id, sim_score_val, matched_skills_serialized, json.dumps(missing_skills), reasoning, MATCH_VERSION, resume_hash, json.dumps(soft_matches), json.dumps(matched_caps), json.dumps(score_breakdown), level1_key))
                        else:
                            cursor.execute("""
                                UPDATE matches 
                                SET match_score = ?, matched_skills = ?, missing_skills = ?, reasoning = ?, match_version = ?, resume_hash = ?, soft_matches = ?, matched_capabilities = ?, score_breakdown = ?, level1_key = ?
                                WHERE resume_id = ? AND job_id = ?
                            """, (sim_score_val, matched_skills_serialized, json.dumps(missing_skills), reasoning, MATCH_VERSION, resume_hash, json.dumps(soft_matches), json.dumps(matched_caps), json.dumps(score_breakdown), level1_key, resume_id, job_id))
                        conn.commit()
                    execute_db_with_retry(save_level1_cache)
                except Exception as db_err:
                    logger.error(f"Failed to write Level 1 cache: {db_err}")

            local_latency = time.time() - local_start

        # 5. Confidence-Aware LLM Router
        is_llm_active = False
        if use_llm:
            is_llm_active = should_route_to_llm(
                base_score_pct=base_score_pct,
                confidence_val=confidence_val,
                matched_caps=matched_caps,
                missing_skills=missing_skills,
                cand_exp=cand_exp,
                req_exp=req_exp,
                exp_confidence=exp_confidence
            )
                
        processing_mode = "hybrid" if is_llm_active else "deterministic"
        final_score = base_score_pct
        adjustment = 0.0
        
        # 7. Compact Context Builder & LLM Adjustment
        if is_llm_active:
            # Check Level 2 Cache (LLM Context Cache)
            llm_hit = False
            if resume_id and job_id:
                def check_level2_cache(conn):
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT llm_adjustment, reasoning
                        FROM llm_cache
                        WHERE cache_key = ?
                    """, (level2_key,))
                    return cursor.fetchone()

                try:
                    row_llm = execute_db_with_retry(check_level2_cache)
                    if row_llm:
                        logger.info("Level 2 Cache Hit (LLM Context Cache). Reusing LLM evaluation.")
                        adjustment = row_llm[0]
                        reasoning = row_llm[1]
                        llm_hit = True
                except Exception as cache_err:
                    logger.error(f"Level 2 Cache lookup failed (non-critical): {cache_err}")

            if not llm_hit:
                try:
                    # Build a compact, token-optimized context focusing only on unresolved or ambiguous evidence
                    ambiguous_matches = []
                    transferable_matches = []
                    for m in matched_caps:
                        m_type = m.get("match_type")
                        is_borderline = m.get("is_borderline", False)
                        score = m.get("score", 0.0)
                        
                        if m_type == "transferable":
                            transferable_matches.append({
                                "required": m.get("requirement"),
                                "resume_evidence": m.get("resume_evidence"),
                                "local_score": round(score, 2)
                            })
                        elif is_borderline or (m_type in ("semantic", "taxonomy") and score < 0.95):
                            ambiguous_matches.append({
                                "requirement": m.get("requirement"),
                                "resume_evidence": m.get("resume_evidence"),
                                "local_similarity": round(m.get("similarity", score), 2)
                            })

                    experience_gap = None
                    if cand_exp < req_exp:
                        experience_gap = {
                            "required_years": req_exp,
                            "estimated_candidate_years": cand_exp
                        }

                    responsibility_ambiguity = None
                    if responsibility_score < 0.85 and jd_responsibilities:
                        responsibility_ambiguity = {
                            "score": round(responsibility_score, 2),
                            "required_responsibilities": jd_responsibilities[:3]
                        }

                    condensed_context = {
                        "base_score": round(base_score_pct, 1),
                        "ambiguous_matches": ambiguous_matches,
                        "transferable_matches": transferable_matches,
                    }
                    if experience_gap:
                        condensed_context["experience_gap"] = experience_gap
                    if responsibility_ambiguity:
                        condensed_context["responsibility_ambiguity"] = responsibility_ambiguity
                    
                    system_prompt = (
                        "You are a technical recruiting assistant. Analyze the candidate fit based ONLY on the provided Gaps and Soft Matches data.\n"
                        "Output strictly valid JSON conforming to the requested schema. No pre-text, post-text, or markdown."
                    )
                    
                    prompt = (
                        f"Evaluate if the candidate's experience and soft-matched skills offset their gaps.\n"
                        f"Context Data:\n{json.dumps(condensed_context)}\n\n"
                        f"Respond strictly in JSON format matching this schema:\n"
                        f"{{\n"
                        f'  "context_fit": float,\n'
                        f'  "transferable_skill_fit": float,\n'
                        f'  "responsibility_fit": float,\n'
                        f'  "experience_quality": float,\n'
                        f'  "confidence": float,\n'
                        f'  "reasoning": "string"\n'
                        f"}}\n"
                        f"All floats must be between 0.0 and 1.0. Keep reasoning concise (max 2 sentences)."
                    )
                    
                    llm_start = time.time()
                    try:
                        res_str = GroqService.completion(prompt, system_prompt, response_json=True)
                        llm_latency += time.time() - llm_start
                    except Exception as e:
                        llm_latency += time.time() - llm_start
                        llm_failed = True
                        raise e
                    llm_res = json.loads(res_str)
                    
                    # Validate required fields
                    required_fields = ["context_fit", "transferable_skill_fit", "responsibility_fit", "experience_quality", "confidence"]
                    for field in required_fields:
                        if field not in llm_res:
                            raise ValueError(f"Missing required field in LLM response: {field}")
                    
                    # Validate and clamp numeric ranges (0.0 to 1.0)
                    context_fit = max(0.0, min(1.0, float(llm_res["context_fit"])))
                    transferable_fit = max(0.0, min(1.0, float(llm_res["transferable_skill_fit"])))
                    resp_fit = max(0.0, min(1.0, float(llm_res["responsibility_fit"])))
                    exp_quality = max(0.0, min(1.0, float(llm_res["experience_quality"])))
                    llm_conf = max(0.0, min(1.0, float(llm_res["confidence"])))
                    
                    # Compute deterministic score adjustment in code
                    cf_delta = (context_fit - 0.70) * 2.0
                    tf_delta = (transferable_fit - 0.70) * 1.0
                    rf_delta = (resp_fit - 0.70) * 1.0
                    eq_delta = (exp_quality - 0.70) * 1.0
                    
                    adjustment_raw = (cf_delta + tf_delta + rf_delta + eq_delta) * llm_conf * 2.5
                    adjustment = max(-MAX_LLM_ADJUSTMENT, min(MAX_LLM_ADJUSTMENT, adjustment_raw))
                    
                    reasoning += (
                        f"\n### Detailed AI Analysis:\n"
                        f"{llm_res.get('reasoning', '')}\n"
                        f"*LLM Score Adjustment: {round(adjustment, 2)} points*"
                    )
                    
                    # Store Level 2 Cache
                    if resume_id and job_id:
                        try:
                            def save_level2_cache(conn):
                                cursor = conn.cursor()
                                cursor.execute("""
                                    INSERT OR REPLACE INTO llm_cache (id, cache_key, llm_adjustment, reasoning, llm_model)
                                    VALUES (?, ?, ?, ?, ?)
                                """, (str(uuid.uuid4()), level2_key, adjustment, reasoning, Config.LLM_MODEL))
                                conn.commit()
                            execute_db_with_retry(save_level2_cache)
                        except Exception as db_err:
                            logger.error(f"Failed to write Level 2 cache: {db_err}")
                            
                except Exception as e:
                    logger.error(f"LLM adjustment failed: {e}")
                    reasoning += f"\n*(Detailed AI Analysis unavailable: {type(e).__name__})*"
                    adjustment = 0.0
                    processing_mode = "deterministic_fallback"

        final_score = max(0.0, min(100.0, base_score_pct + adjustment))

        # Reconstruct req_names_lower for explanation formatting
        req_names_lower = set()
        r_skills = jd.get("required_skills", {})
        if isinstance(r_skills, dict):
            for lst in r_skills.values():
                if isinstance(lst, list):
                    req_names_lower.update(str(s).lower().strip() for s in lst if s)
        elif isinstance(r_skills, list):
            req_names_lower.update(str(s).lower().strip() for s in r_skills if s)

        # Generate standard match explanation locally (consumes zero LLM tokens)
        reasoning = generate_deterministic_explanation(
            final_score=final_score,
            base_score_pct=base_score_pct,
            adjustment=adjustment,
            processing_mode=processing_mode,
            confidence_val=confidence_val,
            matched_caps=matched_caps,
            missing_skills=missing_skills,
            req_names_lower=req_names_lower,
            cand_exp=cand_exp,
            req_exp=req_exp,
            responsibility_score=score_breakdown.get("responsibilities", 100.0) / 100.0,
            title_score=score_breakdown.get("role_title", 100.0) / 100.0,
            education_score=score_breakdown.get("education_certifications", 100.0) / 100.0,
            domain_relevance_score=score_breakdown.get("domain_relevance", 100.0) / 100.0,
            score_breakdown=score_breakdown
        )

        # Update the matches table to store the final combined score and reasoning if LLM was used or if we need to sync back
        if resume_id and job_id and is_llm_active and not llm_hit:
            try:
                def update_final_match_record(conn):
                    cursor = conn.cursor()
                    sim_score_val = round(final_score / 100.0, 4)
                    cursor.execute("""
                        UPDATE matches 
                        SET match_score = ?, reasoning = ?
                        WHERE resume_id = ? AND job_id = ?
                    """, (sim_score_val, reasoning, resume_id, job_id))
                    conn.commit()
                execute_db_with_retry(update_final_match_record)
            except Exception as db_err:
                logger.error(f"Failed to update final match record: {db_err}")

        exact_list = [m for m in matched_caps if m.get("match_type") == "exact"]
        taxonomy_list = [m for m in matched_caps if m.get("match_type") == "taxonomy"]
        transferable_list = [m for m in matched_caps if m.get("match_type") == "transferable"]
        semantic_list = [m for m in matched_caps if m.get("match_type") == "semantic"]

        from src.services.skills_normalization import SkillNormalizationService
        missing_req = []
        missing_pref = []
        for ms in missing_skills:
            ms_lower = ms.lower().strip()
            canonical_skill = SkillNormalizationService.resolve_canonical_skill(ms_lower)
            cid = canonical_skill.skill_id if canonical_skill else ms_lower
            
            is_req = False
            if ms_lower in req_names_lower:
                is_req = True
            else:
                for rs in req_names_lower:
                    r_can = SkillNormalizationService.resolve_canonical_skill(rs)
                    if r_can and r_can.skill_id == cid:
                        is_req = True
                        break
            if is_req:
                missing_req.append(ms)
            else:
                missing_pref.append(ms)

        experience_analysis = {
            "required_years": req_exp,
            "estimated_candidate_years": cand_exp,
            "score": score_breakdown.get("experience", 100.0) / 100.0,
            "confidence": score_breakdown.get("experience_confidence", 1.0)
        }

        explanation = {
            "reasoning": reasoning
        }

        cache_status = {
            "local_hit": local_hit,
            "llm_hit": llm_hit
        }

        # Record Observability Metrics
        try:
            from src.services.metrics import MetricsTracker
            MetricsTracker.record_match(
                processing_mode=processing_mode,
                confidence=confidence_val,
                local_hit=local_hit,
                llm_hit=llm_hit,
                is_llm_used=is_llm_active,
                llm_adjustment=adjustment,
                local_latency=local_latency,
                embedding_latency=embedding_latency,
                llm_latency=llm_latency,
                llm_failed=llm_failed
            )
        except Exception as metrics_err:
            logger.debug(f"Failed to record match metrics: {metrics_err}")

        # Application Decision (Informational)
        from src.services.application_decision_engine import ApplicationDecisionEngine
        app_decision = ApplicationDecisionEngine.evaluate(final_score, confidence_val).to_dict()

        return MatchResult(
            match_score=round(final_score / 100.0, 4),
            base_score=base_score_pct,
            llm_adjustment=round(adjustment, 2),
            matched_skills=exact_matches + [sm["requirement"] for sm in soft_matches],
            missing_skills=missing_skills,
            reasoning=reasoning,
            matched_capabilities=matched_caps,
            confidence=confidence_val,
            is_llm_used=is_llm_active,
            score_breakdown={k: v for k, v in score_breakdown.items() if k not in ("experience_confidence", "candidate_experience_years", "required_experience_years")},
            processing_mode=processing_mode,
            exact_matches=exact_list,
            taxonomy_matches=taxonomy_list,
            transferable_matches=transferable_list,
            semantic_matches=semantic_list,
            missing_required_skills=missing_req,
            missing_preferred_skills=missing_pref,
            experience_analysis=experience_analysis,
            explanation=explanation,
            cache=cache_status,
            application_decision=app_decision
        )
