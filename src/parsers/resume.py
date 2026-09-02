import json
import uuid
import logging
import re
from src.parsers.pdf import PDFParser
from src.services.groq import GroqService
from src.database.connection import get_connection, execute_db_with_retry

logger = logging.getLogger(__name__)

def extract_contact_info(text: str) -> dict:
    # Clean up common PDF icon ligatures/merges that get concatenated directly with words
    text = re.sub(r'envel[^\w]*pe', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'github[^\w]*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'linkedin[^\w]*', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'phone[^\w]*', ' ', text, flags=re.IGNORECASE)

    contacts = {}
    
    # 1. Email Regex (handles spaces around @ and . that are common in PDF extractions)
    email_match = re.search(r'([a-zA-Z0-9._%+-]+)\s*@\s*([a-zA-Z0-9.-]+)\s*\.\s*([a-zA-Z]{2,})', text)
    if email_match:
        contacts['email'] = f"{email_match.group(1)}@{email_match.group(2)}.{email_match.group(3)}".replace(" ", "")
        
    # 2. Phone Regex (captures formats like +1-234-567-8901, (123) 456-7890, 123-456-7890, +91 9876543210, etc.)
    phone_match = re.search(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|\+?\d{10,12}', text)
    if phone_match:
        contacts['phone'] = phone_match.group(0).strip()
        
    # 3. LinkedIn Regex
    linkedin_match = re.search(r'(?:https?://)?(?:www\.)?linkedin\.com/in/[a-zA-Z0-9\-_/%]+', text, re.IGNORECASE)
    if linkedin_match:
        url = linkedin_match.group(0).strip()
        if not url.startswith('http'):
            url = 'https://' + url
        contacts['linkedin'] = url.rstrip('/')
        
    # 4. GitHub Regex
    github_match = re.search(r'(?:https?://)?(?:www\.)?github\.com/[a-zA-Z0-9\-_/%]+', text, re.IGNORECASE)
    if github_match:
        url = github_match.group(0).strip()
        if not url.startswith('http'):
            url = 'https://' + url
        contacts['github'] = url.rstrip('/')
        
    return contacts

class ResumeParser:
    def __init__(self):
        self.pdf_parser = PDFParser()

    def parse_and_save(self, filename: str, file_bytes: bytes) -> dict:
        """
        Extracts text from the PDF, parses it via Groq API,
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

        # 3. Override/fill values using local regex extraction
        try:
            local_contacts = extract_contact_info(raw_text)
            if "contact_info" not in parsed_json or not isinstance(parsed_json["contact_info"], dict):
                parsed_json["contact_info"] = {}
            
            ci = parsed_json["contact_info"]
            for field in ["email", "phone", "linkedin", "github"]:
                # Always prioritize the highly precise deterministic local contact parser
                if field in local_contacts and local_contacts[field]:
                    ci[field] = local_contacts[field]
        except Exception as ex:
            logger.error(f"Error overriding contact info: {ex}")

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

