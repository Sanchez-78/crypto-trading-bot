"""Simple HTTP dashboard server (port 5000) - V10.6"""
import json
import logging
import threading
import time
from flask import Flask, jsonify

log = logging.getLogger(__name__)

# Shared state
_current_metrics = {}
_metrics_lock = threading.RLock()

app = Flask(__name__)

@app.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Return current dashboard metrics."""
    with _metrics_lock:
        return jsonify(_current_metrics)

@app.route("/api/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok", "timestamp": time.time()})

def update_metrics(metrics: dict):
    """Update dashboard metrics (called from main loop)."""
    global _current_metrics
    with _metrics_lock:
        _current_metrics = metrics.copy()

def start_dashboard_server(port: int = 5000):
    """Start Flask dashboard server in background thread."""
    def run_flask():
        try:
            app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
        except Exception as e:
            log.exception("[DASHBOARD_HTTP_ERROR] Failed to start: %s", e)

    thread = threading.Thread(target=run_flask, daemon=True)
    thread.start()
    log.info("[DASHBOARD_HTTP] Started on port %d", port)
    return thread
