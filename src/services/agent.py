import threading
import time
import queue
import logging
import json
import uuid
from src.database.connection import get_connection
from src.services.job_search import JobSearchService
from src.services.groq import GroqService
from src.services.embedding import EmbeddingService
from src.server.handlers import _get_resume_skills, _build_embedding_text, _compare_skills

logger = logging.getLogger(__name__)

class AutonomousAgent(threading.Thread):
    def __init__(self):
        super().__init__()
        self.daemon = True
        self.listeners = []
        self.listeners_lock = threading.Lock()
        from src.config import Config
        self.interval_seconds = getattr(Config, "AGENT_INTERVAL_SECONDS", 600)  # Configurable wakeup interval
        self.running = True
        self.wake_event = threading.Event()
        self.history = []
        self.history_lock = threading.Lock()
        self.last_run_time = 0

    def register_listener(self) -> queue.Queue:
        q = queue.Queue(maxsize=100)
        with self.listeners_lock:
            self.listeners.append(q)
        return q

    def unregister_listener(self, q: queue.Queue):
        with self.listeners_lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def trigger_run(self):
        """Wakes up the agent immediately to run a matching cycle, with a 30s cooldown."""
        now = time.time()
        if now - self.last_run_time < 30:
            logger.info("[Agent] Wake-up request ignored (cooldown active).")
            return
        logger.info("[Agent] Wake-up triggered by client connection.")
        self.wake_event.set()

    def get_history(self) -> list[str]:
        """Returns a copy of the recent log event history."""
        with self.history_lock:
            return list(self.history)

    def log_and_broadcast(self, message: str, type_evt: str = "log"):
        """Logs to standard python logger and broadcasts to all connected SSE clients."""
        logger.info(f"[Agent] {message}")
        event_data = {
            "time": time.strftime("%H:%M:%S"),
            "message": message,
            "type": type_evt
        }
        sse_payload = f"data: {json.dumps(event_data)}\n\n"
        
        # Save to history
        with self.history_lock:
            self.history.append(sse_payload)
            if len(self.history) > 20:
                self.history.pop(0)

        with self.listeners_lock:
            for q in self.listeners:
                try:
                    q.put_nowait(sse_payload)
                except queue.Full:
                    pass

    def run(self):
        self.log_and_broadcast("Autonomous Job Matcher Agent started.", "status")
        
        while self.running:
            # Clear event flag before cycle
            self.wake_event.clear()
            
            try:
                self.log_and_broadcast("Agent checking for matches...")
                with matching_lock:
                    self._run_matching_cycle()
            except Exception as e:
                logger.error(f"Error in agent execution cycle: {e}", exc_info=True)
                self.log_and_broadcast(f"Error during matching cycle: {e}", "error")
            
            # Wait for wakeup trigger or timeout
            if self.running:
                self.wake_event.wait(self.interval_seconds)

        self.log_and_broadcast("Agent shut down.", "status")

    def _run_matching_cycle(self):
        from src.config import Config
        from src.server.handlers import _extract_all_skills
        from src.services.cache import PARSER_VERSION, MATCH_VERSION, calculate_sha256
        from src.database.connection import execute_db_with_retry

        self.last_run_time = time.time()
        
        # 1. Fetch latest resume
        def fetch_resume(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT id, filename, parsed_json, embedding, raw_text FROM resumes ORDER BY created_at DESC LIMIT 1")
            return cursor.fetchone()

        row = execute_db_with_retry(fetch_resume)
        if not row:
            self.log_and_broadcast("No resumes found in database. Waiting for upload...", "warning")
            return
            
        resume_id, filename, resume_parsed_str, resume_embed_str, resume_raw_text = row
        resume_parsed = json.loads(resume_parsed_str)

        self.log_and_broadcast(f"Found active resume: {filename}")
        
        # 2. Ensure resume has embedding
        resume_embed = None
        if resume_embed_str and resume_embed_str != "null":
            resume_embed = json.loads(resume_embed_str)
            
        if not resume_embed:
            self.log_and_broadcast("Generating vector embedding for resume...")
            embed_text = _build_embedding_text(resume_parsed)
            # Embedding API call made outside transaction!
            resume_embed = EmbeddingService.generate_embedding(embed_text)
            
            def save_resume_embed(conn):
                cursor = conn.cursor()
                cursor.execute("UPDATE resumes SET embedding = ? WHERE id = ?", (json.dumps(resume_embed), resume_id))
                conn.commit()
            execute_db_with_retry(save_resume_embed)
            self.log_and_broadcast("Resume embedding saved successfully.")

        # 3. Fetch jobs from online feeds (Network call outside transaction)
        search_skills = _get_resume_skills(resume_parsed)
        self.log_and_broadcast(f"Searching online job boards for: {', '.join(search_skills)}")
        
        raw_jobs = JobSearchService.search_jobs(search_skills, limit=10)
        self.log_and_broadcast(f"Retrieved {len(raw_jobs)} live job postings. Filtering and scoring...")

        # 4. Filter jobs by local semantic similarity first
        resume_hash = calculate_sha256(resume_raw_text)

        # Check job and match cache validity using atomic select queries
        def query_existing_jobs_and_matches(conn):
            cursor = conn.cursor()
            job_details = {}
            for rj in raw_jobs:
                cursor.execute("SELECT id, jd_parsed, embedding, jd_hash, parser_version FROM jobs WHERE url = ?", (rj['url'],))
                job_row = cursor.fetchone()
                if job_row:
                    job_id = job_row[0]
                    cursor.execute("""
                        SELECT matched_skills, missing_skills, reasoning, match_score, match_version, resume_hash, soft_matches, matched_capabilities 
                        FROM matches 
                        WHERE resume_id = ? AND job_id = ?
                    """, (resume_id, job_id))
                    match_row = cursor.fetchone()
                    job_details[rj['url']] = (job_row, match_row)
            return job_details

        job_cache_map = execute_db_with_retry(query_existing_jobs_and_matches)

        jobs_to_evaluate = []
        for rj in raw_jobs:
            current_jd_hash = calculate_sha256(rj['jd_raw'])
            cache_info = job_cache_map.get(rj['url'])
            existing_job = None
            row_match = None
            is_job_cache_valid = False
            is_match_cache_valid = False
            
            if cache_info:
                existing_job, row_match = cache_info
                db_jd_hash = existing_job[3]
                db_parser_version = existing_job[4]
                if db_jd_hash == current_jd_hash and db_parser_version == PARSER_VERSION:
                    is_job_cache_valid = True
                    
                if row_match and is_job_cache_valid:
                    db_match_version = row_match[4]
                    db_resume_hash = row_match[5]
                    # The cached reasoning must also be generated successfully
                    if (db_match_version == MATCH_VERSION and 
                        db_resume_hash == resume_hash and 
                        row_match[2] is not None and 
                        not row_match[2].startswith("Could not generate reasoning") and 
                        not row_match[2].startswith("**Local Analysis Fallback:**")):
                        is_match_cache_valid = True

            if is_job_cache_valid and is_match_cache_valid:
                # Match already computed and still valid, skip completely
                continue

            # Compute preliminary similarity score locally
            if existing_job and is_job_cache_valid:
                embed_str = existing_job[2]
                if embed_str and embed_str != "null":
                    jd_embed = json.loads(embed_str)
                else:
                    jd_embed = EmbeddingService.generate_embedding(rj['title'] + " " + rj['jd_raw'][:1000])
                sim_score = EmbeddingService.compute_similarity(resume_embed, jd_embed)
            else:
                jd_embed = EmbeddingService.generate_embedding(rj['title'] + " " + rj['jd_raw'][:1000])
                sim_score = EmbeddingService.compute_similarity(resume_embed, jd_embed)
            
            jobs_to_evaluate.append({
                "raw_job": rj,
                "prelim_score": sim_score,
                "prelim_embed": jd_embed,
                "existing_job": existing_job,
                "is_job_cache_valid": is_job_cache_valid,
                "row_match": row_match,
                "is_match_cache_valid": is_match_cache_valid,
                "current_jd_hash": current_jd_hash
            })

        # Sort jobs by preliminary similarity score descending
        jobs_to_evaluate.sort(key=lambda x: x["prelim_score"], reverse=True)

        # 5. Evaluate jobs: top Config.MAX_JOBS_TO_EVALUATE with Groq, remainder with programmatic fallback
        new_matches_count = 0
        for idx, item in enumerate(jobs_to_evaluate):
            if not self.running:
                break
            
            rj = item["raw_job"]
            sim_score = item["prelim_score"]
            jd_embed = item["prelim_embed"]
            existing_job = item["existing_job"]
            is_job_cache_valid = item["is_job_cache_valid"]
            row_match = item["row_match"]
            is_match_cache_valid = item["is_match_cache_valid"]
            current_jd_hash = item["current_jd_hash"]
            
            # Decide whether to use LLM based on rank
            use_llm = idx < getattr(Config, "MAX_JOBS_TO_EVALUATE", 3)
            
            try:
                if existing_job and existing_job[1]:
                    job_id = existing_job[0]
                    jd_parsed = json.loads(existing_job[1])
                    embed_str = existing_job[2]
                    if embed_str and embed_str != "null":
                        jd_embed = json.loads(embed_str)
                    else:
                        jd_embed_text = _build_embedding_text(jd_parsed)
                        jd_embed = EmbeddingService.generate_embedding(jd_embed_text)
                    sim_score = EmbeddingService.compute_similarity(resume_embed, jd_embed)
                else:
                    job_id = existing_job[0] if existing_job else str(uuid.uuid4())
                    if use_llm:
                        self.log_and_broadcast(f"Evaluating new job using LLM: {rj['title']} @ {rj['company']}")
                        jd_parsed = GroqService.parse_jd(rj['jd_raw'])
                        jd_embed_text = _build_embedding_text(jd_parsed)
                        jd_embed = EmbeddingService.generate_embedding(jd_embed_text)
                        sim_score = EmbeddingService.compute_similarity(resume_embed, jd_embed)
                    else:
                        # Fallback: Local programmatical parsing/extraction to avoid Groq call
                        self.log_and_broadcast(f"Evaluating new job using local parser: {rj['title']} @ {rj['company']}")
                        from src.services.skills_normalization import SkillNormalizationService
                        extracted_skills = SkillNormalizationService.extract_skills(rj['jd_raw'])
                        jd_parsed = {
                            "title": rj['title'],
                            "required_skills": {
                                "languages": extracted_skills, "frameworks": [], "databases": [],
                                "cloud_devops": [], "tools": [], "soft_skills": []
                            },
                            "preferred_skills": [],
                            "responsibilities": [],
                            "requirements": {"years_of_experience": "", "education": "", "other": []}
                        }


                    # Save newly parsed job description to jobs table in a short transaction
                    def save_parsed_job(conn):
                        cursor = conn.cursor()
                        cursor.execute("SELECT id FROM jobs WHERE url = ?", (rj['url'],))
                        existing_db_row = cursor.fetchone()
                        nonlocal job_id
                        if existing_db_row:
                            job_id = existing_db_row[0]
                            cursor.execute("""
                                UPDATE jobs 
                                SET jd_parsed = ?, embedding = ?, jd_hash = ?, parser_version = ?
                                WHERE id = ?
                            """, (json.dumps(jd_parsed), json.dumps(jd_embed), current_jd_hash, PARSER_VERSION, job_id))
                        else:
                            cursor.execute("""
                                INSERT INTO jobs (id, title, company, url, jd_raw, jd_parsed, embedding, jd_hash, parser_version)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (job_id, rj['title'], rj['company'], rj['url'], rj['jd_raw'], json.dumps(jd_parsed), json.dumps(jd_embed), current_jd_hash, PARSER_VERSION))
                        conn.commit()
                    execute_db_with_retry(save_parsed_job)
                
                from src.services.scoring_pipeline import ScoringPipeline
                options = {
                    "resume_id": resume_id,
                    "job_id": job_id,
                    "resume_raw_text": resume_raw_text,
                    "jd_raw_text": rj['jd_raw'],
                    "use_llm": use_llm,
                    "resume_hash": resume_hash,
                    "jd_hash": current_jd_hash
                }
                match_res = ScoringPipeline.match(resume_parsed, jd_parsed, options)
                match_pct = round(match_res.match_score * 100.0, 2)
                self.log_and_broadcast(f"Matched: '{rj['title']}' - Score: {match_pct}% Match!", "match")
                new_matches_count += 1
                
            except Exception as e:
                logger.error(f"Failed to process job {rj['title']}: {e}")
                self.log_and_broadcast(f"Failed to evaluate job '{rj['title']}': {e}", "warning")
            
            # Sleep to respect rate limits
            if use_llm:
                time.sleep(3.0)
            else:
                time.sleep(0.1)
                
        if new_matches_count > 0:
            self.log_and_broadcast(f"Matching cycle complete. Added {new_matches_count} new job matches.", "success")
        else:
            self.log_and_broadcast("Matching cycle complete. No new matches found this time.", "status")

    def stop(self):
        self.running = False
        self.wake_event.set()

# Global lock to synchronize matching operations between server threads and the background agent
matching_lock = threading.Lock()

# Global singleton agent instance
agent_instance = AutonomousAgent()
