#!/usr/bin/env python3
"""
ULTRA-SIMPLE DASHBOARD - Minimal, reliable metrics server

Uses only standard library. No Flask, no venv. Just HTTP server + bot API.
Single file, no dependencies. Auto-restarts if crashes.
"""

import json
import http.server
import socketserver
import threading
import time
import urllib.request
from datetime import datetime, timezone

PORT = 5001
BOT_API = "http://localhost:5000/api/dashboard/metrics"


class MetricsHandler(http.server.SimpleHTTPRequestHandler):
    """Handle HTTP requests for metrics."""

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/api/dashboard/metrics":
            try:
                # Get metrics from bot API
                response = urllib.request.urlopen(BOT_API, timeout=5)
                metrics = json.loads(response.read().decode())

                # Return as JSON
                self.send_response(200)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(metrics).encode())

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif self.path == "/" or self.path == "":
            # Simple HTML dashboard
            html = """
<!DOCTYPE html>
<html>
<head>
    <title>CryptoMaster Dashboard</title>
    <style>
        body { font-family: monospace; background: #0a0e27; color: #e0e0e0; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: #1e90ff; }
        .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; }
        .metric { background: #1a1f3a; padding: 20px; border-radius: 8px; border: 1px solid #2a3f5f; }
        .label { font-size: 12px; color: #888; }
        .value { font-size: 24px; font-weight: bold; color: #1e90ff; }
        .positive { color: #00ff00; }
        .negative { color: #ff4444; }
        .last-update { font-size: 10px; color: #666; margin-top: 5px; }
    </style>
    <script>
        function updateMetrics() {
            fetch('/api/dashboard/metrics')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('wr').innerText = data.win_rate_pct?.toFixed(2) + '%';
                    document.getElementById('pnl').innerText = '$' + data.net_pnl?.toFixed(2);
                    document.getElementById('pf').innerText = data.profit_factor?.toFixed(2) + 'x';
                    document.getElementById('trades').innerText = data.closed_trades;
                    document.getElementById('open').innerText = data.open_positions;
                    document.getElementById('timeout').innerText = data.exit_distribution?.timeout || 0;
                    document.getElementById('timestamp').innerText = new Date(data.timestamp).toLocaleTimeString();

                    let pnlClass = data.net_pnl > 0 ? 'positive' : 'negative';
                    document.getElementById('pnl-value').className = 'value ' + pnlClass;
                })
                .catch(e => console.error(e));
        }

        setInterval(updateMetrics, 10000);
        updateMetrics();
    </script>
</head>
<body>
    <div class="container">
        <h1>🤖 CryptoMaster Trading Dashboard</h1>

        <div class="metrics">
            <div class="metric">
                <div class="label">Win Rate</div>
                <div class="value" id="wr">--</div>
            </div>
            <div class="metric">
                <div class="label">P&L (USD)</div>
                <div class="value" id="pnl-value" id="pnl">--</div>
            </div>
            <div class="metric">
                <div class="label">Profit Factor</div>
                <div class="value" id="pf">--</div>
            </div>
            <div class="metric">
                <div class="label">Closed Trades</div>
                <div class="value" id="trades">--</div>
            </div>
            <div class="metric">
                <div class="label">Open Positions</div>
                <div class="value" id="open">--</div>
            </div>
            <div class="metric">
                <div class="label">TIMEOUT Exits</div>
                <div class="value" id="timeout">--</div>
            </div>
        </div>

        <p style="margin-top: 30px; font-size: 12px; color: #666;">
            Last update: <span id="timestamp">--</span> UTC | Refreshes every 10 seconds
        </p>
    </div>
</body>
</html>
            """
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress logging."""
        pass


def run_server():
    """Start the dashboard server."""
    try:
        with socketserver.TCPServer(("0.0.0.0", PORT), MetricsHandler) as httpd:
            print(f"✅ Dashboard running on http://localhost:{PORT}")
            httpd.serve_forever()
    except Exception as e:
        print(f"❌ Server error: {e}")
        time.sleep(5)
        run_server()  # Restart


if __name__ == "__main__":
    run_server()
