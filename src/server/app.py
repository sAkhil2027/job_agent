import os
import json
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Response, UploadFile, File, HTTPException, Depends, Security, status
from fastapi.security.api_key import APIKeyHeader
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from src.config import Config
from src.database.connection import (
    initialize_database,
    get_all_candidate_answers,
    add_candidate_answer,
    delete_candidate_answer
)
from src.services.metrics import MetricsTracker
from src.parsers.resume import ResumeParser
from src.services.agent import agent_instance

logger = logging.getLogger("app")

# API Key Security Header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: Optional[str] = Security(api_key_header), request: Request = None):
    """
    Validates API key if Config.API_KEY is configured.
    Supports 'X-API-Key' header or 'Authorization: Bearer <key>'.
    If Config.API_KEY is not set (empty), authentication is bypassed for development.
    """
    expected_key = getattr(Config, "API_KEY", "")
    if not expected_key:
        return True  # Dev mode: open access

    # Check X-API-Key header
    if api_key and api_key == expected_key:
        return True

    # Check Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization", "") if request else ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token == expected_key:
            return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events for FastAPI."""
    logger.info("Initializing application resources...")
    Config.validate()
    initialize_database()

    # Optional in-process workers for local development
    enable_workers = os.getenv("ENABLE_IN_PROCESS_WORKERS", str(getattr(Config, "ENABLE_IN_PROCESS_WORKERS", "true"))).lower() in ("true", "1", "yes")
    if enable_workers:
        logger.info("Starting in-process background matching agent...")
        if not agent_instance.is_alive():
            agent_instance.start()

    yield

    logger.info("Shutting down application...")
    if enable_workers:
        agent_instance.stop()


app = FastAPI(
    title="Autonomous Job Matcher API",
    openapi_tags=[{"name": "Core", "description": "Core matching and parsing endpoints"}, {"name": "Agent", "description": "Autonomous background agent stream and control"}],
    description="Production-grade AI-powered Resume Parser and Autonomous Job Matcher",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint for cloud load balancers and container orchestrators."""
    return {"status": "healthy"}


@app.get("/api/metrics", dependencies=[Depends(verify_api_key)])
async def get_metrics():
    """Observability metrics endpoint."""
    return MetricsTracker.get_metrics()


@app.get("/api/candidate-answers", dependencies=[Depends(verify_api_key)])
async def get_candidate_answers():
    """Returns all pre-stored candidate Q&A rules."""
    try:
        answers = get_all_candidate_answers()
        return {"answers": answers}
    except Exception as e:
        logger.error(f"Error fetching candidate answers: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/candidate-answers", dependencies=[Depends(verify_api_key)])
async def create_candidate_answer(payload: Dict[str, Any]):
    """Creates or updates a candidate Q&A rule."""
    q_key = payload.get("question_key")
    q_pattern = payload.get("question_pattern")
    a_value = payload.get("answer_value")

    if not q_key or not q_pattern or not a_value:
        raise HTTPException(status_code=400, detail="Missing question_key, question_pattern, or answer_value")

    try:
        ans_id = add_candidate_answer(q_key, q_pattern, a_value)
        return {"status": "success", "id": ans_id}
    except Exception as e:
        logger.error(f"Error creating candidate answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/candidate-answers/{answer_id}", dependencies=[Depends(verify_api_key)])
async def remove_candidate_answer(answer_id: str):
    """Deletes a candidate Q&A rule by ID."""
    try:
        success = delete_candidate_answer(answer_id)
        if not success:
            raise HTTPException(status_code=404, detail="Answer not found")
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting candidate answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/parse-resume", dependencies=[Depends(verify_api_key)])
async def parse_resume(file: UploadFile = File(...)):
    """
    Parses uploaded resume PDF with 10MB size limit and PDF magic header validation.
    """
    max_size = getattr(Config, "MAX_UPLOAD_SIZE", 10 * 1024 * 1024)

    # Read file content safely
    contents = await file.read()
    if len(contents) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is {max_size // (1024 * 1024)}MB."
        )

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate PDF magic header (%PDF-)
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file format. Only valid PDF files starting with %PDF- are supported."
        )

    filename = file.filename or "resume.pdf"
    try:
        parser = ResumeParser()
        result = parser.parse_and_save(filename, contents)
        return result
    except Exception as e:
        logger.error(f"Error parsing resume {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/match-jobs", dependencies=[Depends(verify_api_key)])
