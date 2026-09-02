import os
import json
import logging
import time
from src.parsers.resume import ResumeParser

logger = logging.getLogger(__name__)

def serve_static_file(handler, path):
    """Serves static frontend files (HTML, CSS, JS)."""
    # Prevent directory traversal attacks
    normalized_path = os.path.normpath(path)
    if normalized_path.startswith("..") or normalized_path.startswith("/"):
        handler.send_response(403)
        handler.end_headers()
        handler.wfile.write(b"Forbidden")
        return

    # Static assets directory
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
    file_path = os.path.join(static_dir, normalized_path)

    # Default to index.html if path is empty or a directory
    if os.path.isdir(file_path) or not normalized_path or normalized_path == ".":
        file_path = os.path.join(static_dir, "index.html")

    if not os.path.exists(file_path) or os.path.isdir(file_path):
        handler.send_response(404)
        handler.end_headers()
        handler.wfile.write(b"Not Found")
        return

    # Determine content type
    content_type = "text/html"
    if file_path.endswith(".css"):
        content_type = "text/css"
    elif file_path.endswith(".js"):
        content_type = "application/javascript"
    elif file_path.endswith(".json"):
        content_type = "application/json"
    elif file_path.endswith(".ico"):
        content_type = "image/x-icon"

    try:
        with open(file_path, "rb") as f:
            content = f.read()
        handler.send_response(200)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(content)))
        handler.end_headers()
        handler.wfile.write(content)
    except Exception as e:
        logger.error(f"Error serving file {file_path}: {e}")
        handler.send_response(500)
        handler.end_headers()
        handler.wfile.write(b"Internal Server Error")

def parse_multipart_form(body_bytes, boundary):
    """
    Manually parses multipart/form-data body to extract uploaded file bytes and filename.
    Works without cgi (which is deprecated/removed in newer Python versions).
    """
    boundary_bytes = f"--{boundary}".encode("utf-8")
    parts = body_bytes.split(boundary_bytes)
    
    for part in parts:
        if not part or part == b"--\r\n" or part == b"\r\n":
            continue
        
        # Split headers and body of this part
        if b"\r\n\r\n" in part:
            header_part, file_data = part.split(b"\r\n\r\n", 1)
        else:
            continue
            
        header_text = header_part.decode("utf-8", errors="ignore")
        
        # Look for filename in content-disposition
        if 'name="file"' in header_text or 'filename=' in header_text:
            # Extract filename
            filename = "resume.pdf"
            for line in header_text.split("\r\n"):
                if "Content-Disposition:" in line and "filename=" in line:
                    parts = line.split("filename=")
                    if len(parts) > 1:
                        filename = parts[1].strip('"').strip("'")
            
            # Trim trailing \r\n from data
            if file_data.endswith(b"\r\n"):
                file_data = file_data[:-2]
                
            return filename, file_data
            
    raise ValueError("No file uploaded with parameter name 'file'.")

def handle_parse_resume(handler, body_bytes, content_type_header):
    """Handles POST /api/parse-resume by parsing PDF and calling Groq."""
    try:
        # Extract boundary from content-type header
        if "boundary=" not in content_type_header:
            raise ValueError("Invalid content type. Must be multipart/form-data with a boundary.")
            
        boundary = content_type_header.split("boundary=")[1].strip()
        filename, file_bytes = parse_multipart_form(body_bytes, boundary)
        
        # Call ResumeParser
        parser = ResumeParser()
        result = parser.parse_and_save(filename, file_bytes)
        
        response_bytes = json.dumps(result).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(response_bytes)))
        handler.end_headers()
        handler.wfile.write(response_bytes)
        
    except Exception as e:
        logger.error(f"Error handling parse resume request: {e}", exc_info=True)
        err_res = {"error": str(e)}
        response_bytes = json.dumps(err_res).encode("utf-8")
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(response_bytes)))
        handler.end_headers()
        handler.wfile.write(response_bytes)

