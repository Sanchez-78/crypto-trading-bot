#!/usr/bin/env python3
"""Ultra-minimal dashboard - plain HTML, easy to debug."""

import sqlite3
import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            html = self.generate_simple_html()
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/api/metrics.json':
            metrics = self.get_metrics()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(metrics).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def get_metrics(self):
        db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'

        metrics = {
            'closed_trades': 0,
            'pf': 0.0,
            'wr': 0.0,
            'net_pnl': 0.0,
            'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0,
            'trades': []
        }

        if not os.path.exists(db_path):
            return metrics

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute('SELECT COUNT(*), SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END), SUM(pnl_usd) FROM trades')
            row = c.fetchone()
            total = row[0] or 0
            wins = row[1] or 0
            net = row[2] or 0.0
            losses = total - wins
            pf = wins / (losses + 0.0001) if losses > 0 else (1.0 if wins > 0 else 0.0)

            metrics['closed_trades'] = total
            metrics['pf'] = round(pf, 2)
            metrics['wr'] = round(100 * wins / total if total > 0 else 0, 1)
            metrics['net_pnl'] = round(net, 8)

            c.execute('SELECT exit_reason, COUNT(*) FROM trades GROUP BY exit_reason')
            for reason, cnt in c.fetchall():
                reason = (reason or '').lower()
                if 'tp' in reason: metrics['tp'] = cnt
                elif 'sl' in reason: metrics['sl'] = cnt
                elif 'scratch' in reason: metrics['scratch'] = cnt
                elif 'stag' in reason: metrics['stagnation'] = cnt
                elif 'timeout' in reason: metrics['timeout'] = cnt

            c.execute('SELECT symbol, entry_price, exit_price, pnl_usd, exit_reason FROM trades ORDER BY exit_ts DESC LIMIT 20')
            for row in c.fetchall():
                metrics['trades'].append({
                    'symbol': row['symbol'],
                    'entry': row['entry_price'],
                    'exit': row['exit_price'],
                    'pnl': row['pnl_usd'],
                    'reason': row['exit_reason']
                })

            conn.close()
        except Exception as e:
            metrics['error'] = str(e)

        return metrics

    def generate_simple_html(self):
        metrics = self.get_metrics()

        trades_html = ''
        for t in metrics.get('trades', []):
            trades_html += f"<tr><td>{t['symbol']}</td><td>{t['entry']:.2f}</td><td>{t['exit']:.2f}</td><td>{t['pnl']:.8f}</td><td>{t['reason']}</td></tr>\n"

        return f"""<!DOCTYPE html>
<html>
<head>
    <title>CryptoMaster Dashboard</title>
    <meta http-equiv="refresh" content="10">
    <style>
        body {{ font-family: Arial, sans-serif; background: #000; color: #0f0; padding: 20px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #0f0; padding: 10px; text-align: left; }}
        th {{ background: #1a1a1a; }}
        .metric {{ font-size: 32px; font-weight: bold; color: #00ff00; }}
        .label {{ color: #888; font-size: 12px; }}
        h1 {{ color: #0f0; }}
        .metrics {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin: 20px 0; }}
        .card {{ background: #1a1a1a; padding: 20px; border: 1px solid #0f0; }}
    </style>
</head>
<body>
    <h1>CryptoMaster Paper Trading Dashboard</h1>

    <div class="metrics">
        <div class="card">
            <div class="label">CLOSED TRADES</div>
            <div class="metric">{metrics['closed_trades']}</div>
        </div>
        <div class="card">
            <div class="label">PROFIT FACTOR</div>
            <div class="metric">{metrics['pf']:.2f}x</div>
        </div>
        <div class="card">
            <div class="label">WIN RATE</div>
            <div class="metric">{metrics['wr']:.1f}%</div>
        </div>
    </div>

    <div class="metrics">
        <div class="card">
            <div class="label">NET PnL</div>
            <div class="metric">${{metrics['net_pnl']:.8f}}</div>
        </div>
        <div class="card">
            <div class="label">TP EXITS</div>
            <div class="metric">{metrics['tp']}</div>
        </div>
        <div class="card">
            <div class="label">SL EXITS</div>
            <div class="metric">{metrics['sl']}</div>
        </div>
    </div>

    <h2>Recent Trades</h2>
    <table>
        <tr>
            <th>Symbol</th>
            <th>Entry</th>
            <th>Exit</th>
            <th>PnL</th>
            <th>Exit Reason</th>
        </tr>
        {trades_html}
    </table>

    <p style="color: #888; font-size: 12px;">Refreshes every 10 seconds | API: http://78.47.2.198:8080/api/metrics.json</p>
</body>
</html>"""

    def log_message(self, format, *args):
        pass  # Suppress logs

if __name__ == '__main__':
    print("🚀 Starting MINIMAL dashboard on port 8081...")
    server = HTTPServer(('0.0.0.0', 8081), Handler)
    print("   Access at: http://78.47.2.198:8081/")
    server.serve_forever()
