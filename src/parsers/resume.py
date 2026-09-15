import json
import uuid
import logging
import re
from src.parsers.pdf import PDFParser
from src.services.groq import GroqService
from src.database.connection import get_connection, execute_db_with_retry

logger = logging.getLogger(__name__)

def extract_contact_info(text: str) -> dict:
    """
    Extracts contact info (email, phone, linkedin, github, portfolio) 
    from raw text and any extracted hyperlink annotations.
    """
    contacts = {}
    
    # 1. Email Regex & mailto links
    mailto = re.search(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', text, re.IGNORECASE)
    if mailto:
        contacts['email'] = mailto.group(1).strip()
    else:
        email_match = re.search(r'([a-zA-Z0-9._%+-]+)\s*@\s*([a-zA-Z0-9.-]+)\s*\.\s*([a-zA-Z]{2,})', text)
        if email_match:
            contacts['email'] = f"{email_match.group(1)}@{email_match.group(2)}.{email_match.group(3)}".replace(" ", "")
        
    # 2. Phone Regex & tel links
    tel = re.search(r'tel:([0-9+ -]{10,20})', text, re.IGNORECASE)
    if tel:
        contacts['phone'] = tel.group(1).strip()
    else:
        phone_match = re.search(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\+?\d{10,12}', text)
        if phone_match:
            contacts['phone'] = phone_match.group(0).strip()

    # Extract all URLs
    all_urls = re.findall(r'https?://[^\s<>"\'\)]+', text)
    cleaned_urls = []
    for u in all_urls:
        u = u.rstrip('.,;:')
        if u not in cleaned_urls:
            cleaned_urls.append(u)
        
    # 3. LinkedIn Regex & URL search
    linkedin_url = None
    for u in cleaned_urls:
        if "linkedin.com/in/" in u.lower() or "linkedin.com/pub/" in u.lower():
            linkedin_url = u
            break
    if not linkedin_url:
        linkedin_match = re.search(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_/%]+', text, re.IGNORECASE)
        if linkedin_match:
            linkedin_url = linkedin_match.group(0).strip()
            if not linkedin_url.startswith('http'):
                linkedin_url = 'https://' + linkedin_url
    if linkedin_url:
        contacts['linkedin'] = linkedin_url.rstrip('/')
        
    # 4. GitHub profile (prioritize user profile URL over repository sub-paths)
    github_profile = None
    for u in cleaned_urls:
        if "github.com/" in u.lower():
            after_domain = u.lower().split("github.com/")[1].strip("/")
            parts = [p for p in after_domain.split("/") if p]
            # Root profile has exactly 1 part (the username)
            if len(parts) == 1:
                github_profile = u
                break
    if not github_profile:
        for u in cleaned_urls:
            if "github.com/" in u.lower():
                github_profile = u
                break
    if not github_profile:
        github_match = re.search(r'(?:https?://)?(?:www\.)?github\.com/([a-zA-Z0-9\-_]+)/?', text, re.IGNORECASE)
        if github_match:
            github_profile = f"https://github.com/{github_match.group(1)}"
    if github_profile:
        contacts['github'] = github_profile.rstrip('/')

    # 5. Portfolio / Personal site (STRICT: only if explicitly identified as portfolio/website/homepage)
    portfolio_url = None
    common_non_portfolio_domains = [
        "linkedin.com", "github.com", "leetcode.com", "codechef.com", 
        "hackerrank.com", "codeforces.com", "google.com", "youtube.com",
        "medium.com", "twitter.com", "x.com", "facebook.com", "instagram.com",
        "arxiv.org", "doi.org", "coursera.org", "udemy.com", "edx.org",
        "wikipedia.org", "amazon.com", "aws.amazon.com", "microsoft.com",
        "kaggle.com", "stackoverflow.com", "gitlab.com", "bitbucket.org"
    ]
    
    # Check for explicit portfolio mentions in text (e.g., "Portfolio: https://...", "Website: https://...")
    portfolio_match = re.search(
        r'(?:portfolio|personal\s+website|website|homepage|site)\s*[:\-]?\s*(https?://[^\s<>"\'\)]+)', 
        text, 
        re.IGNORECASE
    )
    if portfolio_match:
        candidate_url = portfolio_match.group(1).rstrip('.,;:')
        if not any(d in candidate_url.lower() for d in common_non_portfolio_domains):
            portfolio_url = candidate_url

    if not portfolio_url:
        # Check if any URL specifically contains 'portfolio' or personal domain patterns
        for u in cleaned_urls:
            u_lower = u.lower()
            if any(d in u_lower for d in common_non_portfolio_domains):
                continue
            if any(k in u_lower for k in ["portfolio", ".dev", ".me", ".site", ".page"]):
                portfolio_url = u
                break
                
    if portfolio_url:
        contacts['portfolio'] = portfolio_url
    else:
        contacts['portfolio'] = None
        
    return contacts

def enhance_parsed_resume(raw_text: str, parsed_json: dict) -> dict:
    """
    Deterministically resolves links, coding profiles, student project repos,
    and contact details from raw text and extracted hyperlinks without fabricating data.
    """
    if "contact_info" not in parsed_json or not isinstance(parsed_json["contact_info"], dict):
        parsed_json["contact_info"] = {}
    ci = parsed_json["contact_info"]

    # Extract contact info from text
    local_contacts = extract_contact_info(raw_text)
    for field in ["email", "phone", "linkedin", "github", "portfolio", "location", "name"]:
        # Only preserve genuine non-placeholder values
        val = ci.get(field)
        if val and str(val).strip().lower() in ["none", "null", "", "n/a", "not provided", "false", "undefined"]:
            ci[field] = None
        elif not val and local_contacts.get(field):
            ci[field] = local_contacts[field]
        elif field not in ci:
            ci[field] = None

    # Clean portfolio if it is a placeholder or not in original text
    if ci.get("portfolio"):
        port_lower = str(ci["portfolio"]).lower().strip()
        if (
            port_lower in ["none", "null", "", "n/a"] or
            any(ph in port_lower for ph in ["example.com", "portfolio.com", "janedoe.dev", "johndoe.dev", "mysite.com"]) or
            port_lower not in raw_text.lower() and not any(port_lower in u.lower() for u in local_contacts.values() if u)
        ):
            ci["portfolio"] = None

    # Extract all cleaned URLs
    all_urls = re.findall(r'https?://[^\s<>"\'\)]+', raw_text)
    cleaned_urls = [u.rstrip('.,;:') for u in all_urls]

    # Collect project repository URLs
    github_repos = []
    for u in cleaned_urls:
        if "github.com/" in u.lower():
            parts = [p for p in u.lower().split("github.com/")[1].split("/") if p]
            if len(parts) >= 2:
                github_repos.append((parts[1], u))

    # Resolve coding profiles (only if present in text)
    if "coding_profiles" not in parsed_json or not isinstance(parsed_json["coding_profiles"], dict):
        parsed_json["coding_profiles"] = {}
    cp = parsed_json["coding_profiles"]

    for u in cleaned_urls:
        u_lower = u.lower()
        if "leetcode.com" in u_lower:
            cp["leetcode"] = u
        elif "codechef.com" in u_lower:
            cp["codechef"] = u
        elif "hackerrank.com" in u_lower:
            cp["hackerrank"] = u
        elif "codeforces.com" in u_lower:
            cp["codeforces"] = u

    # Resolve student project repositories & URLs only if explicitly matching
    projects = parsed_json.get("projects", [])
    if isinstance(projects, list):
        used_repos = set()
        for proj in projects:
            p_name = str(proj.get("name", "")).lower()
            p_desc = str(proj.get("description", "")).lower()
            p_url = str(proj.get("url", "") or "")
            p_repo = str(proj.get("repository", "") or "")

            is_placeholder_url = (
                not p_url or 
                p_url.lower() in ["null", "none", "", "n/a"] or
                any(ph in p_url.lower() for ph in ["/githublink", "githublink", "example.com"]) or
                p_url.lower().rstrip("/") == "https://github.com" or
                p_url.lower().rstrip("/") == "http://github.com"
            )
            is_placeholder_repo = (
                not p_repo or 
                p_repo.lower() in ["null", "none", "", "n/a"] or
                any(ph in p_repo.lower() for ph in ["/githublink", "githublink", "example.com"]) or
                p_repo.lower().rstrip("/") == "https://github.com" or
                p_repo.lower().rstrip("/") == "http://github.com"
            )

            matched_repo_url = None
            # Keyword / name matching only
            for r_name, r_url in github_repos:
                r_clean = r_name.lower().replace("-", " ").replace("_", " ")
                keywords = [w for w in r_clean.split() if len(w) > 2]
                if any(kw in p_name or kw in p_desc for kw in keywords):
                    matched_repo_url = r_url
                    used_repos.add(r_url)
                    break

            if matched_repo_url:
                if is_placeholder_url:
                    proj["url"] = matched_repo_url
                if is_placeholder_repo:
                    proj["repository"] = matched_repo_url
            else:
                if is_placeholder_url:
                    proj["url"] = None
                if is_placeholder_repo:
                    proj["repository"] = None

    return parsed_json

class ResumeParser:
    def __init__(self):
        self.pdf_parser = PDFParser()

    def parse_and_save(self, filename: str, file_bytes: bytes) -> dict:
        """
        Extracts text from the PDF, parses it via Groq API,
        enhances contacts, links, and projects deterministically,
        saves the result in SQLite, and returns the parsed JSON structure along with DB record ID.
        """
        # 1. Extract text from PDF
        logger.info(f"Extracting text from {filename}...")
        raw_text = self.pdf_parser.extract_text(file_bytes)
        if not raw_text.strip():
            raise ValueError("The uploaded PDF resume contains no extractable text.")

        # 2. Parse via Groq API
        logger.info("Parsing resume text using Groq API...")
        parsed_json = GroqService.parse_resume(raw_text)

        # 3. Deterministically enhance links, profiles, projects, and contacts
        try:
            parsed_json = enhance_parsed_resume(raw_text, parsed_json)
        except Exception as ex:
            logger.error(f"Error enhancing parsed resume: {ex}")

        # 4. Save to SQLite database
        logger.info("Saving parsed resume to SQLite database...")
        resume_id = str(uuid.uuid4()) # Generate unique ID in Python
        try:
            def save_resume(conn):
                cursor = conn.cursor()
                query = """
                    INSERT INTO resumes (id, filename, raw_text, parsed_json)
                    VALUES (?, ?, ?, ?);
                """
                cursor.execute(query, (resume_id, filename, raw_text, json.dumps(parsed_json)))
                conn.commit()
            execute_db_with_retry(save_resume)
            logger.info(f"Resume saved successfully with ID: {resume_id}")
        except Exception as e:
            logger.error(f"Database error while saving resume: {e}")
            raise Exception(f"Database error: {e}")

        return {
            "id": resume_id,
            "filename": filename,
            "parsed_json": parsed_json
        }