def _extract_all_skills(skills_obj) -> list[str]:
    """Helper to extract a flat list of skills from various JSON structures (dict of lists, list of dicts, or flat list)."""
    skills = []
    if not skills_obj:
        return skills
    if isinstance(skills_obj, list):
        for item in skills_obj:
            if isinstance(item, dict):
                # Handle {"category": "Programming Languages...", "keywords": ["C", "C++", ...]}
                for key in ["keywords", "skills", "values"]:
                    val = item.get(key)
                    if isinstance(val, list):
                        skills.extend([str(s).strip() for s in val if s])
                    elif isinstance(val, str):
                        skills.append(val.strip())
                    elif val:
                        skills.append(str(val).strip())
            elif isinstance(item, str):
                skills.append(item.strip())
            elif item:
                skills.append(str(item).strip())
    elif isinstance(skills_obj, dict):
        for val in skills_obj.values():
            if isinstance(val, list):
                skills.extend([str(s).strip() for s in val if s])
            elif isinstance(val, str):
                skills.append(val.strip())
            elif val:
                skills.append(str(val).strip())
    elif isinstance(skills_obj, str):
        skills.append(skills_obj.strip())
    return [str(s) for s in skills if s]

def _get_resume_skills(parsed_json: dict) -> list[str]:
    """Helper to extract top skills from parsed resume JSON for searching."""
    skills_obj = parsed_json.get("skills", {})
    skills = []
    if isinstance(skills_obj, dict):
        for category in ["languages", "frameworks", "databases", "cloud", "tools"]:
            cat_val = skills_obj.get(category, [])
            if isinstance(cat_val, list):
                skills.extend([str(s) for s in cat_val if s])
            elif isinstance(cat_val, str):
                skills.append(cat_val)
    if not skills:
        skills = _extract_all_skills(skills_obj)
    return skills[:5]

def _build_embedding_text(parsed_json: dict) -> str:
    """Helper to build a concise text representation of a resume or JD for embedding."""
    parts = []
    
    summary = parsed_json.get("professional_summary")
    if summary:
        parts.append(str(summary))
        
    skills_obj = parsed_json.get("skills")
    if skills_obj:
        skills = _extract_all_skills(skills_obj)
        if skills:
            parts.append("Skills: " + ", ".join([str(s) for s in skills if s]))
    
    # JD specific fields
    title = parsed_json.get("title")
    if title:
        parts.append(f"Title: {title}")
        
    req_skills_obj = parsed_json.get("required_skills")
    if req_skills_obj:
        skills = _extract_all_skills(req_skills_obj)
        if skills:
            parts.append("Required Skills: " + ", ".join([str(s) for s in skills if s]))
    
    # Filter out any lingering None or empty strings just to be safe
    parts = [str(p) for p in parts if p]
    return "\n".join(parts)

def _normalize_skill_name(s: str) -> str:
    """Normalizes skill names to standard aliases to handle synonyms and acronyms."""
    s = s.strip().lower()
    canonical = {
        "react": "react", "reactjs": "react", "react.js": "react",
        "node": "node", "nodejs": "node", "node.js": "node",
        "vue": "vue", "vuejs": "vue", "vue.js": "vue",
        "angular": "angular", "angularjs": "angular", "angular.js": "angular",
        "javascript": "javascript", "js": "javascript",
        "typescript": "typescript", "ts": "typescript",
        "postgresql": "postgresql", "postgres": "postgresql",
        "mongodb": "mongodb", "mongo": "mongodb",
        "ai": "ai", "artificial intelligence": "ai", "artificialintelligence": "ai",
        "ml": "ml", "machine learning": "ml", "machinelearning": "ml",
        "nlp": "nlp", "natural language processing": "nlp",
        "dl": "dl", "deep learning": "dl",
        "genai": "genai", "generative ai": "genai", "generativeai": "genai",
        "aws": "aws", "amazon web services": "aws", "amazonwebservices": "aws",
        "gcp": "gcp", "google cloud platform": "gcp",
        "kubernetes": "kubernetes", "k8s": "kubernetes",
        "ui": "ui", "user interface": "ui",
        "ux": "ux", "user experience": "ux",
        "swe": "swe", "software engineer": "swe", "software engineering": "swe",
        "qa": "qa", "quality assurance": "qa",
    }
    return canonical.get(s, s)

