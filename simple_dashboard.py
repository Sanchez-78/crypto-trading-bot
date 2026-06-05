#!/usr/bin/env python3
"""
CryptoMaster Paper Trading Dashboard HTTP Server (Full Featured)
Parses journalctl logs to extract metrics and show live trading dashboard
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
        pass

    def generate_dashboard(self):
        logs = get_logs(since_minutes=120)
        metrics = extract_metrics(logs)
        by_symbol = count_by_symbol(logs)
        closed_trades = extract_closed_trades(logs)
        open_positions = extract_open_positions(logs)

        # Build symbol rows
        symbol_rows = ''
        for symbol in sorted(by_symbol.keys())[:12]:
            data = by_symbol[symbol]
            symbol_rows += f"""
                <tr>
                    <td><strong>{symbol}</strong></td>
                    <td>{data.get('entries', 0)}</td>
                    <td>{data.get('closed', 0)}</td>
                    <td>${data.get('pnl', 0):.8f}</td>
                </tr>
        """

        # Build recent closed trades rows
        trade_rows = ''
        for i, trade in enumerate(closed_trades[-20:]):  # Last 20
            pnl_class = 'positive' if trade['pnl'] >= 0 else 'negative'
            trade_rows += f"""
                <tr>
                    <td>{trade['symbol']}</td>
                    <td class="{pnl_class}">${trade['pnl']:.8f}</td>
                    <td>{trade['reason']}</td>
                    <td>{int(trade.get('hold_s', 0))}</td>
                </tr>
        """

        # Build open positions rows
        pos_rows = ''
        for pos in open_positions[:15]:  # First 15
            pos_rows += f"""
                <tr>
                    <td><strong>{pos['symbol']}</strong></td>
                    <td>${pos.get('entry', 0):.8f}</td>
                    <td>${pos.get('tp', 0):.8f}</td>
                    <td>${pos.get('sl', 0):.8f}</td>
                    <td>{int(pos.get('age_s', 0))}s</td>
                </tr>
        """

        # Exit distribution bars
        exit_total = (metrics['exits']['tp'] + metrics['exits']['sl'] +
                     metrics['exits']['scratch'] + metrics['exits']['stagnation'])

        if exit_total > 0:
            tp_pct = int((metrics['exits']['tp'] / exit_total) * 100)
            sl_pct = int((metrics['exits']['sl'] / exit_total) * 100)
            scratch_pct = int((metrics['exits']['scratch'] / exit_total) * 100)
            stag_pct = int((metrics['exits']['stagnation'] / exit_total) * 100)
        else:
            tp_pct = sl_pct = scratch_pct = stag_pct = 0

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
        }}
        .container {{ max-width: 1400px; margin: 0 auto; }}

        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #1e90ff;
        }}
        .header h1 {{ color: #1e90ff; font-size: 32px; margin-bottom: 8px; }}
        .header .info {{ color: #888; font-size: 12px; }}

        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}

        .metric-card {{
            background: linear-gradient(135deg, #1a1f3a 0%, #242d4a 100%);
            border: 1px solid #2a3f5f;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }}

        .metric-label {{
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 8px;
        }}

        .metric-value {{
            font-size: 28px;
            font-weight: 700;
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
            box-shadow: 0 4px 6px rgba(0,0,0,0.2);
        }}

        .section-title {{
            color: #1e90ff;
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #2a3f5f;
        }}

        .exit-distribution {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-bottom: 20px;
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

        .exit-bar {{
            display: flex;
            height: 30px;
            border-radius: 4px;
            overflow: hidden;
            background: #0f1729;
            margin-top: 10px;
        }}

        .bar-segment {{
            display: flex;
            align-items: center;
            justify-content: center;
            color: #fff;
            font-weight: bold;
            font-size: 11px;
        }}

        .bar-tp {{ background: #00aa00; }}
        .bar-sl {{ background: #ff6666; }}
        .bar-scratch {{ background: #ffaa00; }}
        .bar-stag {{ background: #aa00ff; }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
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
            font-size: 13px;
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

        .grid-2 {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(600px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}

        .pnl-chart {{
            background: #0f1729;
            padding: 10px;
            border-radius: 4px;
            display: flex;
            align-items: flex-end;
            gap: 2px;
            height: 200px;
            overflow-x: auto;
        }}

        .pnl-bar {{
            flex: 1;
            min-width: 20px;
            border-radius: 2px 2px 0 0;
            position: relative;
        }}

        .pnl-bar.win {{ background: #00aa00; }}
        .pnl-bar.loss {{ background: #ff6666; }}

        @media (max-width: 768px) {{
            .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
            .exit-distribution {{ grid-template-columns: repeat(2, 1fr); }}
            .grid-2 {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 CryptoMaster Paper Trading</h1>
            <div class="info">
                Updated: <strong>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</strong> |
                Auto-refresh: 15s |
                Logs: Last 120 min
            </div>
        </div>

        <!-- Core Metrics -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Closed Trades</div>
                <div class="metric-value info">{metrics['closed_today']}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Open Positions</div>
                <div class="metric-value info">{len(open_positions)}</div>
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
                <div class="metric-label">Total Entries</div>
                <div class="metric-value info">{sum(d.get('entries', 0) for d in by_symbol.values())}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Learning Health</div>
                <div class="metric-value {'positive' if metrics['health'] > 0.05 else 'neutral'}">{metrics['health']:.4f}</div>
            </div>
        </div>

        <!-- Exit Distribution -->
        <div class="section">
            <div class="section-title">Exit Distribution ({exit_total} total)</div>
            <div class="exit-distribution">
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

            <!-- Stacked bar chart -->
            <div style="margin-top: 15px;">
                <div style="font-size: 11px; color: #888; margin-bottom: 5px;">Distribution</div>
                <div class="exit-bar">
                    {f'<div class="bar-segment bar-tp" style="width: {tp_pct}%">{tp_pct}%</div>' if tp_pct > 5 else ''}
                    {f'<div class="bar-segment bar-sl" style="width: {sl_pct}%">{sl_pct}%</div>' if sl_pct > 5 else ''}
                    {f'<div class="bar-segment bar-scratch" style="width: {scratch_pct}%">{scratch_pct}%</div>' if scratch_pct > 5 else ''}
                    {f'<div class="bar-segment bar-stag" style="width: {stag_pct}%">{stag_pct}%</div>' if stag_pct > 5 else ''}
                </div>
            </div>
        </div>

        <div class="grid-2">
            <!-- Symbol Activity -->
            <div class="section">
                <div class="section-title">Trading Symbols</div>
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Entries</th>
                            <th>Closed</th>
                            <th>PnL</th>
                        </tr>
                    </thead>
                    <tbody>
                        {symbol_rows if symbol_rows else '<tr><td colspan="4" style="text-align: center; color: #666;">No trades yet</td></tr>'}
                    </tbody>
                </table>
            </div>

            <!-- Open Positions -->
            <div class="section">
                <div class="section-title">Open Positions ({len(open_positions)} active)</div>
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Entry</th>
                            <th>TP</th>
                            <th>SL</th>
                            <th>Age</th>
                        </tr>
                    </thead>
                    <tbody>
                        {pos_rows if pos_rows else '<tr><td colspan="5" style="text-align: center; color: #666;">No open positions</td></tr>'}
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Recent Closed Trades -->
        <div class="section">
            <div class="section-title">Recent Closed Trades (Last 20)</div>
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>PnL (USD)</th>
                        <th>Exit Reason</th>
                        <th>Hold Time</th>
                    </tr>
                </thead>
                <tbody>
                    {trade_rows if trade_rows else '<tr><td colspan="4" style="text-align: center; color: #666;">No closed trades yet</td></tr>'}
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>CryptoMaster Paper Trading Dashboard | Live from journalctl logs | No external dependencies</p>
            <p>Refresh every 15 seconds • Last 120 minutes of data</p>
        </div>
    </div>
</body>
</html>"""
        return html

