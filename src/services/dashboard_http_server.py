#!/usr/bin/env python3
"""
CryptoMaster Paper Trading Dashboard HTTP Server

Serves live trading metrics from journalctl logs on port 8080
Auto-refreshes every 15 seconds
"""

import subprocess
import json
import re
from datetime import datetime
from collections import defaultdict
from flask import Flask, render_string

app = Flask(__name__)

def write_exits_to_db(logs):
    """Parse [PAPER_EXIT] logs and record trades to SQLite"""
    try:
        import sqlite3
        import re
        import time
        import os

        # Ensure directory exists
        os.makedirs("local_learning_storage", exist_ok=True)

        db = sqlite3.connect("local_learning_storage/learning_database.sqlite", timeout=2)
        cursor = db.cursor()

        # Create table if missing
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                trade_id TEXT UNIQUE,
                symbol TEXT,
                exit_reason TEXT,
                pnl_pct REAL,
                pnl_usd REAL,
                entry_price REAL,
                exit_price REAL,
                exit_ts REAL
            )
        ''')

        # Parse exit logs: [PAPER_EXIT] trade_id=... symbol=... reason=... net_pnl_pct=... outcome=...
        for line in logs.split('\n'):
            if '[PAPER_EXIT]' in line:
                try:
                    # Extract fields from log line
                    trade_id = re.search(r'trade_id=(\S+)', line)
                    symbol = re.search(r'symbol=(\S+)', line)
                    reason = re.search(r'reason=(\S+)', line)
                    pnl_pct = re.search(r'net_pnl_pct=([\-\d.eE+]+)', line)
                    outcome = re.search(r'outcome=(\S+)', line)
                    entry = re.search(r'entry=([\d.]+)', line)
                    exit_p = re.search(r'exit=([\d.]+)', line)
                    hold_s = re.search(r'hold_s=([\d.]+)', line)

                    if all([trade_id, symbol, reason, pnl_pct, outcome, entry, exit_p]):
                        # Calculate pnl_usd from pnl_pct (approximate: assume 1 unit traded)
                        pnl_pct_val = float(pnl_pct.group(1))
                        entry_val = float(entry.group(1))
                        pnl_usd = entry_val * pnl_pct_val / 100.0

                        cursor.execute('''
                            INSERT OR IGNORE INTO trades
                            (trade_id, symbol, exit_reason, pnl_pct, pnl_usd, entry_price, exit_price, exit_ts)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            trade_id.group(1),
                            symbol.group(1),
                            reason.group(1),
                            pnl_pct_val,
                            pnl_usd,
                            entry_val,
                            float(exit_p.group(1)),
                            int(time.time())
                        ))
                except Exception as e:
                    pass  # Skip malformed lines

        db.commit()
        db.close()
    except Exception as e:
        pass  # Fail silently