def _compare_skills(resume_parsed: dict, jd_parsed: dict, resume_raw_text: str = None, jd_raw_text: str = None, use_llm: bool = False) -> tuple[list[str], list[dict], list[str], list[dict]]:
    """Programmatically compares resume and JD skills using the centralized CapabilityMatchingEngine."""
    from src.services.capability_matcher import CapabilityMatchingEngine
    
    result = CapabilityMatchingEngine.match_capabilities(
        resume_parsed=resume_parsed,
        jd_parsed=jd_parsed,
        resume_raw_text=resume_raw_text,
        jd_raw_text=jd_raw_text,
        use_llm=use_llm
    )
    
    exact_matches = [m["candidate_skill"] for m in result["matched_capabilities"] if m["stage"] == "Exact Match"]
    soft_matches = [m for m in result["matched_capabilities"] if m["stage"] in ("Skill Relationship Match", "Capability Graph Match", "Embedding Similarity Match", "LLM Reasoning Match")]
    
    return exact_matches, soft_matches, result["missing_skills"], result["matched_capabilities"]






def handle_match_jobs(handler, body_bytes):
    """Handles POST /api/match-jobs by searching, embedding, and scoring."""
    from src.database.connection import get_connection
    from src.services.job_search import JobSearchService
    from src.services.groq import GroqService
    from src.services.embedding import EmbeddingService
    from src.services.agent import matching_lock
    import uuid

    matching_lock.acquire()
    try:
        req_data = json.loads(body_bytes.decode("utf-8"))
        resume_id = req_data.get("resume_id")
        if not resume_id:
            raise ValueError("resume_id is required.")
            
        # 1. Fetch resume (short transaction)
        from src.config import Config
        from src.database.connection import execute_db_with_retry, get_connection
        from src.services.groq import GroqService
        from src.services.embedding import EmbeddingService
        from src.services.capability_matcher import CapabilityMatchingEngine
        from src.services.cache import PARSER_VERSION, MATCH_VERSION, calculate_sha256
        import uuid

        def fetch_resume(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT parsed_json, embedding, raw_text FROM resumes WHERE id = ?", (resume_id,))
            return cursor.fetchone()

        row = execute_db_with_retry(fetch_resume)
        if not row:
            raise ValueError(f"Resume with id {resume_id} not found.")
            
        resume_parsed = json.loads(row[0])
        resume_embed_str = row[1]
        resume_raw_text = row[2] if len(row) > 2 and row[2] else ""

        # 2. Get or generate resume embedding
        resume_embed = None
        if resume_embed_str and resume_embed_str != "null":
            resume_embed = json.loads(resume_embed_str)
            
        if not resume_embed:
            embed_text = _build_embedding_text(resume_parsed)
            resume_embed = EmbeddingService.generate_embedding(embed_text)
            
            def save_resume_embed(conn):
                cursor = conn.cursor()
                cursor.execute("UPDATE resumes SET embedding = ? WHERE id = ?", (json.dumps(resume_embed), resume_id))
                conn.commit()
            execute_db_with_retry(save_resume_embed)
            
        # 3. Search jobs based on resume skills
        search_skills = _get_resume_skills(resume_parsed)
        logger.info(f"Searching jobs with skills: {search_skills}")
        raw_jobs = JobSearchService.search_jobs(search_skills, limit=10)
        
        # 4. Filter jobs by local semantic similarity first
        resume_hash = calculate_sha256(resume_raw_text)

        # Check job and match cache validity in a single query
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
                    if (db_match_version == MATCH_VERSION and 
                        db_resume_hash == resume_hash and 
                        row_match[2] is not None and 
                        not row_match[2].startswith("Could not generate reasoning") and 
                        not row_match[2].startswith("**Local Analysis Fallback:**")):
                        is_match_cache_valid = True

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

        matches = []
        
        # 5. Evaluate each job description: top Config.MAX_JOBS_TO_EVALUATE with Groq, remainder with programmatic fallback
        for idx, item in enumerate(jobs_to_evaluate):
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
            
            logger.info(f"Processing JD for {rj['title']} at {rj['company']} (LLM evaluation: {use_llm})")
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
                        jd_parsed = GroqService.parse_jd(rj['jd_raw'])
                        jd_embed_text = _build_embedding_text(jd_parsed)
                        jd_embed = EmbeddingService.generate_embedding(jd_embed_text)
                        sim_score = EmbeddingService.compute_similarity(resume_embed, jd_embed)
                    else:
                        # Local programmatic parsing fallback
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

                    # Write newly parsed job description in short transaction
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
                res_dict = match_res.to_dict()
                res_dict.update({
                    "job_id": job_id,
                    "title": rj['title'],
                    "company": rj['company'],
                    "url": rj['url'],
                    "score": round(match_res.match_score * 100.0, 2),
                    "jd_parsed": jd_parsed,
                    "soft_matches": [
                        m for m in match_res.matched_capabilities
                        if m.get("match_type") in ("taxonomy", "transferable", "semantic")
                    ]
                })
                matches.append(res_dict)
            except Exception as e:
                logger.error(f"Failed to process job {rj['title']}: {e}")

            # Sleep to respect Groq API rate limits
            if use_llm:
                time.sleep(3.0)
            else:
                time.sleep(0.1)
                
        # Sort matches by score descending
        matches.sort(key=lambda x: x["score"], reverse=True)

        # Query application statuses for this resume
        def fetch_app_statuses(conn):
            cursor = conn.cursor()
            cursor.execute("SELECT job_id, status FROM application_queue WHERE resume_id = ?", (resume_id,))
            return dict(cursor.fetchall())

        app_statuses = execute_db_with_retry(fetch_app_statuses)
        for m in matches:
            m["application_status"] = app_statuses.get(m["job_id"])
            m["applied"] = m["job_id"] in app_statuses
        
        response_data = {"resume_id": resume_id, "matches": matches}
        response_bytes = json.dumps(response_data).encode("utf-8")
        
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(response_bytes)))
        handler.end_headers()
        handler.wfile.write(response_bytes)
        
    except Exception as e:
        logger.error(f"Error handling match jobs request: {e}", exc_info=True)
        err_res = {"error": str(e)}
        response_bytes = json.dumps(err_res).encode("utf-8")
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(response_bytes)))
        handler.end_headers()
        handler.wfile.write(response_bytes)
    finally:
        matching_lock.release()