async def match_jobs(request: Request):
    """Matches active resume against live jobs."""
    try:
        body = await request.body()
        from src.server.handlers import handle_match_jobs
        # Re-use existing handler logic
        class DummyHandler:
            def __init__(self):
                self.headers = {}
                self.status_code = 200
                self.response_body = b""
                self.response_headers = {}

            def send_response(self, code):
                self.status_code = code

            def send_header(self, k, v):
                self.response_headers[k] = v

            def end_headers(self):
                pass

            class WFile:
                def __init__(self, parent):
                    self.parent = parent
                def write(self, b):
                    self.parent.response_body += b
            @property
            def wfile(self):
                return DummyHandler.WFile(self)

        dummy = DummyHandler()
        handle_match_jobs(dummy, body)
        return Response(content=dummy.response_body, status_code=dummy.status_code, media_type="application/json")
    except Exception as e:
        logger.error(f"Error matching jobs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/detailed-explanation", dependencies=[Depends(verify_api_key)])
async def detailed_explanation(payload: Dict[str, Any]):
    """Generates deep AI explanation for a match."""
    resume_id = payload.get("resume_id")
    job_id = payload.get("job_id")
    if not resume_id or not job_id:
        raise HTTPException(status_code=400, detail="Missing resume_id or job_id")

    try:
        from src.services.explanation_service import DetailedExplanationService
        explanation = DetailedExplanationService.get_detailed_explanation(resume_id, job_id)
        return {
            "resume_id": resume_id,
            "job_id": job_id,
            "detailed_explanation": explanation
        }
    except Exception as e:
        logger.error(f"Error generating detailed explanation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/apply-job", dependencies=[Depends(verify_api_key)])
async def apply_job(payload: Dict[str, Any]):
    """Enqueues job application for automated agent worker."""
    resume_id = payload.get("resume_id")
    job_id = payload.get("job_id")
    if not resume_id or not job_id:
        raise HTTPException(status_code=400, detail="Missing resume_id or job_id")

    try:
        from src.services.application_queue import enqueue_application
        queue_id = enqueue_application(resume_id, job_id)
        agent_instance.log_and_broadcast(
            f"Job application enqueued (ID: {queue_id[:8]}). Autonomous agent worker scheduled to submit application.",
            "status"
        )
        return {
            "status": "success",
            "queue_id": queue_id,
            "message": "Job application enqueued for agent worker."
        }
    except Exception as e:
        logger.error(f"Error enqueuing job application: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent/stream")
async def agent_stream():
    """Server-Sent Events (SSE) stream for real-time agent execution logs."""
    async def event_generator():
        client_queue = agent_instance.register_listener()
        welcome_evt = {
            "time": time.strftime("%H:%M:%S"),
            "message": "Connected to Agent Stream. Listening for events...",
            "type": "status"
        }
        yield f"data: {json.dumps(welcome_evt)}\n\n"

        for history_payload in agent_instance.get_history():
            yield history_payload

        agent_instance.trigger_run()

        try:
            while True:
                try:
                    # Non-blocking poll from thread-safe queue
                    sse_payload = client_queue.get_nowait()
                    yield sse_payload
                except Exception:
                    # Ping event to keep SSE connection alive
                    yield ": ping\n\n"
                    await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
        finally:
            agent_instance.unregister_listener(client_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# Serve Static Frontend Assets (HTML, CSS, JS)
static_dir = os.path.join(Config.BASE_DIR, "src", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    async def index():
        return FileResponse(os.path.join(static_dir, "index.html"))

    @app.get("/{file_path:path}")
    async def serve_static(file_path: str):
        if file_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        target = os.path.join(static_dir, file_path)
        if os.path.exists(target) and os.path.isfile(target):
            return FileResponse(target)
        # Fallback to index.html for single-page application routing
        return FileResponse(os.path.join(static_dir, "index.html"))