def get_logs(since_minutes=120):
    """Fetch recent logs from journalctl"""
    try:
        cmd = f"journalctl -u cryptomaster.service --since '{since_minutes} minutes ago' --no-pager 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        return result.stdout
    except Exception:
        return ""

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
        # Parse V10.13g EXIT breakdown
        if '[V10.13g EXIT]' in line:
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

    # Count closed trades from [PAPER_EXIT] logs
    closed_count = logs.count('[PAPER_EXIT]')
    metrics['closed_today'] = closed_count

    return metrics

def extract_closed_trades(logs):
    """Extract closed trade details"""
    trades = []
    for line in logs.split('\n'):
        if '[PAPER_EXIT]' in line:
            trade = {}
            m = re.search(r'symbol=(\w+)', line)
            if m: trade['symbol'] = m.group(1)

            m = re.search(r'net_pnl_pct=([\d.\-]+)', line)
            if m:
                pnl_pct = float(m.group(1))
                # Estimate PnL in USD assuming ~0.001 BTC per trade (~$30-60)
                trade['pnl'] = pnl_pct / 100.0

            m = re.search(r'reason=(\w+)', line)
            if m: trade['reason'] = m.group(1)

            m = re.search(r'hold_s=(\d+)', line)
            if m: trade['hold_s'] = int(m.group(1))

            if trade:
                trades.append(trade)

    return trades

def extract_open_positions(logs):
    """Extract open position details"""
    positions = {}
    current_time = time.time()

    for line in logs.split('\n'):
        if '[EXEC]' in line and 'entry=' in line:
            # Extract symbol
            m = re.search(r'symbol=(\w+)', line)
            if not m: continue
            symbol = m.group(1)

            # Extract entry price
            m = re.search(r'entry=([\d.]+)', line)
            entry = float(m.group(1)) if m else 0

            # Extract TP and SL
            m = re.search(r'TP[=]([\d.]+)', line)
            tp = float(m.group(1)) if m else 0

            m = re.search(r'SL[=]([\d.]+)', line)
            sl = float(m.group(1)) if m else 0

            # Store position (keep last entry for each symbol)
            positions[symbol] = {
                'symbol': symbol,
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'age_s': 0
            }

    return list(positions.values())

def count_by_symbol(logs):
    """Count trades by symbol"""
    by_symbol = defaultdict(lambda: {'entries': 0, 'closed': 0, 'pnl': 0.0})

    for line in logs.split('\n'):
        if '[EXEC]' in line:
            m = re.search(r'symbol[=](\w+)', line)
            if m:
                sym = m.group(1)
                by_symbol[sym]['entries'] += 1

        if '[PAPER_EXIT]' in line:
            m = re.search(r'symbol=(\w+)', line)
            if m:
                sym = m.group(1)
                by_symbol[sym]['closed'] += 1

    return dict(by_symbol)

def run_server():
    """Run HTTP server on port 8080"""
    server = HTTPServer(('0.0.0.0', 8080), DashboardHandler)
    print(f"[DASHBOARD] HTTP Server started on http://0.0.0.0:8080")
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