def handle_apply_job(handler, body_bytes):
    """Handles POST /api/apply-job by enqueuing a job application for the background agent worker."""
    from src.services.application_queue import enqueue_application
    from src.services.agent import agent_instance

    try:
        req_data = json.loads(body_bytes.decode("utf-8"))
        resume_id = req_data.get("resume_id")
        job_id = req_data.get("job_id")

        if not resume_id or not job_id:
            handler.send_response(400)
            handler.end_headers()
            handler.wfile.write(b'{"error": "Missing resume_id or job_id"}')
            return

        queue_id = enqueue_application(resume_id, job_id)

        agent_instance.log_and_broadcast(
            f"Job application enqueued (ID: {queue_id[:8]}). Autonomous agent worker scheduled to submit application.",
            "status"
        )

        res_data = {
            "status": "success",
            "queue_id": queue_id,
            "message": "Job application enqueued for agent worker."
        }
        res_bytes = json.dumps(res_data).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)

    except Exception as e:
        logger.error(f"Error handling apply job request: {e}", exc_info=True)
        err_res = {"error": str(e)}
        res_bytes = json.dumps(err_res).encode("utf-8")
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)


def handle_agent_stream(handler):
    """Handles Server-Sent Events GET /api/agent/stream to broadcast real-time log updates."""
    from src.services.agent import agent_instance
    import queue
    
    # Establish SSE headers
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.send_header("X-Accel-Buffering", "no")
    handler.end_headers()

    # Register client queue
    client_queue = agent_instance.register_listener()
    
    # Send initial welcome message
    welcome_evt = {
        "time": time.strftime("%H:%M:%S"),
        "message": "Connected to Agent Stream. Listening for events...",
        "type": "status"
    }
    try:
        handler.wfile.write(f"data: {json.dumps(welcome_evt)}\n\n".encode("utf-8"))
        
        # Replay past log history to let the user see previous agent activities immediately
        for history_payload in agent_instance.get_history():
            handler.wfile.write(history_payload.encode("utf-8"))
            
        handler.wfile.flush()
    except Exception:
        agent_instance.unregister_listener(client_queue)
        return

    # Trigger background agent to wake up and run matching cycle immediately
    agent_instance.trigger_run()

    try:
        while True:
            try:
                # Read from queue with a timeout so we don't block indefinitely 
                sse_payload = client_queue.get(timeout=2.0)
                handler.wfile.write(sse_payload.encode("utf-8"))
                handler.wfile.flush()
            except queue.Empty:
                # Send SSE ping to keep connection alive and detect disconnects
                handler.wfile.write(b": ping\n\n")
                handler.wfile.flush()
    except Exception as e:
        logger.debug(f"SSE client disconnected: {e}")
    finally:
        agent_instance.unregister_listener(client_queue)

