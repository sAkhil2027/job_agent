import json
import logging
from src.services.groq import GroqService

logger = logging.getLogger(__name__)

class LLMReasoningService:
    @classmethod
    def reason_capabilities(cls, resume_parsed: dict, unresolved_requirements: dict[str, str]) -> list[dict]:
        """
        Batches multiple capability checks into a single structured LLM query.
        Accepts unresolved_requirements as a dict of required_id -> display_name.
        Validates that returned required_id and evidence exist in candidate data.
        """
        if not unresolved_requirements:
            return []
            
        system_prompt = (
            "You are an expert technical recruiter analyzing a candidate's resume for specific required skills.\n"
            "Evaluate if the candidate demonstrates capability for each required skill based ONLY on their documented experience, projects, education or certifications.\n"
            "Do NOT assume or infer skills without evidence.\n"
            "Output strictly valid JSON conforming to the requested schema. No pre-text, post-text or markdown."
        )
        
        prompt = (
            f"Evaluate whether the candidate has the capability to work with each of these required skills (specified as key-value pairs of required_id and display name):\n"
            f"{json.dumps(unresolved_requirements)}\n\n"
            f"Resume Data: {json.dumps(resume_parsed)}\n"
            f"Respond strictly in JSON format matching this schema:\n"
            f'{{"results": [{{"required_id": "string", "matched": true/false, "confidence": 0.0-1.0, "reasoning": "string", "evidence": "sentence from resume"}}]}}'
        )
        
        try:
            from src.services.groq import clean_and_parse_json
            response_str = GroqService.completion(prompt, system_prompt, response_json=True)
            res = clean_and_parse_json(response_str)
            results = res.get("results", [])
            
            validated_results = []
            resume_str_lower = json.dumps(resume_parsed).lower()
            
            for item in results:
                req_id = item.get("required_id")
                matched = bool(item.get("matched"))
                confidence = float(item.get("confidence", 0.0))
                reasoning = item.get("reasoning", "")
                evidence = item.get("evidence", "")
                
                # Enforce validation rules:
                if req_id not in unresolved_requirements:
                    logger.warning(f"LLM returned unexpected required_id: '{req_id}' not in {list(unresolved_requirements.keys())}")
                    continue
                    
                confidence = max(0.0, min(1.0, confidence))
                
                if matched and evidence:
                    evidence_clean = evidence.strip().lower()
                    alphanumeric_evidence = "".join(c for c in evidence_clean if c.isalnum())
                    alphanumeric_resume = "".join(c for c in resume_str_lower if c.isalnum())
                    if alphanumeric_evidence not in alphanumeric_resume:
                        logger.warning(f"Rejected LLM matched capability '{req_id}': evidence '{evidence}' does not exist in resume.")
                        matched = False
                        confidence = 0.0
                        reasoning = f"Rejected match: Evidence '{evidence}' not found in resume."
                        
                validated_results.append({
                    "required_id": req_id,
                    "required_skill": unresolved_requirements[req_id],
                    "matched": matched,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "evidence": evidence
                })
                
            return validated_results
            
        except Exception as e:
            logger.error(f"LLM Reasoning Batch Service failed: {e}")
            raise
