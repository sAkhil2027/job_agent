import re
import logging
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

from src.services.automation.platform_detector import (
    ATSPlatform,
    PlatformDetectionResult,
    ApplicationPlatformDetector
)

# Export ATSResult alias for backward compatibility
ATSResult = PlatformDetectionResult

class ATSIdentifier(ApplicationPlatformDetector):
    """
    Deterministic Applicant Tracking System (ATS) Identifier.
    Delegates to ApplicationPlatformDetector while preserving backward compatibility.
    """
    
    @classmethod
    def identify(cls, job_url: str, html_content: Optional[str] = None) -> ATSResult:
        res_dict = cls.detect(job_url, html_content)
        return ATSResult(
            platform=res_dict["platform"],
            confidence=res_dict["confidence"],
            is_multi_step=res_dict["is_multi_step"],
            detection_method=res_dict["detection_method"]
        )

    # Property alias for legacy tests/code accessing .ats instead of .platform
    @property
    def ats(self) -> str:
        return getattr(self, "platform", "generic")

