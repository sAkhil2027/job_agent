from http.server import BaseHTTPRequestHandler
import logging
from src.server.handlers import serve_static_file, handle_parse_resume

logger = logging.getLogger(__name__)

class Router(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Forward http.server logs to standard python logger
        logger.info("%s - - %s" % (self.address_string(), format % args))

    def do_GET(self):
        """Route GET requests."""
        # Simple health check endpoint
        if self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
            return

        # Observability Metrics endpoint
        if self.path == "/api/metrics":
            import json
            from src.services.metrics import MetricsTracker
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(MetricsTracker.get_metrics()).encode("utf-8"))
            return

        # Server-Sent Events for agent log streaming
        if self.path == "/api/agent/stream":
            from src.server.handlers import handle_agent_stream
            handle_agent_stream(self)
            return

        # Candidate Q&A Database Rules GET endpoint
        if self.path == "/api/candidate-answers":
            from src.server.handlers import handle_get_candidate_answers
            handle_get_candidate_answers(self)
            return

        # Serve static assets
        # Strip leading slash for relative filesystem lookup
        path = self.path.lstrip("/")
        serve_static_file(self, path)

    def do_POST(self):
        """Route POST requests."""
        if self.path == "/api/candidate-answers":
            from src.server.handlers import handle_add_candidate_answer
            content_length = int(self.headers.get('Content-Length', 0))
            body_bytes = self.rfile.read(content_length)
            handle_add_candidate_answer(self, body_bytes)
            return

        if self.path == "/api/parse-resume":
            content_length = int(self.headers.get('Content-Length', 0))
            content_type = self.headers.get('Content-Type', '')
            
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Empty body"}')
                return
                
            # Read post body bytes
            body_bytes = self.rfile.read(content_length)
            handle_parse_resume(self, body_bytes, content_type)
            return

        if self.path == "/api/match-jobs":
            from src.server.handlers import handle_match_jobs
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Empty body"}')
                return
            body_bytes = self.rfile.read(content_length)
            handle_match_jobs(self, body_bytes)
            return

        if self.path == "/api/detailed-explanation":
            from src.server.handlers import handle_detailed_explanation
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Empty body"}')
                return
            body_bytes = self.rfile.read(content_length)
            handle_detailed_explanation(self, body_bytes)
            return

        if self.path == "/api/apply-job":
            from src.server.handlers import handle_apply_job
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "Empty body"}')
                return
            body_bytes = self.rfile.read(content_length)
            handle_apply_job(self, body_bytes)
            return

        # Route not found
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error": "Not Found"}')

    def do_DELETE(self):
        """Route DELETE requests."""
        if self.path.startswith("/api/candidate-answers/"):
            from src.server.handlers import handle_delete_candidate_answer
            answer_id = self.path.replace("/api/candidate-answers/", "").strip()
            handle_delete_candidate_answer(self, answer_id)
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error": "Not Found"}')

