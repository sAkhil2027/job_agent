import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables from .env file
load_dotenv(dotenv_path=BASE_DIR / ".env")

class Config:
    BASE_DIR = BASE_DIR
    # AI Models & Keys
    GROQ_API_KEY = os.getenv("GROQ_API_KEY")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

    # Server & DB Settings
    DATABASE_URL = os.getenv("DATABASE_URL")
    PORT = int(os.getenv("PORT", "8000"))
    HOST = os.getenv("HOST", "127.0.0.1")
    
    # Browser Automation Settings
    HEADLESS_MODE = os.getenv("HEADLESS_MODE", "false").lower() in ("true", "1", "yes")
    BROWSER_PROFILE_DIR = BASE_DIR / os.getenv("BROWSER_PROFILE_DIR", "data/browser_profile")
    SCREENSHOT_DIR = BASE_DIR / os.getenv("SCREENSHOT_DIR", "data/screenshots")
    
    # Application Worker Settings
    MAX_APPLICATION_RETRIES = int(os.getenv("MAX_APPLICATION_RETRIES", "3"))
    APPLICATION_TIMEOUT = int(os.getenv("APPLICATION_TIMEOUT", "120"))

    # Throttling & Rate-limiting settings
    AGENT_INTERVAL_SECONDS = int(os.getenv("AGENT_INTERVAL_SECONDS", "600"))  # Default to 10 minutes
    MAX_JOBS_TO_EVALUATE = int(os.getenv("MAX_JOBS_TO_EVALUATE", "3"))        # Only parse/evaluate top 3 jobs per run
    LLM_API_URL = os.getenv("LLM_API_URL", "https://api.groq.com/openai/v1/chat/completions")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")

    # Configurable router thresholds
    HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "0.90"))
    LOW_BASE_SCORE_THRESHOLD = float(os.getenv("LOW_BASE_SCORE_THRESHOLD", "20.0"))
    HIGH_BASE_SCORE_THRESHOLD = float(os.getenv("HIGH_BASE_SCORE_THRESHOLD", "95.0"))
    MAX_LLM_ADJUSTMENT = float(os.getenv("MAX_LLM_ADJUSTMENT", "5.0"))

    # Cache level versions for two-level cache architecture
    PARSER_VERSION = "1.0.0"
    MATCHER_VERSION = "1.0.0"
    TAXONOMY_VERSION = "1.0.0"
    EMBEDDING_MODEL_VERSION = "1.0.0"
    SCORING_CONFIG_VERSION = "1.0.0"
    PROMPT_VERSION = "1.0.0"
    LLM_CONTEXT_SCHEMA_VERSION = "1.0.0"

    # Configurable scoring weights (must sum to 1.0)
    SCORING_WEIGHTS = {
        "required_skills": 0.35,
        "preferred_skills": 0.10,
        "experience": 0.20,
        "responsibilities": 0.15,
        "role_title": 0.10,
        "education_certifications": 0.05,
        "domain_relevance": 0.05
    }

    # Configurable confidence signal weights (must sum to 1.0)
    CONFIDENCE_WEIGHTS = {
        "exact_match_coverage": 0.30,
        "taxonomy_match_coverage": 0.20,
        "experience_confidence": 0.20,
        "role_title_confidence": 0.15,
        "responsibility_confidence": 0.15
    }

    @classmethod
    def ensure_directories(cls):
        """Ensure data, browser profile, and screenshot directories exist."""
        os.makedirs(cls.BASE_DIR / "data", exist_ok=True)
        os.makedirs(cls.BROWSER_PROFILE_DIR, exist_ok=True)
        os.makedirs(cls.SCREENSHOT_DIR, exist_ok=True)

    @classmethod
    def validate(cls):
        """Validate critical configuration settings."""
        cls.ensure_directories()

        # Validate that scoring weights sum to 1.0
        weights_sum = sum(cls.SCORING_WEIGHTS.values())
        if not abs(weights_sum - 1.0) < 1e-6:
            raise ValueError(f"SCORING_WEIGHTS must sum to 1.0, currently sums to {weights_sum}")

        # Validate that confidence weights sum to 1.0
        conf_sum = sum(cls.CONFIDENCE_WEIGHTS.values())
        if not abs(conf_sum - 1.0) < 1e-6:
            raise ValueError(f"CONFIDENCE_WEIGHTS must sum to 1.0, currently sums to {conf_sum}")

        missing = []
        if not cls.GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        
        if missing:
            raise ValueError(
                f"Missing required environment variables in .env: {', '.join(missing)}\n"
                "Please configure them before running the application."
            )
