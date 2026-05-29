"""Simple HTTP API server for V5 Bot metrics."""

import json
import logging
from typing import Optional
from flask import Flask, jsonify, request
from .metrics_api import MetricsCollector

logger = logging.getLogger(__name__)


class MetricsHTTPServer:
    """HTTP server for V5 Bot metrics API."""

    def __init__(self, host: str = "0.0.0.0", port: int = 5000):
        self.app = Flask(__name__)
        self.host = host
        self.port = port
        self.collector: Optional[MetricsCollector] = None

        # Setup routes
        self.app.add_url_rule("/metrics", "metrics", self.get_metrics)
        self.app.add_url_rule("/health", "health", self.health_check)
        self.app.add_url_rule("/metrics/dashboard", "dashboard", self.get_dashboard)
        self.app.add_url_rule("/metrics/trading", "trading", self.get_trading)
        self.app.add_url_rule("/metrics/firebase", "firebase", self.get_firebase)
        self.app.add_url_rule("/metrics/signals", "signals", self.get_signals)
        self.app.add_url_rule("/metrics/learning-history", "learning_history", self.get_learning_history)

    def set_collector(self, collector: MetricsCollector) -> None:
        """Set the metrics collector."""
        self.collector = collector

    def get_metrics(self):
        """GET /metrics - Complete metrics snapshot."""
        if not self.collector:
            return jsonify({"error": "Collector not initialized"}), 503

        metrics = self.collector.collect()
        return jsonify(metrics.to_dict()), 200

    def health_check(self):
        """GET /health - Simple health check."""
        if not self.collector:
            return jsonify({"status": "unhealthy", "reason": "Collector not initialized"}), 503

        metrics = self.collector.collect()
        status = "healthy" if metrics.running else "stopped"
        return jsonify({
            "status": status,
            "running": metrics.running,
            "feed_connected": metrics.feed_connected,
            "firebase_quota_ok": metrics.quota_state in ["NORMAL", "WARNING"],
        }), 200

    def get_dashboard(self):
        """GET /metrics/dashboard - Dashboard summary metrics."""
        if not self.collector:
            return jsonify({"error": "Collector not initialized"}), 503

        metrics = self.collector.collect()
        return jsonify({
            "status": {
                "running": metrics.running,
                "timestamp": metrics.timestamp,
                "feed_connected": metrics.feed_connected,
                "symbols_with_data": metrics.symbols_with_data,
            },
            "positions": {
                "open": metrics.open_positions,
                "notional_usd": metrics.open_notional_usd,
            },
            "performance": {
                "total_pnl_usd": metrics.total_net_pnl_usd,
                "win_rate": metrics.win_rate,
                "profit_factor": metrics.profit_factor,
            },
            "trading": {
                "entries_attempted": metrics.entries_attempted,
                "entries_successful": metrics.entries_successful,
                "trades_closed": metrics.trades_closed,
            },
        }), 200

    def get_trading(self):
        """GET /metrics/trading - Detailed trading metrics."""
        if not self.collector:
            return jsonify({"error": "Collector not initialized"}), 503

        metrics = self.collector.collect()
        return jsonify({
            "entries": {
                "attempted": metrics.entries_attempted,
                "successful": metrics.entries_successful,
                "rejected_by_gate": metrics.entries_rejected_by_gate,
            },
            "positions": {
                "open_count": metrics.open_positions,
                "open_notional_usd": metrics.open_notional_usd,
                "max_open": metrics.max_open_global,
            },
            "results": {
                "trades_closed": metrics.trades_closed,
                "total_pnl_usd": metrics.total_net_pnl_usd,
                "net_pnl_pct": metrics.net_pnl_pct,
                "win_rate": metrics.win_rate,
                "profit_factor": metrics.profit_factor,
                "average_cost_bps": metrics.average_cost_bps,
            },
            "uptime_seconds": metrics.uptime_seconds,
        }), 200

    def get_firebase(self):
        """GET /metrics/firebase - Firebase quota and sync metrics."""
        if not self.collector:
            return jsonify({"error": "Collector not initialized"}), 503

        metrics = self.collector.collect()
        reads_percent = (metrics.quota_reads_used / metrics.quota_reads_limit * 100) if metrics.quota_reads_limit > 0 else 0
        writes_percent = (metrics.quota_writes_used / metrics.quota_writes_limit * 100) if metrics.quota_writes_limit > 0 else 0

        return jsonify({
            "quota": {
                "reads": {
                    "used": metrics.quota_reads_used,
                    "limit": metrics.quota_reads_limit,
                    "percent_used": round(reads_percent, 1),
                },
                "writes": {
                    "used": metrics.quota_writes_used,
                    "limit": metrics.quota_writes_limit,
                    "percent_used": round(writes_percent, 1),
                },
                "state": metrics.quota_state,
            },
            "sync": {
                "writes": metrics.firebase_writes,
                "failures": metrics.firebase_failures,
            },
        }), 200

    def get_signals(self):
        """GET /metrics/signals - Current signal status for all symbols."""
        if not self.collector:
            return jsonify({"error": "Collector not initialized"}), 503

        metrics = self.collector.collect()
        return jsonify({
            "current_regime": metrics.current_regime,
            "signals": metrics.signals,
            "spreads_bps": metrics.book_spreads,
            "mid_prices": metrics.mid_prices,
            "timestamp": metrics.timestamp,
        }), 200

    def get_learning_history(self):
        """GET /metrics/learning-history - Detailed learning history with all closed trades."""
        if not self.collector:
            return jsonify({"error": "Collector not initialized"}), 503

        learning = self.collector.collect_learning_history()
        return jsonify(learning.to_dict()), 200

    def run(self, debug: bool = False) -> None:
        """Start the HTTP server."""
        logger.info(f"Starting metrics HTTP server on {self.host}:{self.port}")
        self.app.run(host=self.host, port=self.port, debug=debug, use_reloader=False)