def get_logs(since_minutes=30):
    """Fetch recent logs from journalctl + generate dashboard metrics from local DB"""
    try:
        cmd = f"journalctl -u cryptomaster.service --since '{since_minutes} minutes ago' --no-pager -q 2>/dev/null || journalctl --since '{since_minutes} minutes ago' --no-pager -q"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        logs = result.stdout

        # V10.22: Write any new [PAPER_EXIT] logs to database
        write_exits_to_db(logs)

        # V10.20: Inject metrics from local database (in case journalctl doesn't have them)
        try:
            import sqlite3
            conn = sqlite3.connect("local_learning_storage/learning_database.sqlite", timeout=2)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                       SUM(pnl_usd) as net_pnl
                FROM trades
                WHERE exit_ts > strftime('%s', 'now', 'start of day')
            """)
            row = cursor.fetchone()
            total = row[0] if row[0] else 0
            wins = row[1] if row[1] else 0
            net_pnl = row[2] if row[2] else 0.0

            # Calculate PF
            pf = 1.0
            if total > 0:
                cursor.execute("SELECT SUM(ABS(pnl_usd)) FROM trades WHERE exit_ts > strftime('%s', 'now', 'start of day') AND pnl_usd > 0")
                wins_pnl = cursor.fetchone()[0] or 0.0
                cursor.execute("SELECT SUM(ABS(pnl_usd)) FROM trades WHERE exit_ts > strftime('%s', 'now', 'start of day') AND pnl_usd < 0")
                losses_pnl = cursor.fetchone()[0] or 0.0
                if losses_pnl > 0:
                    pf = wins_pnl / losses_pnl

            conn.close()

            # Inject synthetic metrics log line
            metrics_line = f"[DASHBOARD_METRICS] closed_today={total} profit_factor={pf:.2f} net_pnl={net_pnl:.8f}\n"
            logs = metrics_line + logs
        except Exception as e:
            pass  # If local DB fails, just use journalctl logs

        return logs
    except Exception as e:
        return f"# Error fetching logs: {e}"

def extract_metrics(logs):
    """Extract key metrics from logs"""
    metrics = {
        'closed_today': 0,
        'pf': 0.0,
        'net_pnl': 0.0,
        'health': 0.0,
        'exits': {'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0}
    }

    for line in logs.split('\n'):
        if 'closed_today=' in line:
            m = re.search(r'closed_today=(\d+)', line)
            if m: metrics['closed_today'] = int(m.group(1))
        if 'profit_factor=' in line:
            m = re.search(r'profit_factor=([\d.]+)', line)
            if m: metrics['pf'] = float(m.group(1))
        if 'net_pnl=' in line:
            m = re.search(r'net_pnl=([\d.\-eE+]+)', line)
            if m: metrics['net_pnl'] = float(m.group(1))
        if 'health=' in line and 'learning' in line.lower():
            m = re.search(r'health=([\d.]+)', line)
            if m: metrics['health'] = float(m.group(1))

        # V10.13g EXIT breakdown
        if 'V10.13g EXIT' in line or 'EXIT' in line and 'TP=' in line:
            m = re.search(r'TP=(\d+).*SL=(\d+).*scratch=(\d+).*stag=(\d+)', line)
            if m:
                metrics['exits'] = {
                    'tp': int(m.group(1)),
                    'sl': int(m.group(2)),
                    'scratch': int(m.group(3)),
                    'stagnation': int(m.group(4))
                }

    return metrics

def count_by_symbol(logs):
    """Count trades by symbol"""
    by_symbol = defaultdict(lambda: {'count': 0, 'entries': 0})

    for line in logs.split('\n'):
        if '[EXEC]' in line or '[PAPER_TRAIN_BRIDGE]' in line:
            m = re.search(r'symbol=(\w+)', line)
            if m:
                sym = m.group(1)
                by_symbol[sym]['entries'] += 1
                by_symbol[sym]['count'] += 1

    # Sort by count descending, take top 12
    sorted_syms = sorted(by_symbol.items(), key=lambda x: x[1]['count'], reverse=True)[:12]
    return dict(sorted_syms)

@app.route('/')
def dashboard():
    """Render dashboard HTML"""
    logs = get_logs(since_minutes=60)
    metrics = extract_metrics(logs)
    by_symbol = count_by_symbol(logs)

    html_template = """<!DOCTYPE html>
