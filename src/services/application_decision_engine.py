from dataclasses import dataclass

@dataclass
class ApplicationDecision:
    decision: str  # AUTO_APPLY | REVIEW | REJECT
    reason: str
    confidence: float

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "reason": self.reason,
            "confidence": self.confidence
        }

class ApplicationDecisionEngine:
    @classmethod
    def evaluate(cls, final_score: float, confidence: float) -> ApplicationDecision:
        """
        Evaluates the final match score and confidence level to determine the application route.
        """
        # score >= 85 and conf >= 0.9 -> AUTO_APPLY
        if final_score >= 85.0 and confidence >= 0.90:
            decision = "AUTO_APPLY"
            reason = f"Excellent fit score ({final_score:.1f}%) and high confidence ({confidence * 100:.1f}%)."
        # score >= 75 -> REVIEW
        elif final_score >= 75.0:
            decision = "REVIEW"
            reason = f"Good fit score ({final_score:.1f}%). Recommended for manual review."
        # else -> REJECT
        else:
            decision = "REJECT"
            reason = f"Fit score ({final_score:.1f}%) does not meet application thresholds."

        return ApplicationDecision(
            decision=decision,
            reason=reason,
            confidence=confidence
        )
