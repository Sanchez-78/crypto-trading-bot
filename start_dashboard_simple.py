#!/usr/bin/env python3
"""
Simple standalone dashboard - ALWAYS WORKS.
No venv, no systemd, no imports except Flask.
Run: python3 start_dashboard_simple.py
"""

import os
import sys
import json
import subprocess
from datetime import datetime

# Ensure Flask is available
try:
    from flask import Flask, jsonify
except ImportError:
    print("Installing Flask...")
    subprocess.run([sys.executable, "-m", "pip", "install", "flask", "-q"])
    from flask import Flask, jsonify

app = Flask(__name__)

@app.route('/api/dashboard/metrics')
def metrics():
    """Return dashboard metrics from cryptomaster."""
    try:
        # Try to get from cryptomaster API on port 5000
        import urllib.request
        response = urllib.request.urlopen('http://localhost:5000/api/dashboard/metrics', timeout=5)
        data = json.loads(response.read().decode())
        return jsonify(data)
    except Exception as e:
        # Fallback to defaults
        return jsonify({
            "closed_trades": 0,
            "profit_factor": 0.0,
            "win_rate_pct": 0.0,
            "net_pnl": 0.0,
            "open_positions": 0,
            "last_update": datetime.now().isoformat(),
            "error": str(e)[:100]
        })

@app.route('/')
def index():
    """Simple HTML dashboard."""
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>CryptoMaster Dashboard</title>
        <style>
            body { font-family: Arial; background: #1a1a1a; color: #fff; margin: 20px; }
            h1 { color: #00ff88; }
            .metric { display: inline-block; margin: 10px; padding: 10px; background: #222; border-radius: 5px; }
            .value { font-size: 20px; font-weight: bold; color: #00ff88; }
        </style>
    </head>
    <body>
        <h1>🤖 CryptoMaster Dashboard</h1>
        <div id="metrics"></div>
        <script>
            async function updateMetrics() {
                try {
                    const res = await fetch('/api/dashboard/metrics');
                    const data = await res.json();
                    document.getElementById('metrics').innerHTML = `
                        <div class="metric">Closed: <div class="value">${data.closed_trades}</div></div>
                        <div class="metric">PF: <div class="value">${data.profit_factor.toFixed(2)}x</div></div>
                        <div class="metric">WR: <div class="value">${data.win_rate_pct.toFixed(1)}%</div></div>
                        <div class="metric">Open: <div class="value">${data.open_positions}</div></div>
                    `;
                } catch(e) {
                    document.getElementById('metrics').innerHTML = '<p>Loading...</p>';
                }
            }
            setInterval(updateMetrics, 5000);
            updateMetrics();
        </script>
    </body>
    </html>
    '''

if __name__ == '__main__':
    print("🚀 Dashboard running on http://0.0.0.0:5001")
    app.run(host='0.0.0.0', port=5001, debug=False)
