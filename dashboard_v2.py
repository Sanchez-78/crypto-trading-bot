#!/usr/bin/env python3
"""
CryptoMaster Dashboard V2 - Pure Python HTTP Server
No Flask, no venv, no complexity. Just works forever.

Usage:
    python3 dashboard_v2.py

Access:
    http://localhost:9999
    http://78.47.2.198:9999
"""

import json
import urllib.request
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

PORT = 9999
CRYPTO_API = "http://localhost:5000/api/dashboard/metrics"

class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for dashboard."""

    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path

        if path == "/" or path == "/index.html":
            self.serve_html()
        elif path == "/api/metrics":
            self.proxy_metrics()
        else:
            self.send_error(404)

    def serve_html(self):
        """Serve main HTML dashboard."""
        html = b"""<!DOCTYPE html>
<html>
<head>
    <title>CryptoMaster Dashboard V2</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #0f0f1e 100%);
            color: #fff;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 {
            color: #00ff88;
            margin-bottom: 30px;
            font-size: 32px;
        }
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .metric {
            background: rgba(0, 255, 136, 0.1);
            border: 2px solid #00ff88;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }
        .metric-label { font-size: 12px; color: #aaa; text-transform: uppercase; margin-bottom: 10px; }
        .metric-value { font-size: 28px; font-weight: bold; color: #00ff88; }
        .status {
            background: rgba(0, 255, 136, 0.15);
            border-left: 4px solid #00ff88;
            padding: 15px;
            border-radius: 4px;
            margin-top: 20px;
        }
        .error {
            background: rgba(255, 100, 100, 0.2);
            border: 2px solid #ff6464;
            color: #ff9999;
            padding: 15px;
            border-radius: 4px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🤖 CryptoMaster Dashboard V2</h1>
        <div id="content">Loading...</div>
    </div>

    <script>
        const API_URL = '/api/metrics';

        async function updateDashboard() {
            try {
                const response = await fetch(API_URL);
                if (!response.ok) throw new Error('API error');
                const data = await response.json();

                const html = `
                    <div class="metrics">
                        <div class="metric">
                            <div class="metric-label">Closed Trades</div>
                            <div class="metric-value">${data.closed_trades || 0}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Profit Factor</div>
                            <div class="metric-value">${(data.profit_factor || 0).toFixed(2)}x</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Win Rate</div>
                            <div class="metric-value">${(data.win_rate_pct || 0).toFixed(1)}%</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Open Positions</div>
                            <div class="metric-value">${data.open_positions || 0}</div>
                        </div>
                        <div class="metric">
                            <div class="metric-label">Net P&L</div>
                            <div class="metric-value">${(data.net_pnl || 0).toFixed(8)}</div>
                        </div>
                    </div>
                    <div class="status">
                        <strong>✅ Dashboard V2 Live</strong><br>
                        <small>Updated: ${new Date().toLocaleTimeString()}</small><br>
                        <small>Cryptomaster: localhost:5000 ✓</small>
                    </div>
                `;
                document.getElementById('content').innerHTML = html;
            } catch (error) {
                document.getElementById('content').innerHTML = `
                    <div class="error">
                        <strong>⚠️ Connection Error</strong><br>
                        ${error.message}<br>
                        <small>Retrying in 5 seconds...</small>
                    </div>
                `;
            }
        }

        // Update immediately and then every 5 seconds
        updateDashboard();
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>"""

        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(html))
        self.end_headers()
        self.wfile.write(html)

    def proxy_metrics(self):
        """Proxy cryptomaster metrics API."""
        try:
            response = urllib.request.urlopen(CRYPTO_API, timeout=5)
            data = response.read().decode()

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Content-Length', len(data))
            self.end_headers()
            self.wfile.write(data.encode())
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-type', 'application/json')
            error_data = json.dumps({"error": str(e)})
            self.send_header('Content-Length', len(error_data))
            self.end_headers()
            self.wfile.write(error_data.encode())

    def log_message(self, format, *args):
        """Suppress request logging."""
        pass

def start_server():
    """Start the HTTP server."""
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"🚀 Dashboard V2 listening on http://0.0.0.0:{PORT}")
    print(f"📱 Access: http://localhost:{PORT}")
    print(f"🌐 Remote: http://78.47.2.198:{PORT}")
    print(f"⚡ Proxying cryptomaster API from {CRYPTO_API}")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n✅ Dashboard stopped")
        server.server_close()

if __name__ == '__main__':
    start_server()
