#!/usr/bin/env python3
"""Simple dashboard that reads DIRECTLY from database - bypasses broken bot API"""

import sqlite3
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import time

class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/metrics':
            self.send_metrics()
        else:
            self.send_response(404)
            self.end_headers()

    def send_metrics(self):
        """Send metrics directly from database"""
        try:
            db = sqlite3.connect("/opt/cryptomaster/local_learning_storage/learning_database.sqlite")
            c = db.cursor()

            # Get stats
            c.execute("""
                SELECT COUNT(*),
                       SUM(CASE WHEN pnl_pct>0 THEN 1 ELSE 0 END),
                       SUM(pnl_usd),
                       MAX(exit_ts)
                FROM trades
            """)
            total, wins, pnl, latest_ts = c.fetchone()

            # Get recent trades
            c.execute("""
                SELECT trade_id, symbol, exit_reason, exit_ts, pnl_pct
                FROM trades ORDER BY exit_ts DESC LIMIT 20
            """)
            recent = c.fetchall()

            db.close()

            wr = (wins/total*100) if total else 0

            data = {
                "closed_trades": total,
                "win_rate_pct": round(wr, 2),
                "net_pnl_usd": round(pnl or 0, 2),
                "recent_trades": [
                    {"trade_id": t[0], "symbol": t[1], "reason": t[2], "exit_ts": t[3], "pnl_pct": t[4]}
                    for t in recent
                ],
                "timestamp": int(time.time()),
                "source": "database"
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def log_message(self, format, *args):
        pass  # Suppress logs

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 3333), MetricsHandler)
    print("[DASHBOARD] Running on http://0.0.0.0:3333/api/metrics")
    server.serve_forever()
