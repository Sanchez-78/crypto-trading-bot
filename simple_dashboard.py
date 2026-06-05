#!/usr/bin/env python3
"""
CryptoMaster Paper Trading Dashboard HTTP Server (V10.15k with Local Learning Storage)
Reads live metrics from local SQLite database instead of parsing logs
"""

import subprocess
import re
import json
import sqlite3
from datetime import datetime
from collections import defaultdict
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import time
import os

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # API endpoints
        if self.path == '/api/dashboard/metrics':
            self.handle_api_metrics()
        elif self.path == '/api/dashboard/readiness':
            self.handle_api_readiness()
        elif self.path.startswith('/api/dashboard/readiness/'):
            symbol = self.path.split('/')[-1].upper()
            self.handle_api_symbol_readiness(symbol)
        elif self.path == '/api/dashboard/exits':
            self.handle_api_exits()
        elif self.path == '/api/dashboard/trades':
            self.handle_api_trades()
        elif self.path.startswith('/api/dashboard/trades/'):
            symbol = self.path.split('/')[-1].upper()
            self.handle_api_symbol_trades(symbol)
        # HTML dashboard
        elif self.path == '/' or self.path == '/index.html':
            html = self.generate_dashboard()
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def send_json(self, data, status=200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def handle_api_metrics(self):
        """GET /api/dashboard/metrics - All aggregated metrics"""
        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if not os.path.exists(db_path):
                return self.send_json({'error': 'No trades recorded yet'}, 404)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get success metrics
            cursor.execute('''
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN pnl_pct > 0.001 THEN 1 ELSE 0 END) as wins,
                       SUM(CASE WHEN pnl_pct < -0.001 THEN 1 ELSE 0 END) as losses,
                       AVG(pnl_pct) as expectancy,
                       SUM(pnl_usd) as net_pnl
                FROM trades
            ''')
            metrics_row = cursor.fetchone()
            total = metrics_row['total']
            wins = metrics_row['wins'] or 0
            losses = metrics_row['losses'] or 0
            net_pnl = metrics_row['net_pnl'] or 0.0
            expectancy = metrics_row['expectancy'] or 0.0

            profit_factor = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)
            win_rate_pct = (wins / total * 100) if total > 0 else 0.0

            # Get exit distribution
            cursor.execute('''
                SELECT exit_reason, COUNT(*) as cnt FROM trades GROUP BY exit_reason
            ''')
            exits = {'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0}
            for row in cursor.fetchall():
                reason = (row['exit_reason'] or 'unknown').lower()
                if reason == 'tp':
                    exits['tp'] = row['cnt']
                elif reason == 'sl':
                    exits['sl'] = row['cnt']
                elif 'scratch' in reason:
                    exits['scratch'] = row['cnt']
                elif 'stag' in reason:
                    exits['stagnation'] = row['cnt']
                elif 'timeout' in reason:
                    exits['timeout'] = row['cnt']

            # Get readiness by symbol
            cursor.execute('''
                SELECT symbol, readiness_status, readiness_pct, closed_trades,
                       win_rate, profit_factor, expectancy
                FROM readiness_status
                ORDER BY readiness_pct DESC
            ''')
            readiness_by_symbol = []
            for row in cursor.fetchall():
                readiness_by_symbol.append({
                    'symbol': row['symbol'],
                    'closed_trades': row['closed_trades'],
                    'win_rate': round(row['win_rate'], 4),
                    'profit_factor': round(row['profit_factor'], 2),
                    'expectancy': round(row['expectancy'], 6),
                    'min_trades_ok': row['closed_trades'] >= 50,
                    'wr_ok': row['win_rate'] >= 0.65,
                    'pf_ok': row['profit_factor'] >= 1.05,
                    'exp_ok': row['expectancy'] > 0,
                    'readiness_status': row['readiness_status'],
                    'readiness_pct': round(row['readiness_pct'], 1),
                    'last_update': int(time.time())
                })

            conn.close()

            response = {
                'win_rate_pct': round(win_rate_pct, 1),
                'profit_factor': round(profit_factor, 2),
                'net_pnl': round(net_pnl, 8),
                'closed_trades': total,
                'exit_distribution': exits,
                'readiness_by_symbol': readiness_by_symbol,
                'timestamp': int(time.time()),
                'last_update': datetime.utcnow().isoformat()
            }
            self.send_json(response)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_api_readiness(self):
        """GET /api/dashboard/readiness - Readiness for all symbols"""
        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if not os.path.exists(db_path):
                return self.send_json([], 200)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT symbol, readiness_status, readiness_pct, closed_trades,
                       win_rate, profit_factor, expectancy
                FROM readiness_status
                ORDER BY readiness_pct DESC
            ''')

            readiness_list = []
            for row in cursor.fetchall():
                readiness_list.append({
                    'symbol': row['symbol'],
                    'closed_trades': row['closed_trades'],
                    'win_rate': round(row['win_rate'], 4),
                    'profit_factor': round(row['profit_factor'], 2),
                    'expectancy': round(row['expectancy'], 6),
                    'min_trades_ok': row['closed_trades'] >= 50,
                    'wr_ok': row['win_rate'] >= 0.65,
                    'pf_ok': row['profit_factor'] >= 1.05,
                    'exp_ok': row['expectancy'] > 0,
                    'readiness_status': row['readiness_status'],
                    'readiness_pct': round(row['readiness_pct'], 1),
                    'last_update': int(time.time())
                })

            conn.close()
            self.send_json(readiness_list)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_api_symbol_readiness(self, symbol):
        """GET /api/dashboard/readiness/<symbol> - Readiness for specific symbol"""
        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if not os.path.exists(db_path):
                return self.send_json({'error': f'Symbol {symbol} not found'}, 404)

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT symbol, readiness_status, readiness_pct, closed_trades,
                       win_rate, profit_factor, expectancy
                FROM readiness_status
                WHERE symbol = ?
            ''', (symbol,))

            row = cursor.fetchone()
            conn.close()

            if not row:
                return self.send_json({'error': f'Symbol {symbol} not found'}, 404)

            response = {
                'symbol': row['symbol'],
                'closed_trades': row['closed_trades'],
                'win_rate': round(row['win_rate'], 4),
                'profit_factor': round(row['profit_factor'], 2),
                'expectancy': round(row['expectancy'], 6),
                'min_trades_ok': row['closed_trades'] >= 50,
                'wr_ok': row['win_rate'] >= 0.65,
                'pf_ok': row['profit_factor'] >= 1.05,
                'exp_ok': row['expectancy'] > 0,
                'readiness_status': row['readiness_status'],
                'readiness_pct': round(row['readiness_pct'], 1),
                'last_update': int(time.time())
            }
            self.send_json(response)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_api_exits(self):
        """GET /api/dashboard/exits - Exit type distribution"""
        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if not os.path.exists(db_path):
                return self.send_json({'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0, 'total': 0})

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT exit_reason, COUNT(*) as cnt FROM trades GROUP BY exit_reason
            ''')

            exits = {'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0, 'total': 0}
            for row in cursor.fetchall():
                reason = (row['exit_reason'] or 'unknown').lower()
                if reason == 'tp':
                    exits['tp'] = row['cnt']
                elif reason == 'sl':
                    exits['sl'] = row['cnt']
                elif 'scratch' in reason:
                    exits['scratch'] = row['cnt']
                elif 'stag' in reason:
                    exits['stagnation'] = row['cnt']
                elif 'timeout' in reason:
                    exits['timeout'] = row['cnt']
                exits['total'] += row['cnt']

            conn.close()
            self.send_json(exits)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_api_trades(self):
        """GET /api/dashboard/trades - All closed trades with full details"""
        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if not os.path.exists(db_path):
                return self.send_json([])

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Get last 100 trades
            cursor.execute('''
                SELECT trade_id, symbol, side, entry_price, exit_price, entry_ts, exit_ts,
                       pnl_pct, pnl_usd, mfe_pct, mae_pct, exit_reason, regime, size_usd,
                       cost_edge_ok, learning_source
                FROM trades
                ORDER BY exit_ts DESC
                LIMIT 100
            ''')

            trades = []
            for row in cursor.fetchall():
                hold_s = (row['exit_ts'] or 0) - (row['entry_ts'] or 0)
                trades.append({
                    'trade_id': row['trade_id'],
                    'symbol': row['symbol'],
                    'side': row['side'],
                    'entry_price': round(row['entry_price'], 8) if row['entry_price'] else 0,
                    'exit_price': round(row['exit_price'], 8) if row['exit_price'] else 0,
                    'entry_ts': row['entry_ts'],
                    'exit_ts': row['exit_ts'],
                    'hold_s': hold_s,
                    'pnl_pct': round(row['pnl_pct'], 6) if row['pnl_pct'] else 0,
                    'pnl_usd': round(row['pnl_usd'], 8) if row['pnl_usd'] else 0,
                    'mfe_pct': round(row['mfe_pct'], 6) if row['mfe_pct'] else 0,
                    'mae_pct': round(row['mae_pct'], 6) if row['mae_pct'] else 0,
                    'exit_reason': row['exit_reason'],
                    'regime': row['regime'],
                    'size_usd': round(row['size_usd'], 8) if row['size_usd'] else 0,
                    'cost_edge_ok': bool(row['cost_edge_ok']),
                    'learning_source': row['learning_source'],
                })

            conn.close()
            self.send_json(trades)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def handle_api_symbol_trades(self, symbol):
        """GET /api/dashboard/trades/<symbol> - Trades for specific symbol"""
        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if not os.path.exists(db_path):
                return self.send_json([])

            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute('''
                SELECT trade_id, symbol, side, entry_price, exit_price, entry_ts, exit_ts,
                       pnl_pct, pnl_usd, mfe_pct, mae_pct, exit_reason, regime, size_usd,
                       cost_edge_ok, learning_source
                FROM trades
                WHERE symbol = ?
                ORDER BY exit_ts DESC
                LIMIT 50
            ''', (symbol,))

            trades = []
            for row in cursor.fetchall():
                hold_s = (row['exit_ts'] or 0) - (row['entry_ts'] or 0)
                trades.append({
                    'trade_id': row['trade_id'],
                    'symbol': row['symbol'],
                    'side': row['side'],
                    'entry_price': round(row['entry_price'], 8) if row['entry_price'] else 0,
                    'exit_price': round(row['exit_price'], 8) if row['exit_price'] else 0,
                    'entry_ts': row['entry_ts'],
                    'exit_ts': row['exit_ts'],
                    'hold_s': hold_s,
                    'pnl_pct': round(row['pnl_pct'], 6) if row['pnl_pct'] else 0,
                    'pnl_usd': round(row['pnl_usd'], 8) if row['pnl_usd'] else 0,
                    'mfe_pct': round(row['mfe_pct'], 6) if row['mfe_pct'] else 0,
                    'mae_pct': round(row['mae_pct'], 6) if row['mae_pct'] else 0,
                    'exit_reason': row['exit_reason'],
                    'regime': row['regime'],
                    'size_usd': round(row['size_usd'], 8) if row['size_usd'] else 0,
                    'cost_edge_ok': bool(row['cost_edge_ok']),
                    'learning_source': row['learning_source'],
                })

            conn.close()
            self.send_json(trades)
        except Exception as e:
            self.send_json({'error': str(e)}, 500)

    def log_message(self, format, *args):
        pass

    def generate_dashboard(self):
        # Load all data from database (not logs)
        metrics = get_metrics_from_database()
        readiness = get_readiness_status()
        success_rate = get_success_rate()
        trade_details = get_trade_details()
        pnl_trend = get_pnl_trend()

        # Extract symbol data from trade_details instead of logs
        by_symbol = {}
        total_entries = 0
        for trade in trade_details:
            sym = trade['symbol']
            if sym not in by_symbol:
                by_symbol[sym] = {'entries': 0, 'closed': 0, 'pnl': 0.0}
            by_symbol[sym]['entries'] += 1
            by_symbol[sym]['closed'] += 1
            total_entries += 1
            # Parse PnL from string (e.g., "$-0.00005000")
            pnl_str = trade['pnl_usd'].replace('$', '')
            try:
                by_symbol[sym]['pnl'] += float(pnl_str)
            except:
                pass

        closed_trades = trade_details[:20]  # Use trade_details for recent trades
        open_positions = []  # Empty for now since we have no open position data

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
            # Parse PnL from string (e.g., "$-0.00005000")
            pnl_str = trade['pnl_usd'].replace('$', '')
            try:
                pnl_value = float(pnl_str)
            except:
                pnl_value = 0.0
            pnl_class = 'positive' if pnl_value >= 0 else 'negative'
            trade_rows += f"""
                <tr>
                    <td>{trade['symbol']}</td>
                    <td class="{pnl_class}">{trade['pnl_usd']}</td>
                    <td>{trade['exit_reason']}</td>
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
                     metrics['exits']['scratch'] + metrics['exits']['stagnation'] +
                     metrics['exits']['timeout'])

        if exit_total > 0:
            tp_pct = int((metrics['exits']['tp'] / exit_total) * 100)
            sl_pct = int((metrics['exits']['sl'] / exit_total) * 100)
            scratch_pct = int((metrics['exits']['scratch'] / exit_total) * 100)
            stag_pct = int((metrics['exits']['stagnation'] / exit_total) * 100)
            timeout_pct = int((metrics['exits']['timeout'] / exit_total) * 100)
        else:
            tp_pct = sl_pct = scratch_pct = stag_pct = timeout_pct = 0

        # Build trade details rows
        trade_details_rows = ''
        for trade in trade_details[:50]:  # Last 50
            trade_details_rows += f"""
                <tr>
                    <td style="font-family: monospace; font-size: 11px;">{trade['trade_id']}</td>
                    <td><strong>{trade['symbol']}</strong></td>
                    <td style="color: {'#10b981' if trade['side'] == 'BUY' else '#ef4444'}">{trade['side']}</td>
                    <td style="font-family: monospace; font-size: 11px;">{trade['entry_price']}</td>
                    <td style="font-family: monospace; font-size: 11px;">{trade['exit_price']}</td>
                    <td style="font-size: 11px;">{trade['entry_time']}</td>
                    <td style="font-size: 11px;">{trade['exit_time']}</td>
                    <td>{trade['hold_s']}</td>
                    <td style="font-family: monospace;">{trade['pnl_pct']}</td>
                    <td style="font-family: monospace; color: {'#10b981' if trade['pnl_color'] == 'positive' else '#ef4444' if trade['pnl_color'] == 'negative' else '#fbbf24'}; font-weight: bold;">{trade['pnl_usd']}</td>
                    <td style="font-size: 11px;">{trade['mfe_mae']}</td>
                    <td><span style="background: {'#10b98133' if 'TP' in trade['exit_reason'] else '#ef444433' if 'SL' in trade['exit_reason'] else '#fbbf2433'}; padding: 2px 6px; border-radius: 3px;">{trade['exit_reason']}</span></td>
                    <td style="font-size: 11px;">{trade['regime']}</td>
                </tr>
        """

        # Build readiness section
        ready_real_html = ''
        for sym in readiness['READY_REAL'][:5]:
            ready_real_html += f"""
                <div style="display: inline-block; background: #1a5f1a; padding: 10px 15px; margin: 5px; border-radius: 4px; font-size: 11px;">
                    <strong>{sym['symbol']}</strong><br/>
                    {sym['pct']:.0f}% Ready | WR {sym['wr']:.0f}% | PF {sym['pf']:.2f}x
                </div>
            """

        ready_paper_html = ''
        for sym in readiness['READY_PAPER'][:5]:
            ready_paper_html += f"""
                <div style="display: inline-block; background: #334d00; padding: 10px 15px; margin: 5px; border-radius: 4px; font-size: 11px;">
                    <strong>{sym['symbol']}</strong><br/>
                    {sym['pct']:.0f}% Ready | WR {sym['wr']:.0f}% | PF {sym['pf']:.2f}x
                </div>
            """

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
        .bar-timeout {{ background: #666666; }}

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
        .chart-container {{
            background: #0f1729;
            padding: 15px;
            border-radius: 8px;
            margin-top: 15px;
            position: relative;
            height: 250px;
        }}

        .chart-title {{
            color: #1e90ff;
            font-size: 12px;
            font-weight: bold;
            margin-bottom: 10px;
        }}

        canvas {{
            max-height: 200px;
        }}

        .exit-chart {{
            display: flex;
            justify-content: space-around;
            align-items: flex-end;
            height: 150px;
            margin-top: 10px;
            gap: 5px;
        }}

        .chart-bar {{
            flex: 1;
            background: linear-gradient(to top, #3b82f6, #1e40af);
            border-radius: 3px 3px 0 0;
            position: relative;
            display: flex;
            flex-direction: column;
            justify-content: flex-end;
            align-items: center;
        }}

        .chart-bar.tp {{ background: linear-gradient(to top, #10b981, #047857); }}
        .chart-bar.sl {{ background: linear-gradient(to top, #ef4444, #dc2626); }}
        .chart-bar.scratch {{ background: linear-gradient(to top, #fbbf24, #f59e0b); }}
        .chart-bar.stag {{ background: linear-gradient(to top, #8b5cf6, #7c3aed); }}
        .chart-bar.timeout {{ background: linear-gradient(to top, #6b7280, #4b5563); }}

        .chart-bar-label {{
            color: #fff;
            font-size: 10px;
            font-weight: bold;
            margin-bottom: 3px;
        }}

        .chart-bar-count {{
            color: #fff;
            font-size: 12px;
            font-weight: bold;
            padding: 2px 4px;
        }}
    </style>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
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
            <div class="section-title">📊 Exit Distribution ({exit_total} total)</div>
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
                <div class="exit-item">
                    <div class="exit-count">{metrics['exits']['timeout']}</div>
                    <div class="exit-label">Timeout</div>
                </div>
            </div>

            <!-- Bar chart visualization -->
            <div class="chart-container">
                <div class="chart-title">Exit Type Distribution</div>
                <div class="exit-chart">
                    {f'<div class="chart-bar tp" style="height: {(metrics["exits"]["tp"] / max(max(metrics["exits"].values()), 1)) * 100}%;"><div class="chart-bar-count">{metrics["exits"]["tp"]}</div><div class="chart-bar-label">TP</div></div>' if metrics['exits']['tp'] > 0 else ''}
                    {f'<div class="chart-bar sl" style="height: {(metrics["exits"]["sl"] / max(max(metrics["exits"].values()), 1)) * 100}%;"><div class="chart-bar-count">{metrics["exits"]["sl"]}</div><div class="chart-bar-label">SL</div></div>' if metrics['exits']['sl'] > 0 else ''}
                    {f'<div class="chart-bar scratch" style="height: {(metrics["exits"]["scratch"] / max(max(metrics["exits"].values()), 1)) * 100}%;"><div class="chart-bar-count">{metrics["exits"]["scratch"]}</div><div class="chart-bar-label">SCR</div></div>' if metrics['exits']['scratch'] > 0 else ''}
                    {f'<div class="chart-bar stag" style="height: {(metrics["exits"]["stagnation"] / max(max(metrics["exits"].values()), 1)) * 100}%;"><div class="chart-bar-count">{metrics["exits"]["stagnation"]}</div><div class="chart-bar-label">STAG</div></div>' if metrics['exits']['stagnation'] > 0 else ''}
                    {f'<div class="chart-bar timeout" style="height: {(metrics["exits"]["timeout"] / max(max(metrics["exits"].values()), 1)) * 100}%;"><div class="chart-bar-count">{metrics["exits"]["timeout"]}</div><div class="chart-bar-label">TIMEOUT</div></div>' if metrics['exits']['timeout'] > 0 else ''}
                </div>
            </div>

            <!-- Stacked bar chart -->
            <div style="margin-top: 15px;">
                <div style="font-size: 11px; color: #888; margin-bottom: 5px;">Procenta</div>
                <div class="exit-bar">
                    {f'<div class="bar-segment bar-tp" style="width: {tp_pct}%">{tp_pct}%</div>' if tp_pct > 5 else ''}
                    {f'<div class="bar-segment bar-sl" style="width: {sl_pct}%">{sl_pct}%</div>' if sl_pct > 5 else ''}
                    {f'<div class="bar-segment bar-scratch" style="width: {scratch_pct}%">{scratch_pct}%</div>' if scratch_pct > 5 else ''}
                    {f'<div class="bar-segment bar-stag" style="width: {stag_pct}%">{stag_pct}%</div>' if stag_pct > 5 else ''}
                    {f'<div class="bar-segment bar-timeout" style="width: {timeout_pct}%">{timeout_pct}%</div>' if timeout_pct > 5 else ''}
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
            <div class="section-title">📊 Success Rate & Readiness</div>
            <div style="background: #1a1f3a; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;">
                    <div style="text-align: center;">
                        <div style="font-size: 36px; font-weight: bold; color: #00ff00;">{success_rate:.1f}%</div>
                        <div style="color: #888; font-size: 12px;">WIN RATE (Success %)</div>
                    </div>
                    <div style="text-align: center;">
                        <div style="font-size: 36px; font-weight: bold; color: #ffaa00;">{metrics['pf']:.2f}x</div>
                        <div style="color: #888; font-size: 12px;">PROFIT FACTOR</div>
                    </div>
                </div>

                <div style="margin-top: 20px;">
                    <div style="color: #1e90ff; font-weight: bold; margin-bottom: 10px;">🚀 READY FOR REAL TRADING (4/4 criteria):</div>
                    <div style="margin-bottom: 10px;">
                        {ready_real_html if ready_real_html else '<span style="color: #666;">No symbols ready yet. Need: 50+ trades, WR≥65%, PF≥1.05x, Expectancy>0</span>'}
                    </div>
                </div>

                <div style="margin-top: 20px;">
                    <div style="color: #90ee90; font-weight: bold; margin-bottom: 10px;">📈 READY FOR PAPER (3/4 criteria):</div>
                    <div style="margin-bottom: 10px;">
                        {ready_paper_html if ready_paper_html else '<span style="color: #666;">No symbols ready yet.</span>'}
                    </div>
                </div>

                <div style="margin-top: 15px; font-size: 11px; color: #666; border-top: 1px solid #333; padding-top: 10px;">
                    <strong>Readiness Criteria:</strong><br/>
                    • MIN TRADES: 50+ closed trades<br/>
                    • WIN RATE: ≥65% success<br/>
                    • PROFIT FACTOR: ≥1.05x (break-even is 1.0x)<br/>
                    • EXPECTANCY: Positive (avg PnL per trade > 0)
                </div>
            </div>
        </div>

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

        <!-- PnL Trend Chart -->
        <div class="section">
            <div class="section-title">📈 PnL Trend (Last 30 Trades)</div>
            <canvas id="pnlChart" width="400" height="200"></canvas>
        </div>

        <!-- Trade Details Section -->
        <div class="section">
            <div class="section-title">📋 Všechny Uzavřené Obchody</div>
            <table>
                <thead>
                    <tr>
                        <th>Trade ID</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>Entry Time</th>
                        <th>Exit Time</th>
                        <th>Hold (s)</th>
                        <th>PnL %</th>
                        <th>PnL USD</th>
                        <th>MFE/MAE</th>
                        <th>Exit Reason</th>
                        <th>Regime</th>
                    </tr>
                </thead>
                <tbody>
                    {trade_details_rows if trade_details_rows else '<tr><td colspan="13" style="text-align: center; color: #666;">Žádné obchody k zobrazení</td></tr>'}
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>CryptoMaster Paper Trading Dashboard | Live from local learning storage | Auto-refresh 15s</p>
            <p>Exit Distribution • Trade Details • Per-Symbol Metrics</p>
        </div>
    </div>

    <script>
        // PnL Trend Chart
        const ctx = document.getElementById('pnlChart');
        if (ctx) {{
            const pnlData = {json.dumps(pnl_trend)};
            const maxValue = Math.max(...pnlData.cumulative.map(v => Math.abs(v))) || 0.0001;

            new Chart(ctx, {{
                type: 'line',
                data: {{
                    labels: pnlData.labels,
                    datasets: [
                        {{
                            label: 'Cumulative PnL (USD)',
                            data: pnlData.cumulative,
                            borderColor: '#1e90ff',
                            backgroundColor: 'rgba(30, 144, 255, 0.1)',
                            tension: 0.1,
                            fill: true,
                            yAxisID: 'y',
                        }},
                        {{
                            label: 'Per-Trade PnL (USD)',
                            data: pnlData.pnl,
                            borderColor: '#10b981',
                            backgroundColor: pnlData.pnl.map(v => v > 0 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'),
                            type: 'bar',
                            yAxisID: 'y1',
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    interaction: {{ mode: 'index', intersect: false }},
                    plugins: {{
                        legend: {{
                            display: true,
                            labels: {{ color: '#999' }}
                        }},
                        tooltip: {{
                            backgroundColor: '#0f1729',
                            titleColor: '#fff',
                            bodyColor: '#ddd'
                        }}
                    }},
                    scales: {{
                        y: {{
                            type: 'linear',
                            display: true,
                            position: 'left',
                            grid: {{ color: 'rgba(100,100,100,0.1)' }},
                            ticks: {{ color: '#999' }},
                            title: {{ display: true, text: 'Cumulative PnL (USD)', color: '#1e90ff' }}
                        }},
                        y1: {{
                            type: 'linear',
                            display: true,
                            position: 'right',
                            grid: {{ drawOnChartArea: false }},
                            ticks: {{ color: '#999' }},
                            title: {{ display: true, text: 'Per-Trade PnL (USD)', color: '#10b981' }}
                        }},
                        x: {{
                            grid: {{ color: 'rgba(100,100,100,0.1)' }},
                            ticks: {{ color: '#999' }}
                        }}
                    }}
                }}
            }});
        }}
    </script>
</body>
</html>"""
        return html

_logs_cache = {"data": "", "timestamp": 0}

def get_logs(since_minutes=120):
    """Fetch recent logs from journalctl (with 30s cache)"""
    global _logs_cache
    current_time = time.time()

    # Use cache if less than 30 seconds old
    if current_time - _logs_cache["timestamp"] < 30 and _logs_cache["data"]:
        return _logs_cache["data"]

    try:
        cmd = f"journalctl -u cryptomaster.service --since '{since_minutes} minutes ago' --no-pager 2>/dev/null"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        _logs_cache["data"] = result.stdout
        _logs_cache["timestamp"] = current_time
        return result.stdout
    except Exception:
        return _logs_cache.get("data", "")

def get_metrics_from_database():
    """Read metrics directly from local learning storage database"""
    db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'

    metrics = {
        'closed_today': 0,
        'pf': 0.0,
        'net_pnl': 0.0,
        'health': 0.0,
        'exits': {'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0},
        'open_positions': 0,
    }

    if not os.path.exists(db_path):
        return metrics

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get closed trades count
        cursor.execute('SELECT COUNT(*) as cnt FROM trades')
        metrics['closed_today'] = cursor.fetchone()['cnt']

        # Get exit distribution
        cursor.execute('''
            SELECT exit_reason, COUNT(*) as cnt
            FROM trades
            GROUP BY exit_reason
        ''')
        for row in cursor.fetchall():
            reason = (row['exit_reason'] or '').lower()
            if 'tp' in reason or reason == 'tp':
                metrics['exits']['tp'] += row['cnt']
            elif 'sl' in reason or reason == 'sl':
                metrics['exits']['sl'] += row['cnt']
            elif 'scratch' in reason:
                metrics['exits']['scratch'] += row['cnt']
            elif 'stag' in reason:
                metrics['exits']['stagnation'] += row['cnt']
            elif 'timeout' in reason or reason == 'timeout':
                metrics['exits']['timeout'] += row['cnt']

        # Get profit factor from trades (not learning_metrics)
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl_usd < 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl_usd) as net_pnl
            FROM trades
        ''')
        row = cursor.fetchone()
        total = row['total'] or 0
        wins = row['wins'] or 0
        losses = row['losses'] or 0
        net_pnl = row['net_pnl'] or 0.0

        # Calculate profit factor correctly
        if losses > 0:
            metrics['pf'] = wins / (losses + 0.0001)
        elif wins > 0:
            metrics['pf'] = 1.0
        else:
            metrics['pf'] = 0.0

        metrics['net_pnl'] = net_pnl

        conn.close()
    except Exception as e:
        print(f"[DASHBOARD_DB_ERROR] {e}")

    return metrics


def extract_metrics(logs):
    """Extract key metrics (DEPRECATED - use database instead)"""
    # Keep for backwards compatibility but delegate to database
    return get_metrics_from_database()

def extract_closed_trades(logs):
    """Extract closed trade details from local database"""
    db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
    trades = []

    if not os.path.exists(db_path):
        return trades

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get last 50 closed trades
        cursor.execute('''
            SELECT symbol, pnl_pct, pnl_usd, exit_reason,
                   (exit_ts - entry_ts) as hold_s
            FROM trades
            ORDER BY exit_ts DESC
            LIMIT 50
        ''')

        for row in cursor.fetchall():
            trade = {
                'symbol': row['symbol'],
                'pnl': row['pnl_usd'] or (row['pnl_pct'] / 100.0 if row['pnl_pct'] else 0),
                'reason': row['exit_reason'],
                'hold_s': row['hold_s']
            }
            trades.append(trade)

        conn.close()
    except Exception as e:
        print(f"[DASHBOARD_DB_ERROR] {e}")

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

def get_success_rate():
    """Calculate overall success rate (win rate)"""
    db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'

    if not os.path.exists(db_path):
        return 0.0

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Count wins and losses
        cursor.execute('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_pct > 0.001 THEN 1 ELSE 0 END) as wins
            FROM trades
        ''')

        row = cursor.fetchone()
        total = row[0]
        wins = row[1] or 0

        conn.close()

        if total > 0:
            return (wins / total) * 100
        else:
            return 0.0
    except Exception as e:
        print(f"[DASHBOARD_ERROR] {e}")
        return 0.0


def get_readiness_status():
    """Get readiness status for all symbols"""
    db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
    readiness = {
        'READY_REAL': [],
        'READY_PAPER': [],
        'LEARNING': [],
        'INSUFFICIENT': []
    }

    if not os.path.exists(db_path):
        return readiness

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get readiness status for all symbols
        cursor.execute('''
            SELECT symbol, readiness_status, readiness_pct,
                   win_rate, profit_factor, expectancy, closed_trades
            FROM readiness_status
            ORDER BY readiness_pct DESC
        ''')

        for row in cursor.fetchall():
            status = row['readiness_status']
            readiness[status].append({
                'symbol': row['symbol'],
                'pct': row['readiness_pct'],
                'wr': row['win_rate'] * 100,
                'pf': row['profit_factor'],
                'exp': row['expectancy'] * 100,
                'trades': row['closed_trades']
            })

        conn.close()
    except Exception as e:
        print(f"[DASHBOARD_ERROR] {e}")

    return readiness


_trade_details_cache = {"data": [], "timestamp": 0}

def get_trade_details():
    """Get last 50 closed trades with all details (cached)"""
    global _trade_details_cache
    current_time = time.time()

    # Use cache if less than 30 seconds old
    if current_time - _trade_details_cache["timestamp"] < 30 and _trade_details_cache["data"]:
        return _trade_details_cache["data"]

    db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
    trades = []

    if not os.path.exists(db_path):
        return trades

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get last 50 trades
        cursor.execute('''
            SELECT trade_id, symbol, side, entry_price, exit_price,
                   entry_ts, exit_ts, pnl_pct, pnl_usd, mfe_pct, mae_pct,
                   exit_reason, regime, size_usd, cost_edge_ok, learning_source
            FROM trades
            ORDER BY exit_ts DESC
            LIMIT 50
        ''')

        for row in cursor.fetchall():
            hold_s = (row['exit_ts'] or 0) - (row['entry_ts'] or 0)
            entry_time = datetime.utcfromtimestamp(row['entry_ts']).strftime('%H:%M:%S') if row['entry_ts'] else '—'
            exit_time = datetime.utcfromtimestamp(row['exit_ts']).strftime('%H:%M:%S') if row['exit_ts'] else '—'

            pnl_color = 'positive' if (row['pnl_usd'] or 0) > 0 else 'negative' if (row['pnl_usd'] or 0) < 0 else 'neutral'

            trades.append({
                'trade_id': row['trade_id'][:12] if row['trade_id'] else '—',
                'symbol': row['symbol'],
                'side': row['side'],
                'entry_price': f"{row['entry_price']:.8f}" if row['entry_price'] else '—',
                'exit_price': f"{row['exit_price']:.8f}" if row['exit_price'] else '—',
                'entry_time': entry_time,
                'exit_time': exit_time,
                'hold_s': f"{int(hold_s)}",
                'pnl_pct': f"{row['pnl_pct']*100:.4f}%" if row['pnl_pct'] else '—',
                'pnl_usd': f"${row['pnl_usd']:.8f}" if row['pnl_usd'] else '—',
                'pnl_color': pnl_color,
                'mfe_pct': f"{row['mfe_pct']*100:.2f}%" if row['mfe_pct'] else '—',
                'mae_pct': f"{row['mae_pct']*100:.2f}%" if row['mae_pct'] else '—',
                'mfe_mae': f"{row['mfe_pct']*100:.2f}% / {row['mae_pct']*100:.2f}%" if (row['mfe_pct'] is not None and row['mae_pct'] is not None) else '—',
                'exit_reason': row['exit_reason'] or '—',
                'regime': row['regime'] or '—',
            })

        conn.close()
        _trade_details_cache["data"] = trades
        _trade_details_cache["timestamp"] = current_time
    except Exception as e:
        print(f"[DASHBOARD_TRADES_ERROR] {e}")

    return trades


_pnl_trend_cache = {"data": {'labels': [], 'cumulative': [], 'pnl': []}, "timestamp": 0}

def get_pnl_trend():
    """Get PnL trend data for last 30 trades (cached)"""
    global _pnl_trend_cache
    current_time = time.time()

    # Use cache if less than 30 seconds old
    if current_time - _pnl_trend_cache["timestamp"] < 30 and _pnl_trend_cache["data"]['labels']:
        return _pnl_trend_cache["data"]

    db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
    trend = {'labels': [], 'cumulative': [], 'pnl': []}

    if not os.path.exists(db_path):
        return trend

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get last 30 trades
        cursor.execute('''
            SELECT pnl_usd, pnl_pct, exit_ts
            FROM trades
            ORDER BY exit_ts ASC
            LIMIT 30
        ''')

        cumulative_pnl = 0
        for idx, row in enumerate(cursor.fetchall(), 1):
            pnl_usd = row['pnl_usd'] or 0
            cumulative_pnl += pnl_usd
            trend['labels'].append(f"Trade {idx}")
            trend['cumulative'].append(round(cumulative_pnl, 8))
            trend['pnl'].append(round(pnl_usd, 8))

        conn.close()
        _pnl_trend_cache["data"] = trend
        _pnl_trend_cache["timestamp"] = current_time
    except Exception as e:
        print(f"[PNL_TREND_ERROR] {e}")

    return trend


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
