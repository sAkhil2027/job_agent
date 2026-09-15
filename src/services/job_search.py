import logging
import requests
from bs4 import BeautifulSoup
import urllib.parse
import json

logger = logging.getLogger(__name__)

import xml.etree.ElementTree as ET

import time
import threading

# Cache storage: {"timestamp": float, "jobs": list[dict]}
_search_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL_SECONDS = 3600  # 1 hour cache

class JobSearchService:
    @classmethod
    def search_jobs(cls, skills: list[str], limit: int = 5) -> list[dict]:
        """
        Fetches recent remote jobs from Remotive API, Jobicy API, and WeWorkRemotely RSS feed.
        Caches results for 1 hour to prevent rate limits and IP blocking.
        Gracefully falls back to existing database jobs if all external endpoints are unavailable.
        """
        now = time.time()
        cache_key = ",".join(sorted([s.lower().strip() for s in skills if s])) if skills else "general"

        # Check memory cache first
        with _cache_lock:
            cached_entry = _search_cache.get(cache_key)
            if cached_entry and (now - cached_entry["timestamp"] < CACHE_TTL_SECONDS):
                logger.info(f"Serving {len(cached_entry['jobs'])} jobs from 1-hour cache for skills: {skills}")
                return cached_entry["jobs"][:limit]

        jobs = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 AI-Job-Matcher/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8"
        }

        # 1. Fetch from Remotive API (Official REST API)
        logger.info("Fetching remote jobs from Remotive API...")
        try:
            remotive_url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=15"
            response = requests.get(remotive_url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                api_jobs = data.get("jobs", [])
                for item in api_jobs:
                    jd_raw = cls._clean_html(item.get("description", ""))
                    jobs.append({
                        "title": item.get("title", "Unknown Title"),
                        "company": item.get("company_name", "Unknown Company"),
                        "url": item.get("url", ""),
                        "location": item.get("candidate_required_location", "Remote"),
                        "jd_raw": jd_raw
                    })
            elif response.status_code in (403, 429):
                logger.warning(f"Remotive API rate-limited (status {response.status_code}).")
        except Exception as e:
            logger.warning(f"Error searching jobs on Remotive: {e}")

        # 2. Fetch from Jobicy API
        if len(jobs) < limit * 2:
            logger.info("Fetching recent remote IT/Developer jobs from Jobicy API...")
            try:
                jobicy_url = "https://jobicy.com/api/v2/remote-jobs?count=15&industry=dev"
                response = requests.get(jobicy_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    api_jobs = data.get("jobs", [])
                    for item in api_jobs:
                        jd_raw = cls._clean_html(item.get("jobDescription", ""))
                        jobs.append({
                            "title": item.get("jobTitle", "Unknown Title"),
                            "company": item.get("companyName", "Unknown Company"),
                            "url": item.get("url", ""),
                            "location": item.get("jobGeo", "Remote"),
                            "jd_raw": jd_raw
                        })
                elif response.status_code in (403, 429):
                    logger.warning(f"Jobicy API rate-limited or blocked (status {response.status_code}).")
            except Exception as e:
                logger.warning(f"Error searching jobs on Jobicy: {e}")

        # 3. Fetch from WeWorkRemotely RSS feed
        if len(jobs) < limit * 2:
            logger.info("Fetching recent remote IT/Developer jobs from WeWorkRemotely RSS feed...")
            try:
                wwr_url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
                response = requests.get(wwr_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    root = ET.fromstring(response.content)
                    items = root.findall(".//item")
                    for item in items:
                        title_text = item.find("title").text or "Unknown Title"
                        company = "Unknown Company"
                        title = title_text
                        
                        if " at " in title_text:
                            parts = title_text.rsplit(" at ", 1)
                            title = parts[0]
                            company = parts[1]
                        elif ":" in title_text:
                            parts = title_text.split(":", 1)
                            company = parts[0].strip()
                            title = parts[1].strip()

                        link = item.find("link").text or ""
                        description_html = item.find("description").text or ""
                        jd_raw = cls._clean_html(description_html)

                        jobs.append({
                            "title": title,
                            "company": company,
                            "url": link,
                            "location": "Remote",
                            "jd_raw": jd_raw
                        })
                elif response.status_code in (403, 429):
                    logger.warning(f"WeWorkRemotely RSS rate-limited or blocked (status {response.status_code}).")
            except Exception as e:
                logger.warning(f"Error searching jobs on WeWorkRemotely: {e}")

        # 4. Fallback to existing database jobs if external scraping yielded 0 jobs
        if not jobs:
            logger.warning("All external job feeds returned 0 jobs. Falling back to local database job cache...")
            try:
                from src.database.connection import get_connection
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT title, company, url, jd_raw FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
                rows = cursor.fetchall()
                conn.close()
                for r in rows:
                    jobs.append({
                        "title": r[0] or "Software Developer",
                        "company": r[1] or "Tech Company",
                        "url": r[2] or "",
                        "location": "Remote",
                        "jd_raw": r[3] or ""
                    })
            except Exception as db_err:
                logger.warning(f"Could not load fallback jobs from database: {db_err}")

        # Save to memory cache
        if jobs:
            with _cache_lock:
                _search_cache[cache_key] = {"timestamp": now, "jobs": jobs}

        # Return up to requested limit
        return jobs[:limit]

    @classmethod
    def _clean_html(cls, html_content: str) -> str:
        """Removes HTML tags to get raw text for JD."""
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        return soup.get_text(separator="\n", strip=True)

if __name__ == "__main__":
    # Test script to see the output when running `python job_search.py` directly
    logging.basicConfig(level=logging.INFO)
    jobs = JobSearchService.search_jobs(["Python", "React"], limit=3)
    
    print("\n=== RAW OUTPUT FROM JOBICY API ===")
    for idx, job in enumerate(jobs):
        print(f"\n[JOB {idx+1}] {job['title']} @ {job['company']}")
        print(f"URL: {job['url']}")
        print(f"Location: {job['location']}")
        print(f"JD Snippet: {job['jd_raw'][:150]}...")
