# parser.py
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from datetime import datetime

import os
import json
import hashlib
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field, model_validator
from typing import List, Optional, Any
from dotenv import load_dotenv
from core.llm_provider import get_llm

load_dotenv()
# Setup local cache path relative to this script
CACHE_FILE = Path(__file__).resolve().parent / "jd_cache.json"

# ==========================================
# Pydantic Schemas (Structured Output)
# ==========================================
class ParsedJD(BaseModel):
    model_config = {
        "protected_namespaces": ()
    }

    title: str = Field(description="The job position title")
    company: str = Field(description="The company offering the role")
    department: Optional[str] = Field(default=None, description="The department within the company")
    employment_type: Optional[str] = Field(default=None, description="Full-time, Part-time, Contract, etc.")
    work_mode: Optional[str] = Field(default=None, description="Remote, Hybrid, or Onsite")
    location: str = Field(description="The geographic or remote status location")
    salary: Optional[str] = Field(default=None, description="Salary range or compensation details if available")

    # Split single skills array into two distinct strategic skill tiers
    required_skills: List[str] = Field(
        default_factory=list,
        description="Core hard/soft skills that are non-negotiable or explicitly listed as requirements.",
    )
    preferred_skills: List[str] = Field(
        default_factory=list,
        description="Bonus, optional, or 'nice-to-have' skills mentioned in the job description.",
    )

    required_technologies: List[str] = Field(default_factory=list, description="Specific required programming languages, tools, frameworks")
    preferred_technologies: List[str] = Field(default_factory=list, description="Specific preferred or bonus technologies")

    responsibilities: List[str] = Field(default_factory=list)
    requirements: List[str] = Field(default_factory=list)
    experience_required: str = Field(
        description="Years or levels of professional experience needed"
    )
    education_required: str = Field(
        description="Degrees, academic fields, or certifications required"
    )
    certifications: List[str] = Field(default_factory=list, description="Required or preferred certifications")
    benefits: List[str] = Field(default_factory=list, description="Perks, benefits, health insurance, etc.")
    industry: Optional[str] = Field(default=None, description="The industry of the company or role")
    seniority_level: Optional[str] = Field(default=None, description="Entry-level, Mid-level, Senior, Executive, etc.")

    # Metadata fields
    source: Optional[str] = Field(default=None, description="Source of the parsed job description (cache or llm)")
    cached_at: Optional[str] = Field(default=None, description="Timestamp when the item was cached")
    parser_version: str = Field(default="1.0.0", description="Version of the job parser")
    model_name: Optional[str] = Field(default=None, description="The LLM model name used to generate this parsed data")
    parse_timestamp: Optional[str] = Field(default=None, description="ISO timestamp of when the parse completed")

    @model_validator(mode='before')
    @classmethod
    def convert_empty_strings_to_none(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field, val in data.items():
                if isinstance(val, str) and not val.strip():
                    data[field] = None
        return data



# ==========================================
# Prompt Template Design
# ==========================================
prompt = ChatPromptTemplate.from_template(
    """
You are an expert Job Description parser. Your task is to analyze the provided job description and accurately extract structured information.

Metadata already known:
- Title: {title}
- Company: {company}
- Location: {location}

Analyze the text below and carefully segregate data points:
- department, employment_type, work_mode, salary, industry, seniority_level
- required_skills (strict, non-negotiable must-haves, core stack, e.g., "Must know Python")
- preferred_skills (optional, 'nice-to-have', plusses, or bonuses, e.g., "Experience with Kubernetes is a plus")
- required_technologies and preferred_technologies
- responsibilities (key duties and daily tasks)
- requirements (must-have overall qualifications/criteria)
- experience_required (years or levels specified)
- education_required (degrees or educational fields specified)
- certifications (e.g., AWS Certified, PMP)
- benefits (e.g., 401k, unlimited PTO)

CRITICAL RULES FOR SKILL EXTRACTION (CHANGE #2):
1. ONLY extract skills that are explicitly mentioned in the JOB DESCRIPTION text.
2. DO NOT infer, assume, or extrapolate skills. For example, if "Python" is mentioned, do not assume they need "Flask" or "FastAPI" unless those words are physically written in the text.
3. If no skills match a category, return an empty list.

JOB DESCRIPTION:
{jd}
"""
)


# ==========================================
# Caching Helper Operations
# ==========================================
def _load_cache() -> dict:
    """Safely loads the local json cache file into memory."""
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_to_cache(cache_key: str, parsed_data: dict):
    """Saves the fresh matching evaluation metrics safely into the cache file."""
    cache = _load_cache()
    cache[cache_key] = parsed_data
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[Warning] Failed to write to file cache: {e}")

def _generate_cache_key(jd_text: str, meta_title: str, meta_company: str) -> str:
    """Generates a unique deterministic string signature block for the target JD entry."""
    import re
    # Normalize whitespace to ensure cache robustness
    normalized_jd = re.sub(r'\s+', ' ', jd_text).strip()
    unique_string = f"{meta_company.lower().strip()}_{meta_title.lower().strip()}_{normalized_jd}"
    return hashlib.sha256(unique_string.encode("utf-8")).hexdigest()




def parse_jd(jd_text: str, meta_title: str, meta_company: str, meta_location: str, use_cache: bool = True) -> ParsedJD:
    """Parses a job description with built-in dynamic local filesystem caching 
    and unified float normalization for target experience fields.
    """
    cache_key = None
    if use_cache:
        # Check cache layer before hitting LLM provider
        cache_key = _generate_cache_key(jd_text, meta_title, meta_company)
        cache = _load_cache()

        if cache_key in cache:
            print("[Cache Hit] Returning cached parsed JD.")
            cached_result = ParsedJD(**cache[cache_key])
            cached_result.source = "cache"
            return cached_result
        
        print("[Cache Miss] No cached result found. Calling LLM...")
    else:
        print("[Cache Bypassed] Cache disabled. Calling LLM...")
    
    # Dynamic LLM Provider selection with failover support
    llm = get_llm(temperature=0.0)
    structured_llm = llm.with_structured_output(ParsedJD)
    chain = prompt | structured_llm
    
    # Passing both text and known API metadata to the model
    result = chain.invoke({
        "jd": jd_text,
        "title": meta_title,
        "company": meta_company,
        "location": meta_location
    })
    
    if isinstance(result, dict):
        result = ParsedJD(**result)

    # Populate metadata fields
    result.source = "llm"
    result.model_name = getattr(llm, "model_name", getattr(llm, "model", "llama-3.3-70b-versatile"))
    result.parse_timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Normalize skills vs. technologies to reduce overlap
    required_techs_lower = {t.lower() for t in result.required_technologies}
    preferred_techs_lower = {t.lower() for t in result.preferred_technologies}
    result.required_skills = [s for s in result.required_skills if s.lower() not in required_techs_lower]
    result.preferred_skills = [s for s in result.preferred_skills if s.lower() not in preferred_techs_lower]

    print("\n" + "=" * 80)
    print("PARSED JOB DESCRIPTION (AI OUTPUT)")
    print("=" * 80)
    print(result.model_dump_json(indent=4))
    print("=" * 80)
    
    if use_cache and cache_key:
        # Save to cache file with cached_at metadata timestamp
        result.cached_at = datetime.utcnow().isoformat() + "Z"
        _save_to_cache(cache_key, result.model_dump())
    
    return result




# ==========================================
# TEST RUNNERS (Add this at the very bottom)
# ==========================================
if __name__ == "__main__":
    # 1. Sample job description text to test your parser
    sample_jd_text = """
    We are looking for a Senior Python Developer. You will be responsible for building 
    and maintaining scalable web applications. You should have 5+ years of experience 
    with Python and Django. A Bachelor's Degree in Computer Science is required. 
    Key duties include writing clean code, mentoring junior devs, and deploying to AWS.
    """
    
    # 2. Mock metadata that your prompt expects
    sample_title = "Senior Python Developer"
    sample_company = "TechCorp"
    sample_location = "Remote, US"
    
    # Run 1: Test with use_cache=True (should hit if cached, or parse and populate)
    print("\n--- RUN 1: Cached Mode (use_cache=True) ---")
    try:
        parse_jd(
            jd_text=sample_jd_text, 
            meta_title=sample_title, 
            meta_company=sample_company, 
            meta_location=sample_location,
            use_cache=True
        )
    except Exception as e:
        print(f"An error occurred: {e}")
        
    # Run 2: Test with use_cache=False (should bypass cache completely)
    print("\n--- RUN 2: Bypassed Mode (use_cache=False) ---")
    try:
        parse_jd(
            jd_text=sample_jd_text, 
            meta_title=sample_title, 
            meta_company=sample_company, 
            meta_location=sample_location,
            use_cache=False
        )
    except Exception as e:
        print(f"An error occurred: {e}")







# prompt = ChatPromptTemplate.from_template(
#     """
# You are an expert Job Description parser.

# Extract information from the Job Description.

# Return:

# - title
# - company
# - location
# - skills
# - responsibilities
# - requirements
# - experience_required
# - education_required

# JOB DESCRIPTION:

# {jd}
# """
# )


# def parse_jd(jd_text: str):

#     chain = prompt | structured_llm

#     result = chain.invoke(
#         {
#             "jd": jd_text
#         }
#     )

#     print("\n" + "=" * 80)
#     print("PARSED JOB DESCRIPTION")
#     print("=" * 80)

#     print(result.model_dump_json(indent=4))

#     print("=" * 80)

#     return result


# Add this at the very bottom of parser.py

# if __name__ == "__main__":
#     # 1. A sample job description to test the script
#     sample_jd_text = """
#     Software Engineer needed at Tech Solutions Inc. located in New York, NY. 
#     Responsibilities include building web applications and collaborating with product teams. 
#     Must have 3+ years of experience with Python and React. 
#     Requires a Bachelor's degree in Computer Science.
#     """
    
#     # 2. Explicitly call the function with the sample text
#     parse_jd(raw_jd)