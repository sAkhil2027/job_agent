import re
import logging
from enum import Enum
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class ATSPlatform(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ASHBY = "ashby"
    BAMBOOHR = "bamboohr"
    SMARTRECRUITERS = "smartrecruiters"
    GENERIC = "generic"

@dataclass
class PlatformDetectionResult:
    platform: str
    confidence: float
    is_multi_step: bool
    detection_method: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

class ApplicationPlatformDetector:
    """
    Application Platform Detector module that classifies target job application pages
    (Greenhouse, Lever, Workday, Ashby, BambooHR, SmartRecruiters, Generic)
    using fast 0ms domain regex patterns and HTML DOM signature analysis.
    """

    # Fast 0ms Domain / URL Regex Patterns
    URL_PATTERNS = [
        (re.compile(r"boards\.greenhouse\.io|greenhouse\.io", re.IGNORECASE), ATSPlatform.GREENHOUSE, 0.98, False),
        (re.compile(r"jobs\.lever\.co|lever\.co", re.IGNORECASE), ATSPlatform.LEVER, 0.98, False),
        (re.compile(r"myworkdayjobs\.com|workday\.com", re.IGNORECASE), ATSPlatform.WORKDAY, 0.98, True),
        (re.compile(r"jobs\.ashbyhq\.com|ashbyhq\.com", re.IGNORECASE), ATSPlatform.ASHBY, 0.98, False),
        (re.compile(r"bamboohr\.com|bamboohr\.co", re.IGNORECASE), ATSPlatform.BAMBOOHR, 0.95, False),
        (re.compile(r"jobs\.smartrecruiters\.com|smartrecruiters\.com", re.IGNORECASE), ATSPlatform.SMARTRECRUITERS, 0.95, False),
    ]

    # DOM Signature HTML Regex Patterns (for custom company subdomains e.g. careers.company.com)
    DOM_SIGNATURES = [
        (re.compile(r"grnhse_app|grnhse_iframe|greenhouse\.io|form#application_form", re.IGNORECASE), ATSPlatform.GREENHOUSE, 0.95, False),
        (re.compile(r"lever-job-details|lever\.co|form#application-form", re.IGNORECASE), ATSPlatform.LEVER, 0.95, False),
        (re.compile(r"data-automation-id=['\"]workday-app['\"]|myworkdayjobs|wd-Application", re.IGNORECASE), ATSPlatform.WORKDAY, 0.95, True),
        (re.compile(r"ashby-application-form|ashbyhq\.com|ashby-job-posting", re.IGNORECASE), ATSPlatform.ASHBY, 0.95, False),
        (re.compile(r"bamboohr-app|Fab-BambooHR|bamboohr\.com", re.IGNORECASE), ATSPlatform.BAMBOOHR, 0.90, False),
        (re.compile(r"st-app|smartrecruiters\.com|sr-job-details", re.IGNORECASE), ATSPlatform.SMARTRECRUITERS, 0.90, False),
    ]

    @classmethod
    def detect(cls, job_url: str, html_content: Optional[str] = None) -> Dict[str, Any]:
        """
        Detects the job application platform and returns a dictionary:
        {
            "platform": "greenhouse",
            "confidence": 0.98,
            "is_multi_step": false,
            "detection_method": "url_domain"
        }
        """
        if not job_url:
            job_url = ""

        # Step 1: Fast Domain Inspection (0ms)
        for pattern, platform, confidence, is_multi_step in cls.URL_PATTERNS:
            if pattern.search(job_url):
                logger.info(f"[ApplicationPlatformDetector] Identified platform '{platform.value}' via URL domain (Confidence: {confidence}).")
                res = PlatformDetectionResult(
                    platform=platform.value,
                    confidence=confidence,
                    is_multi_step=is_multi_step,
                    detection_method="url_domain"
                )
                return res.to_dict()

        # Step 2: DOM Signature Inspection (for custom company subdomains)
        if html_content:
            for pattern, platform, confidence, is_multi_step in cls.DOM_SIGNATURES:
                if pattern.search(html_content):
                    logger.info(f"[ApplicationPlatformDetector] Identified platform '{platform.value}' via DOM signature (Confidence: {confidence}).")
                    res = PlatformDetectionResult(
                        platform=platform.value,
                        confidence=confidence,
                        is_multi_step=is_multi_step,
                        detection_method="dom_signature"
                    )
                    return res.to_dict()

        # Fallback: Generic Job Page
        logger.info("[ApplicationPlatformDetector] Defaulting to 'generic' application platform classification.")
        res = PlatformDetectionResult(
            platform=ATSPlatform.GENERIC.value,
            confidence=0.50,
            is_multi_step=False,
            detection_method="fallback"
        )
        return res.to_dict()