<html>
<head>
    <title>CryptoMaster Paper Trading Dashboard</title>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="15">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0a0e27;
            color: #e0e0e0;
            padding: 20px;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            border-bottom: 2px solid #1e90ff;
            padding-bottom: 20px;
        }
        .header h1 { color: #1e90ff; font-size: 28px; }
        .timestamp { color: #888; font-size: 12px; margin-top: 5px; }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }

        .metric-card {
            background: #1a1f3a;
            border: 1px solid #2a3f5f;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }

        .metric-value {
            font-size: 32px;
            font-weight: bold;
            margin: 10px 0;
        }

        .metric-label {
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
        }

        .positive { color: #00ff00; }
        .negative { color: #ff4444; }
        .neutral { color: #ffaa00; }

        .symbol-table {
            background: #1a1f3a;
            border: 1px solid #2a3f5f;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 30px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            background: #0f1729;
            padding: 12px;
            text-align: left;
            font-weight: bold;
            color: #1e90ff;
            border-bottom: 2px solid #2a3f5f;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid #2a3f5f;
        }

        tr:hover { background: #242d4a; }

        .chart-container {
            background: #1a1f3a;
            border: 1px solid #2a3f5f;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
        }

        .chart-title {
            color: #1e90ff;
            font-weight: bold;
            margin-bottom: 15px;
        }

        .exit-breakdown {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-top: 10px;
        }

        .exit-item {
            background: #0f1729;
            padding: 10px;
            border-radius: 4px;
            text-align: center;
        }

        .exit-count {
            font-size: 20px;
            font-weight: bold;
            color: #1e90ff;
        }

        .exit-label {
            font-size: 11px;
            color: #888;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 PAPER TRADING DASHBOARD</h1>
        <div class="timestamp">Last updated: """ + datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC') + """</div>
        <div class="timestamp">Auto-refresh: 15 seconds</div>
    </div>

    <div class="metrics-grid">
        <div class="metric-card">
            <div class="metric-label">Closed Trades</div>
            <div class="metric-value">""" + str(metrics['closed_today']) + """</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Profit Factor</div>
            <div class="metric-value """ + ('positive' if metrics['pf'] >= 1.0 else 'negative') + """\">""" + f"{metrics['pf']:.2f}x" + """</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Net PnL (USD)</div>
            <div class="metric-value """ + ('positive' if metrics['net_pnl'] >= 0 else 'negative') + """\">""" + f"${metrics['net_pnl']:.8f}" + """</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Learning Health</div>
            <div class="metric-value """ + ('positive' if metrics['health'] > 0.05 else 'neutral') + """\">""" + f"{metrics['health']:.4f}" + """</div>
        </div>
    </div>

    <div class="chart-container">
        <div class="chart-title">Exit Distribution</div>
        <div class="exit-breakdown">
            <div class="exit-item">
                <div class="exit-count">""" + str(metrics['exits']['tp']) + """</div>
                <div class="exit-label">TP EXITS</div>
            </div>
            <div class="exit-item">
                <div class="exit-count">""" + str(metrics['exits']['sl']) + """</div>
                <div class="exit-label">SL EXITS</div>
            </div>
            <div class="exit-item">
                <div class="exit-count">""" + str(metrics['exits']['scratch']) + """</div>
                <div class="exit-label">SCRATCH</div>
            </div>
            <div class="exit-item">
                <div class="exit-count">""" + str(metrics['exits']['stagnation']) + """</div>
                <div class="exit-label">STAGNATION</div>
            </div>
        </div>
    </div>

    <div class="symbol-table">
        <div class="chart-title" style="padding: 20px 20px 0 20px;">Top Symbols by Trade Count</div>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Entry Count</th>
                </tr>
            </thead>
            <tbody>
    """

    for symbol, data in by_symbol.items():
        html_template += f"""
                <tr>
                    <td><strong>{symbol}</strong></td>
                    <td>{data['entries']}</td>
                </tr>
        """

    html_template += """
            </tbody>
        </table>
    </div>

    <footer style="text-align: center; margin-top: 40px; color: #666; font-size: 12px;">
        <p>CryptoMaster Paper Trading Dashboard v4 | Live Metrics from systemd Logs</p>
    </footer>

    <script>
    // V10.25: Load live metrics from API and update HTML
    function updateMetrics() {
        fetch('/api/dashboard/metrics')
            .then(r => r.json())
            .then(data => {
                // Update metric cards
                const closedEl = document.querySelectorAll('.metric-value')[0];
                if (closedEl) closedEl.textContent = data.closed_trades || 0;

                const openEl = document.querySelectorAll('.metric-value')[1];
                if (openEl) openEl.textContent = data.open_positions || 0;

                const pfEl = document.querySelectorAll('.metric-value')[2];
                if (pfEl) pfEl.textContent = ((data.profit_factor || 0).toFixed(2)) + 'x';

                const pnlEl = document.querySelectorAll('.metric-value')[3];
                if (pnlEl) pnlEl.textContent = '$' + (data.net_pnl || 0).toFixed(8);
            })
            .catch(e => console.log('API loading...'));
    }

    // Update on load and every 15 seconds
    updateMetrics();
    setInterval(updateMetrics, 15000);
    </script>
</body>
</html>"""

    return html_template

if __name__ == '__main__':
    print("[DASHBOARD] Starting HTTP server on port 8080...")
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)