def handle_detailed_explanation(handler, body_bytes):
    """POST /api/detailed-explanation on-demand detailed AI analysis endpoint."""
    try:
        req_data = json.loads(body_bytes.decode("utf-8"))
        resume_id = req_data.get("resume_id")
        job_id = req_data.get("job_id")

        if not resume_id or not job_id:
            handler.send_response(400)
            handler.end_headers()
            handler.wfile.write(b'{"error": "Missing resume_id or job_id"}')
            return

        from src.services.explanation_service import DetailedExplanationService
        explanation = DetailedExplanationService.get_detailed_explanation(resume_id, job_id)

        res_data = {
            "resume_id": resume_id,
            "job_id": job_id,
            "detailed_explanation": explanation
        }
        res_bytes = json.dumps(res_data).encode("utf-8")

        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)

    except Exception as e:
        logger.error(f"Error handling detailed explanation request: {e}", exc_info=True)
        err_res = {"error": str(e)}
        res_bytes = json.dumps(err_res).encode("utf-8")
        handler.send_response(500)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)

def handle_get_candidate_answers(handler):
    """GET /api/candidate-answers returns all candidate Q&A database rules."""
    from src.database.connection import get_all_candidate_answers
    try:
        answers = get_all_candidate_answers()
        res_bytes = json.dumps({"answers": answers}).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)
    except Exception as e:
        logger.error(f"Error handling GET candidate answers: {e}")
        handler.send_response(500)
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

def handle_add_candidate_answer(handler, body_bytes):
    """POST /api/candidate-answers creates or updates a candidate Q&A rule."""
    from src.database.connection import add_candidate_answer
    try:
        req_data = json.loads(body_bytes.decode("utf-8"))
        q_key = req_data.get("question_key")
        q_pattern = req_data.get("question_pattern")
        a_value = req_data.get("answer_value")

        if not q_key or not q_pattern or not a_value:
            handler.send_response(400)
            handler.end_headers()
            handler.wfile.write(b'{"error": "Missing question_key, question_pattern, or answer_value"}')
            return

        ans_id = add_candidate_answer(q_key, q_pattern, a_value)
        res_bytes = json.dumps({"status": "success", "id": ans_id}).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)
    except Exception as e:
        logger.error(f"Error handling POST candidate answer: {e}")
        handler.send_response(500)
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

def handle_delete_candidate_answer(handler, answer_id):
    """DELETE /api/candidate-answers/<id> deletes a candidate Q&A rule."""
    from src.database.connection import delete_candidate_answer
    try:
        success = delete_candidate_answer(answer_id)
        res_bytes = json.dumps({"status": "success" if success else "not_found"}).encode("utf-8")
        handler.send_response(200 if success else 404)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(res_bytes)))
        handler.end_headers()
        handler.wfile.write(res_bytes)
    except Exception as e:
        logger.error(f"Error handling DELETE candidate answer: {e}")
        handler.send_response(500)
        handler.end_headers()
        handler.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))

