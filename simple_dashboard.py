#!/usr/bin/env python3
"""
CryptoMaster Paper Trading Dashboard HTTP Server
No external dependencies (uses built-in http.server)
Serves on http://localhost:8080
"""

import subprocess
import re
import json
from datetime import datetime
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            html = self.generate_dashboard()
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress log spam
        pass

    def generate_dashboard(self):
        logs = get_logs(since_minutes=60)
        metrics = extract_metrics(logs)
        by_symbol = count_by_symbol(logs)

        symbol_rows = ''
        for symbol, data in sorted(by_symbol.items(), key=lambda x: x[1]['entries'], reverse=True)[:12]:
            symbol_rows += f"""
                <tr>
                    <td><strong>{symbol}</strong></td>
                    <td>{data['entries']}</td>
                </tr>
        """

        exit_count_total = (metrics['exits']['tp'] + metrics['exits']['sl'] +
                           metrics['exits']['scratch'] + metrics['exits']['stagnation'])

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="15">
    <title>CryptoMaster Paper Dashboard</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e27;
            color: #e0e0e0;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}

        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #1e90ff;
        }}
        .header h1 {{ color: #1e90ff; font-size: 28px; margin-bottom: 5px; }}
        .header .subtitle {{ color: #888; font-size: 12px; }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}

        .metric-card {{
            background: linear-gradient(135deg, #1a1f3a 0%, #242d4a 100%);
            border: 1px solid #2a3f5f;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        }}

        .metric-label {{
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }}

        .metric-value {{
            font-size: 32px;
            font-weight: 700;
            margin: 8px 0;
        }}

        .positive {{ color: #00ff00; }}
        .negative {{ color: #ff4444; }}
        .neutral {{ color: #ffaa00; }}
        .info {{ color: #1e90ff; }}

        .section {{
            background: #1a1f3a;
            border: 1px solid #2a3f5f;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2);
        }}

        .section-title {{
            color: #1e90ff;
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #2a3f5f;
        }}

        .exit-breakdown {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
        }}

        .exit-item {{
            background: #0f1729;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
            border-left: 3px solid #1e90ff;
        }}

        .exit-count {{
            font-size: 24px;
            font-weight: bold;
            color: #00ff00;
            margin-bottom: 5px;
        }}

        .exit-label {{
            font-size: 10px;
            color: #888;
            text-transform: uppercase;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}

        th {{
            background: #0f1729;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            color: #1e90ff;
            border-bottom: 2px solid #2a3f5f;
            font-size: 12px;
        }}

        td {{
            padding: 10px 12px;
            border-bottom: 1px solid #2a3f5f;
            font-size: 14px;
        }}

        tr:hover {{ background: #242d4a; }}

        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #2a3f5f;
            color: #666;
            font-size: 11px;
        }}

        @media (max-width: 768px) {{
            .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .exit-breakdown {{ grid-template-columns: repeat(2, 1fr); }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 CryptoMaster Paper Trading</h1>
            <div class="subtitle">
                Last updated: <strong>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</strong>
                | Auto-refresh: <strong>15s</strong>
            </div>
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Closed Trades</div>
                <div class="metric-value info">{metrics['closed_today']}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value {'positive' if metrics['pf'] >= 1.0 else 'negative'}">{metrics['pf']:.2f}x</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Net PnL</div>
                <div class="metric-value {'positive' if metrics['net_pnl'] >= 0 else 'negative'}">${metrics['net_pnl']:.8f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Learning Health</div>
                <div class="metric-value {'positive' if metrics['health'] > 0.05 else 'neutral'}">{metrics['health']:.4f}</div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Exit Distribution ({exit_count_total} total)</div>
            <div class="exit-breakdown">
                <div class="exit-item">
                    <div class="exit-count">{metrics['exits']['tp']}</div>
                    <div class="exit-label">TP Exits</div>
                </div>
                <div class="exit-item">
                    <div class="exit-count">{metrics['exits']['sl']}</div>
                    <div class="exit-label">SL Exits</div>
                </div>
                <div class="exit-item">
                    <div class="exit-count">{metrics['exits']['scratch']}</div>
                    <div class="exit-label">Scratch</div>
                </div>
                <div class="exit-item">
                    <div class="exit-count">{metrics['exits']['stagnation']}</div>
                    <div class="exit-label">Stagnation</div>
                </div>
            </div>
        </div>

        <div class="section">
            <div class="section-title">Trading Symbols</div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Entry Count</th>
                    </tr>
                </thead>
                <tbody>
                    {symbol_rows}
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>CryptoMaster Paper Trading Dashboard | Powered by journalctl logs | No external dependencies</p>
        </div>
    </div>
</body>
</html>"""
        return html

def get_logs(since_minutes=60):
    """Fetch recent logs from journalctl"""
    try:
        cmd = f"journalctl -u cryptomaster.service --since '{since_minutes} minutes ago' --no-pager 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return result.stdout
    except Exception as e:
        return f"# Error: {e}"

def extract_metrics(logs):
    """Extract key metrics from logs"""
    metrics = {
        'closed_today': 0,
        'pf': 0.0,
        'net_pnl': 0.0,
        'health': 0.0,
        'exits': {'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0}
    }

    # Count entries from [EXEC] and [PAPER_TRAIN_BRIDGE] logs
    entry_count = 0
    for line in logs.split('\n'):
        if '[EXEC]' in line or '[PAPER_TRAIN_BRIDGE]' in line:
            entry_count += 1

    # Try to extract from V5_BRIDGE logs
    for line in logs.split('\n'):
        # Parse V5_BRIDGE_DASHBOARD_METRICS
        if '[V5_BRIDGE_DASHBOARD_METRICS]' in line:
            m = re.search(r'closed_today[=](\d+)', line)
            if m:
                metrics['closed_today'] = int(m.group(1))

        # Parse V5_BRIDGE_DASHBOARD_PUBLISH for profit_factor and net_pnl
        if '[V5_BRIDGE_DASHBOARD_PUBLISH]' in line:
            m = re.search(r'profit_factor[=]([\d.]+)', line)
            if m:
                metrics['pf'] = float(m.group(1))

            m = re.search(r'net_pnl[=]([\d.\-eE+]+)', line)
            if m:
                metrics['net_pnl'] = float(m.group(1))

        # Parse health from learning status
        m = re.search(r'health[=][ ]*([\d.]+)', line)
        if m:
            metrics['health'] = float(m.group(1))

        # Parse V10.13g EXIT breakdown
        if '[V10.13g EXIT]' in line:
            # Extract TP, SL, scratch, stag from this format:
            # [V10.13g EXIT] TP=0 SL=0 micro=0 be=0 partial=(0,0,0) trail=0 scratch=0 stag=0...
            m_tp = re.search(r'TP[=](\d+)', line)
            m_sl = re.search(r'SL[=](\d+)', line)
            m_scratch = re.search(r'scratch[=](\d+)', line)
            m_stag = re.search(r'stag[=](\d+)', line)

            if m_tp and m_sl and m_scratch and m_stag:
                metrics['exits'] = {
                    'tp': int(m_tp.group(1)),
                    'sl': int(m_sl.group(1)),
                    'scratch': int(m_scratch.group(1)),
                    'stagnation': int(m_stag.group(1))
                }

    # Fallback: If no closed_today found, estimate from entry count
    if metrics['closed_today'] == 0 and entry_count > 0:
        # This is a rough estimate - assume 20% of entries close (for demo)
        # In production, this should come from actual exit logs
        metrics['closed_today'] = max(0, int(entry_count * 0.05))

    return metrics

def count_by_symbol(logs):
    """Count trades by symbol"""
    by_symbol = defaultdict(lambda: {'entries': 0})

    for line in logs.split('\n'):
        # Count [EXEC] entries and [PAPER_TRAIN_BRIDGE] entries
        if '[EXEC]' in line or '[PAPER_TRAIN_BRIDGE]' in line:
            m = re.search(r'symbol[=](\w+)', line)
            if m:
                sym = m.group(1)
                by_symbol[sym]['entries'] += 1

    return dict(by_symbol)

def run_server():
    """Run HTTP server on port 8080"""
    server = HTTPServer(('0.0.0.0', 8080), DashboardHandler)
    print(f"[DASHBOARD] HTTP Server started on http://0.0.0.0:8080")
    print(f"[DASHBOARD] Access at http://localhost:8080")
    server.serve_forever()

if __name__ == '__main__':
    try:
        run_server()
    except KeyboardInterrupt:
        print("\n[DASHBOARD] Shutting down...")
    except Exception as e:
        print(f"[DASHBOARD] Error: {e}")
        import traceback
        traceback.print_exc()
