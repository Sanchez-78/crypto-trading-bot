"""Simple HTTP dashboard server (port 5000) - stdlib only, no Flask"""
import json
import logging
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger(__name__)

_current_metrics = {}
_metrics_lock = threading.RLock()

class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP handler for /api/metrics endpoint."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/api/metrics":
            with _metrics_lock:
                data = json.dumps(_current_metrics or {})
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(data.encode())
        elif self.path == "/api/health":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "timestamp": time.time()}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress HTTP server logs."""
        pass

def start_dashboard_server(port: int = 5000):
    """Start simple HTTP dashboard server in background thread."""
    def run_server():
        try:
            server = HTTPServer(("0.0.0.0", port), MetricsHandler)
            log.info("[DASHBOARD_HTTP] Server started on port %d", port)
            server.serve_forever()
        except Exception as e:
            log.exception("[DASHBOARD_HTTP_ERROR] Failed to start: %s", e)

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    return thread
