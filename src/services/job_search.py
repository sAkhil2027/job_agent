import logging
import requests
from bs4 import BeautifulSoup
import urllib.parse
import json

logger = logging.getLogger(__name__)

import xml.etree.ElementTree as ET

class JobSearchService:
    @classmethod
    def search_jobs(cls, skills: list[str], limit: int = 5) -> list[dict]:
        """
        Fetches recent remote jobs from Jobicy API and WeWorkRemotely RSS feed.
        Combines them up to the requested limit so the vector engine can score them.
        """
        jobs = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Job-Matcher/1.0"
        }

        # 1. Fetch from Jobicy API
        logger.info("Fetching recent remote IT/Developer jobs from Jobicy API...")
        try:
            jobicy_url = "https://jobicy.com/api/v2/remote-jobs?count=15&industry=dev"
            response = requests.get(jobicy_url, headers=headers, timeout=15)
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
            else:
                logger.error(f"Jobicy API returned status: {response.status_code}")
        except Exception as e:
            logger.error(f"Error searching jobs on Jobicy: {e}")

        # 2. Fetch from WeWorkRemotely RSS feed
        logger.info("Fetching recent remote IT/Developer jobs from WeWorkRemotely RSS feed...")
        try:
            wwr_url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
            response = requests.get(wwr_url, headers=headers, timeout=15)
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
            else:
                logger.error(f"WeWorkRemotely RSS returned status: {response.status_code}")
        except Exception as e:
            logger.error(f"Error searching jobs on WeWorkRemotely: {e}")

        # Return up to the requested limit
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
