import json
import logging
import time
from src.services.skills_normalization import SkillNormalizationService, SkillComparisonEngine
from src.services.resume_aggregation import ResumeSkillAggregationService
from src.services.skills_relationship import RELATIONSHIP_REGISTRY
from src.services.capability_graph import find_capability_path
from src.services.embedding import EmbeddingService
from src.services.llm_reasoning import LLMReasoningService
from src.services.cache import calculate_sha256
from src.database.connection import get_connection, execute_db_with_retry

logger = logging.getLogger(__name__)

class CapabilityMatchingEngine:
    @classmethod
    def match_capabilities(cls, resume_parsed: dict, jd_parsed: dict, resume_raw_text: str = None, jd_raw_text: str = None, use_llm: bool = False) -> dict:
        """
        Preserves original workflow by orchestrating individual matching steps internally.
        """
        # 1. Build unified resume skill profile
        profile = ResumeSkillAggregationService.build_profile(resume_parsed, resume_raw_text)
        resume_ids = set(profile.skills.keys())
        
        # 2. Extract unique JD skill requirements
        jd_skills = []
        req_skills_obj = jd_parsed.get("required_skills", {})
        for category, list_val in req_skills_obj.items():
            if isinstance(list_val, list):
                for s in list_val:
                    if s and s.strip() not in jd_skills:
                        jd_skills.append(s.strip())
                        
        pref_list = jd_parsed.get("preferred_skills", [])
        if isinstance(pref_list, list):
            for s in pref_list:
                if s and str(s).strip() not in jd_skills:
                    jd_skills.append(str(s).strip())
                    
        if jd_raw_text:
            raw_jd_extracted = SkillNormalizationService.extract_skills(jd_raw_text)
            for s in raw_jd_extracted:
                if s and s not in jd_skills:
                    jd_skills.append(s)

        matched_capabilities = []
        unresolved_jd_skills = {}
        
        jd_objs = {}
        for js in jd_skills:
            skill_obj = SkillNormalizationService.resolve_canonical_skill(js)
            if skill_obj:
                jd_objs[skill_obj.skill_id] = skill_obj

        # Execute reusable matching methods sequentially
        for jid, jd_skill in jd_objs.items():
            # Exact Match
            exact_match = cls.match_exact_skills({jid}, resume_ids, profile, jd_objs)
            if exact_match:
                matched_capabilities.append(exact_match[0])
                continue
                
            # Relationship Match
            rel_match = cls.match_skill_relationships({jid}, resume_ids, profile, jd_objs)
            if rel_match:
                matched_capabilities.append(rel_match[0])
                continue
                
            # Capability Graph Match
            graph_match = cls.match_capability_graph({jid}, resume_ids, profile, jd_objs)
            if graph_match:
                matched_capabilities.append(graph_match[0])
                continue
                
            # Semantic Embedding Match
            emb_match = cls.match_embeddings({jid}, profile, resume_raw_text, jd_objs)
            if emb_match:
                matched_capabilities.append(emb_match[0])
                continue
                
            unresolved_jd_skills[jid] = jd_skill

        # LLM Reasoning Fallback
        if unresolved_jd_skills:
            resume_hash = calculate_sha256(resume_raw_text or json.dumps(resume_parsed))
            cached_matches = {}
            
            def read_cache(conn):
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in unresolved_jd_skills)
                query = f"""
                    SELECT required_id, matched, confidence, reasoning, evidence
                    FROM semantic_cache
                    WHERE resume_hash = ? AND required_id IN ({placeholders})
                """
                params = [resume_hash] + list(unresolved_jd_skills.keys())
                cursor.execute(query, params)
                return cursor.fetchall()

            try:
                rows = execute_db_with_retry(read_cache)
                for row in rows:
                    req_id, matched_val, conf_val, reason_val, evid_val = row
                    cached_matches[req_id] = {
                        "matched": bool(matched_val),
                        "confidence": conf_val,
                        "reasoning": reason_val,
                        "evidence": evid_val
                    }
            except Exception as e:
                logger.error(f"Semantic Cache retrieval failed: {e}")

            for req_id, cache_item in list(cached_matches.items()):
                jd_skill = unresolved_jd_skills[req_id]
                if cache_item["matched"] and cache_item["confidence"] >= 0.70:
                    matched_capabilities.append({
                        "requirement": jd_skill.display_name,
                        "match_type": "semantic",
                        "score": cache_item["confidence"],
                        "similarity": cache_item["confidence"],
                        "resume_evidence": cache_item["evidence"] if cache_item["evidence"] else "Demonstrated in experience."
                    })
                unresolved_jd_skills.pop(req_id)

            if use_llm and unresolved_jd_skills:
                try:
                    unresolved_reqs = {jid: s.display_name for jid, s in unresolved_jd_skills.items()}
                    llm_results = LLMReasoningService.reason_capabilities(resume_parsed, unresolved_reqs)
                    
                    cache_rows = []
                    for res_item in llm_results:
                        req_id = res_item.get("required_id")
                        matched = res_item.get("matched")
                        confidence = res_item.get("confidence", 0.0)
                        reasoning = res_item.get("reasoning", "")
                        evidence = res_item.get("evidence", "")
                        
                        cache_rows.append((resume_hash, req_id, 1 if matched else 0, confidence, reasoning, evidence))

                        if matched and confidence >= 0.70:
                            jd_skill = unresolved_jd_skills[req_id]
                            matched_capabilities.append({
                                "requirement": jd_skill.display_name,
                                "match_type": "semantic",
                                "score": confidence,
                                "similarity": confidence,
                                "resume_evidence": evidence if evidence else "Demonstrated in experience."
                            })
                            unresolved_jd_skills.pop(req_id)
                            
                    if cache_rows:
                        def write_cache(conn):
                            cursor = conn.cursor()
                            cursor.executemany("""
                                INSERT OR REPLACE INTO semantic_cache (resume_hash, required_id, matched, confidence, reasoning, evidence)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, cache_rows)
                            conn.commit()
                        execute_db_with_retry(write_cache)
                except Exception as e:
                    logger.error(f"LLM capability reasoning failed: {e}")

        missing_skills = [s.display_name for s in unresolved_jd_skills.values()]
        total_req = len(matched_capabilities) + len(missing_skills)
        overall_score = sum(mc["score"] for mc in matched_capabilities) / total_req if total_req > 0 else 0.0

        return {
            "match_score": overall_score,
            "matched_capabilities": matched_capabilities,
            "missing_skills": sorted(missing_skills)
        }

    # Expose Reusable Local Matching Methods independently
    
    @classmethod
    def match_exact_skills(cls, target_ids: set, resume_ids: set, profile, jd_objs: dict) -> list[dict]:
        """Exact skill matching check, distinguishing exact vs synonym/alias matches."""
        matched = []
        for jid in target_ids:
            if jid in resume_ids:
                cand_skill = profile.skills[jid]
                jd_skill = jd_objs.get(jid)
                if jd_skill:
                    evidence_val = cand_skill.evidence[0] if cand_skill.evidence else "Listed in skills section."
                    is_synonym = jd_skill.display_name.lower().strip() != cand_skill.display_name.lower().strip()
                    confidence_val = 0.95 if is_synonym else 1.00
                    match_type_val = "taxonomy" if is_synonym else "exact"
                    
                    matched.append({
                        "requirement": jd_skill.display_name,
                        "match_type": match_type_val,
                        "score": confidence_val,
                        "similarity": 1.0,
                        "resume_evidence": evidence_val
                    })
        return matched

    @classmethod
    def match_skill_relationships(cls, target_ids: set, resume_ids: set, profile, jd_objs: dict) -> list[dict]:
        """Transferable skill relationship mapping."""
        matched = []
        for jid in target_ids:
            best_rel = None
            best_rel_cand = None
            for rid in resume_ids:
                for rel in RELATIONSHIP_REGISTRY:
                    if rel.source_id == rid and rel.target_id == jid:
                        if best_rel is None or rel.transferability_score > best_rel.transferability_score:
                            best_rel = rel
                            best_rel_cand = profile.skills[rid]
            if best_rel:
                jd_skill = jd_objs.get(jid)
                if jd_skill:
                    evidence_val = best_rel_cand.evidence[0] if best_rel_cand.evidence else best_rel.description
                    matched.append({
                        "requirement": jd_skill.display_name,
                        "match_type": "transferable",
                        "score": best_rel.transferability_score,
                        "similarity": best_rel.transferability_score,
                        "resume_evidence": evidence_val
                    })
        return matched

    @classmethod
    def match_capability_graph(cls, target_ids: set, resume_ids: set, profile, jd_objs: dict) -> list[dict]:
        """Capability Graph Match check."""
        matched = []
        for jid in target_ids:
            best_path_score = 0.0
            best_path_desc = None
            best_path_cand = None
            
            for rid in resume_ids:
                score, path_desc = find_capability_path(rid, jid)
                if score > best_path_score:
                    best_path_score = score
                    best_path_desc = path_desc
                    best_path_cand = profile.skills[rid]
                    
            if best_path_score > 0.0:
                jd_skill = jd_objs.get(jid)
                if jd_skill:
                    evidence_val = "Path: " + " -> ".join(best_path_desc)
                    matched.append({
                        "requirement": jd_skill.display_name,
                        "match_type": "transferable",
                        "score": round(best_path_score, 2),
                        "similarity": round(best_path_score, 2),
                        "resume_evidence": evidence_val
                    })
        return matched

    # Configurable semantic matching thresholds
    STRONG_SEMANTIC_THRESHOLD = 0.82
    BORDERLINE_SEMANTIC_THRESHOLD = 0.75

    @classmethod
    def match_embeddings(cls, target_ids: set, profile, resume_raw_text: str, jd_objs: dict) -> list[dict]:
        """Embedding similarity matching check using configurable thresholds."""
        matched = []
        evidence_sentences = []
        for s_val in profile.skills.values():
            evidence_sentences.extend(s_val.evidence)
        if resume_raw_text:
            raw_sents = ResumeSkillAggregationService._split_into_sentences(resume_raw_text)
            evidence_sentences.extend(raw_sents)
        unique_sentences = list(set(evidence_sentences))

        for jid in target_ids:
            jd_skill = jd_objs.get(jid)
            if not jd_skill:
                continue
                
            promising_sentences = []
            skill_words = set(jd_skill.display_name.lower().split())
            for sent in unique_sentences:
                sent_lower = sent.lower()
                overlap = len(skill_words.intersection(set(sent_lower.split())))
                if overlap > 0:
                    promising_sentences.append((overlap, sent))
            
            promising_sentences.sort(key=lambda x: x[0], reverse=True)
            top_sentences = [x[1] for x in promising_sentences[:3]]
            
            best_emb_score = 0.0
            best_emb_sent = None
            
            if top_sentences:
                try:
                    all_texts = [jd_skill.display_name] + top_sentences
                    embs = EmbeddingService.generate_embeddings(all_texts)
                    jd_emb = embs[0]
                    sent_embs = embs[1:]
                    for sent, sent_emb in zip(top_sentences, sent_embs):
                        sim = EmbeddingService.compute_similarity(jd_emb, sent_emb)
                        if sim > best_emb_score:
                            best_emb_score = sim
                            best_emb_sent = sent
                except Exception as e:
                    logger.debug(f"Embedding check failed: {e}")
                    
            if best_emb_score >= cls.BORDERLINE_SEMANTIC_THRESHOLD:
                evidence_val = best_emb_sent if best_emb_sent else "Demonstrated semantically in resume content."
                is_borderline = best_emb_score < cls.STRONG_SEMANTIC_THRESHOLD
                classification = "borderline" if is_borderline else "strong"
                
                scaled_confidence = 0.50 + ((best_emb_score - 0.75) / 0.25) * 0.30
                scaled_confidence = round(max(0.50, min(0.80, scaled_confidence)), 2)
                
                matched.append({
                    "requirement": jd_skill.display_name,
                    "match_type": "semantic",
                    "match_classification": classification,
                    "is_borderline": is_borderline,
                    "score": scaled_confidence,
                    "similarity": round(best_emb_score, 2),
                    "resume_evidence": evidence_val
                })
        return matched

    @classmethod
    def match_experience(cls, resume_parsed: dict, jd_parsed: dict) -> float:
        """Independence check for experience."""
        from src.services.scoring_pipeline import calculate_resume_experience_years, parse_required_experience
        cand = calculate_resume_experience_years(resume_parsed)
        req = parse_required_experience(jd_parsed)
        if req == 0.0:
            return 1.0
        return min(1.0, cand / req)

    @classmethod
    def match_education(cls, resume_parsed: dict, jd_parsed: dict) -> float:
        """Independence check for education."""
        from src.services.scoring_pipeline import evaluate_education_match
        return evaluate_education_match(resume_parsed, jd_parsed)
