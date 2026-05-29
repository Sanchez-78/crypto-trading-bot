"""Simple HTTP API server for V5 Bot metrics — no external dependencies."""

import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for metrics endpoints."""

    # Class variable to hold collector (set by server)
    collector = None

    def do_GET(self):
        """Handle GET requests."""
        try:
            if self.path == "/health":
                self._handle_health()
            elif self.path == "/metrics":
                self._handle_metrics()
            elif self.path == "/metrics/learning-history":
                self._handle_learning_history()
            elif self.path == "/metrics/signals":
                self._handle_signals()
            elif self.path == "/metrics/firebase":
                self._handle_firebase()
            else:
                self._send_json({"error": f"Unknown endpoint: {self.path}"}, 404)
        except Exception as e:
            logger.error(f"Handler error: {e}")
            self._send_json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

    def _send_json(self, data: Dict[str, Any], status_code: int = 200) -> None:
        """Send JSON response."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        response = json.dumps(data).encode('utf-8')
        self.wfile.write(response)

    def _handle_health(self) -> None:
        """GET /health - Simple health check."""
        response = {
            "status": "healthy",
            "running": True,
            "feed_connected": True,
            "firebase_quota_ok": True,
        }
        self._send_json(response, 200)

    def _handle_metrics(self) -> None:
        """GET /metrics - Complete metrics snapshot."""
        if not self.collector:
            self._send_json({"error": "Collector not initialized"}, 503)
            return

        try:
            metrics = self.collector.collect()
            response = {
                "running": metrics.running,
                "epoch_id": metrics.epoch_id,
                "timestamp": metrics.timestamp,
                "open_positions": metrics.open_positions,
                "open_notional_usd": metrics.open_notional_usd,
                "trades_closed": metrics.trades_closed,
                "entries_attempted": metrics.entries_attempted,
                "entries_successful": metrics.entries_successful,
                "entries_rejected_by_gate": metrics.entries_rejected_by_gate,
                "total_net_pnl_usd": metrics.total_net_pnl_usd,
                "net_pnl_pct": getattr(metrics, "net_pnl_pct", None),
                "win_rate": getattr(metrics, "win_rate", None),
                "profit_factor": getattr(metrics, "profit_factor", None),
                "quota_state": metrics.quota_state,
                "quota_reads_used": metrics.quota_reads_used,
                "quota_reads_limit": metrics.quota_reads_limit,
                "quota_writes_used": metrics.quota_writes_used,
                "quota_writes_limit": metrics.quota_writes_limit,
                "feed_connected": metrics.feed_connected,
                "symbols_with_data": metrics.symbols_with_data,
                "uptime_seconds": getattr(metrics, "uptime_seconds", 0),
                "signals": getattr(metrics, "signals", {}),
            }
            self._send_json(response, 200)
        except Exception as e:
            import traceback
            logger.error(f"Metrics collection error: {e}")
            logger.error(traceback.format_exc())
            self._send_json({"error": str(e), "type": type(e).__name__}, 500)

    def _handle_learning_history(self) -> None:
        """GET /metrics/learning-history - Trading and learning history."""
        if not self.collector:
            self._send_json({"error": "Collector not initialized"}, 503)
            return

        try:
            history = self.collector.get_learning_history()
            self._send_json(history, 200)
        except Exception as e:
            logger.error(f"Learning history error: {e}")
            self._send_json({"error": str(e)}, 500)

    def _handle_signals(self) -> None:
        """GET /metrics/signals - Current trading signals."""
        if not self.collector:
            self._send_json({"error": "Collector not initialized"}, 503)
            return

        try:
            signals = self.collector.get_signals()
            self._send_json(signals, 200)
        except Exception as e:
            logger.error(f"Signals error: {e}")
            self._send_json({"error": str(e)}, 500)

    def _handle_firebase(self) -> None:
        """GET /metrics/firebase - Firebase quota and health."""
        if not self.collector:
            self._send_json({"error": "Collector not initialized"}, 503)
            return

        try:
            firebase = self.collector.get_firebase_status()
            self._send_json(firebase, 200)
        except Exception as e:
            logger.error(f"Firebase status error: {e}")
            self._send_json({"error": str(e)}, 500)


class MetricsHTTPServer:
    """HTTP server for V5 Bot metrics — uses Python's built-in HTTPServer."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def set_collector(self, collector) -> None:
        """Set the metrics collector."""
        MetricsHandler.collector = collector

    def start(self) -> None:
        """Start HTTP server in background thread."""
        try:
            self.server = HTTPServer((self.host, self.port), MetricsHandler)
            self.thread = threading.Thread(
                target=self.server.serve_forever,
                daemon=True,
            )
            self.thread.start()
            logger.info(f"Metrics HTTP server started on {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to start HTTP server: {e}")
            raise

    def stop(self) -> None:
        """Stop HTTP server."""
        if self.server:
            self.server.shutdown()
            logger.info("Metrics HTTP server stopped")

    def run(self, debug: bool = False) -> None:
        """Run server (blocking)."""
        try:
            if not self.server:
                self.server = HTTPServer((self.host, self.port), MetricsHandler)
            logger.info(f"Metrics HTTP server running on {self.host}:{self.port}")
            self.server.serve_forever()
        except Exception as e:
            logger.error(f"HTTP server error: {e}")
