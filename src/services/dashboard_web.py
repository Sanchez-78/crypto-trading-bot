#!/usr/bin/env python3
"""
CryptoMaster Modern Web Dashboard (V10.25)
Complete responsive dashboard with live metrics and charts
"""

from flask import Flask, render_template_string, jsonify
import sqlite3
import json
import time
import subprocess
import re
import logging
import os

log = logging.getLogger(__name__)

def load_lifetime_metrics():
    """Load lifetime metrics from learning state file."""
    try:
        # Try multiple paths for flexibility
        paths = [
            "server_local_backups/paper_adaptive_learning_state.json",
            "/opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json",
            os.path.expanduser("~/cryptomaster/server_local_backups/paper_adaptive_learning_state.json"),
        ]

        for state_file in paths:
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    data = json.load(f)
                return {
                    "lifetime_n": data.get("lifetime_n", 0),
                    "lifetime_pf": data.get("lifetime_pf", 1.0),
                    "lifetime_expectancy": data.get("lifetime_expectancy", 0.0),
                }
    except Exception as e:
        log.warning(f"Could not load lifetime metrics: {e}")
    return {"lifetime_n": 0, "lifetime_pf": 1.0, "lifetime_expectancy": 0.0}


def _load_learning_state():
    """Load the adaptive-learning JSON state (durable, survives restarts)."""
    import json as _json
    paths = [
        "/opt/cryptomaster/server_local_backups/paper_adaptive_learning_state.json",
        "server_local_backups/paper_adaptive_learning_state.json",
    ]
    for sp in paths:
        try:
            if os.path.exists(sp):
                with open(sp) as f:
                    return _json.load(f)
        except Exception:
            continue
    return {}


def get_live_metrics_from_cache():
    """Return LIVE, restart-durable metrics for the dashboard/API.

    Data-source strategy (never read the dead `trades` table):
      * Headline WR / PF / lifetime_n / expectancy come from the adaptive
        learning JSON state (durable across restarts).
      * Per-session full trade detail (prices, exit_reason, USD pnl) comes from
        cache.sqlite:closed_trades — the active close sink, but EPHEMERAL: it is
        reset to empty on every bot restart.
      * If cache.sqlite is empty (just restarted), the trade list is rebuilt
        from the durable learning rolling window so the dashboard is never blank.
    Returns a metrics dict, or None only if no live source exists at all.
    """
    import sqlite3
    from datetime import datetime, timezone
    try:
        if os.path.exists('/opt/cryptomaster'):
            cache_path = '/opt/cryptomaster/local_learning_storage/cache.sqlite'
            pos_path = '/opt/cryptomaster/data/paper_open_positions.json'
        else:
            cache_path = 'local_learning_storage/cache.sqlite'
            pos_path = 'data/paper_open_positions.json'

        lifetime_metrics = load_lifetime_metrics()
        state = _load_learning_state()
        rolling = state.get('rolling100') or state.get('rolling50') or []
        lifetime_n = int(lifetime_metrics.get('lifetime_n', 0) or 0)

        # No durable source at all -> let caller use its legacy path.
        if not rolling and lifetime_n == 0:
            return None

        def _pnl(e):
            return e[0] if isinstance(e, (list, tuple)) and e and isinstance(e[0], (int, float)) else 0.0

        def _outcome(e):
            if isinstance(e, (list, tuple)):
                for x in e:
                    if isinstance(x, str) and x.upper() in ('WIN', 'LOSS', 'FLAT'):
                        return x.upper()
                return 'WIN' if _pnl(e) > 0 else 'LOSS'
            return ''

        roll_n = len(rolling)
        roll_wins = sum(1 for e in rolling if _outcome(e) == 'WIN')
        win_rate = (roll_wins / roll_n * 100.0) if roll_n else 0.0

        # --- Per-session detail from cache.sqlite (may be empty after restart) ---
        session_n = 0
        session_net = 0.0
        exits = {'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0}
        closed_trades_list = []
        if os.path.exists(cache_path):
            try:
                conn = sqlite3.connect(cache_path, timeout=2)
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT COUNT(*), SUM(COALESCE(pnl_usd,0)) FROM closed_trades"
                ).fetchone() or (0, 0)
                session_n = int(row[0] or 0)
                session_net = float(row[1] or 0)
                for reason, cnt in cur.execute(
                    "SELECT LOWER(COALESCE(exit_reason,'')), COUNT(*) "
                    "FROM closed_trades GROUP BY LOWER(COALESCE(exit_reason,''))"
                ):
                    if reason == 'tp':
                        exits['tp'] = cnt
                    elif reason == 'sl':
                        exits['sl'] = cnt
                    elif 'scratch' in reason:
                        exits['scratch'] += cnt
                    elif 'stag' in reason:
                        exits['stagnation'] += cnt
                    elif 'timeout' in reason:
                        exits['timeout'] += cnt
                for r in cur.execute(
                    "SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
                    "exit_reason, entry_ts, exit_ts, regime, win "
                    "FROM closed_trades ORDER BY exit_ts DESC LIMIT 30"
                ):
                    tid, sym, ep, xp, pu, pp, reason, ets, xts, regime, win = r
                    ep = float(ep or 0)
                    xp = float(xp or 0)
                    if pp is None:
                        pp = ((xp / ep - 1.0) * 100.0) if ep else 0.0
                    ets = float(ets or 0)
                    xts = float(xts or 0)
                    closed_trades_list.append({
                        'trade_id': tid, 'symbol': sym, 'side': 'BUY',
                        'entry_price': ep, 'exit_price': xp,
                        'pnl_pct': float(pp or 0), 'pnl_usd': float(pu or 0),
                        'reason': reason, 'exit_reason': reason,
                        'hold_s': int(xts - ets) if (xts and ets) else 0,
                        'regime': regime or 'UNKNOWN', 'win': int(win or 0),
                        'exit_time': int(xts) if xts else 0,
                        'entry_timestamp': datetime.fromtimestamp(ets, tz=timezone.utc).isoformat().replace('+00:00', 'Z') if ets else '',
                        'exit_timestamp': datetime.fromtimestamp(xts, tz=timezone.utc).isoformat().replace('+00:00', 'Z') if xts else '',
                    })
                conn.close()
            except Exception:
                pass

        # --- Fallback list from durable rolling window (cache empty post-restart) ---
        if not closed_trades_list and rolling:
            for e in reversed(rolling[-30:]):
                if not isinstance(e, (list, tuple)) or len(e) < 3:
                    continue
                seg = next((x for x in e if isinstance(x, str) and ':' in x), '::')
                parts = seg.split(':')
                ts = next((x for x in e if isinstance(x, (int, float)) and x > 1e9), 0)
                outcome = _outcome(e)
                closed_trades_list.append({
                    'trade_id': '', 'symbol': parts[0] if parts else '?', 'side': parts[2] if len(parts) > 2 else 'BUY',
                    'entry_price': 0, 'exit_price': 0,
                    'pnl_pct': round(_pnl(e), 4), 'pnl_usd': 0.0,
                    'reason': outcome, 'exit_reason': outcome,
                    'hold_s': 0, 'regime': parts[1] if len(parts) > 1 else 'UNKNOWN',
                    'win': 1 if outcome == 'WIN' else 0,
                    'exit_time': int(ts),
                    'entry_timestamp': '',
                    'exit_timestamp': datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace('+00:00', 'Z') if ts else '',
                })

        # --- Open positions ---
        open_positions_list = []
        try:
            import json as _json
            with open(pos_path) as f:
                positions = _json.load(f)
            now_ts = time.time()
            iterable = positions.items() if isinstance(positions, dict) else enumerate(positions)
            for pid, p in iterable:
                ets = float(p.get('entry_ts', now_ts))
                open_positions_list.append({
                    'trade_id': str(pid)[:12], 'symbol': p.get('symbol', 'N/A'),
                    'side': p.get('side', 'BUY'),
                    'entry_price': float(p.get('entry_price', 0)),
                    'current_price': float(p.get('last_price', p.get('entry_price', 0))),
                    'tp': float(p.get('tp', 0)), 'sl': float(p.get('sl', 0)),
                    'entry_ts': ets, 'age_seconds': int(now_ts - ets),
                    'current_hold_s': int(now_ts - ets),
                    'regime': p.get('regime', 'N/A'),
                    'size_usd': float(p.get('size_usd', 0.5)),
                    'pnl_pct': 0.0, 'status': 'OPEN',
                    'entry_timestamp': datetime.fromtimestamp(ets, tz=timezone.utc).isoformat().replace('+00:00', 'Z'),
                })
        except Exception:
            pass

        iso = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        return {
            'closed_trades': lifetime_n,
            'session_closed_trades': session_n,
            'lifetime_closed_trades': lifetime_n,
            'open_positions': len(open_positions_list),
            'open_positions_list': open_positions_list,
            'closed_trades_list': closed_trades_list,
            'profit_factor': round(float(lifetime_metrics.get('lifetime_pf', 0.0) or 0.0), 3),
            'win_rate_pct': round(win_rate, 2),
            'win_rate_window': roll_n,
            'net_pnl': round(session_net, 6),
            'exit_distribution': exits,
            'timestamp': iso,
            'last_update': iso,
            'data_source': 'learning_state+cache.sqlite',
            'lifetime_metrics': {
                'lifetime_n': lifetime_n,
                'lifetime_pf': lifetime_metrics.get('lifetime_pf', 0.0),
                'lifetime_expectancy': lifetime_metrics.get('lifetime_expectancy', 0.0),
            },
        }
    except Exception as e:
        import sys
        print(f"[DASHBOARD] live metrics read failed: {e}", file=sys.stderr, flush=True)
        return None

# Start readiness monitoring (will auto-start background thread)
try:
    import src.services.readiness_monitor  # noqa: Starts background monitoring
except Exception as e:
    log.warning(f"Could not start readiness monitoring: {e}")

def populate_trades_from_logs():
    """Parse [PAPER_EXIT] logs and save trades to database"""
    try:
        # Get recent logs via os.system to file
        import os
        os.system("journalctl -u cryptomaster.service --since '2 hours ago' --no-pager -q > /tmp/trades_logs.txt 2>/dev/null")

        try:
            with open('/tmp/trades_logs.txt', 'r') as f:
                logs = f.read()
        except:
            logs = ""

        conn = sqlite3.connect("/opt/cryptomaster/local_learning_storage/learning_database.sqlite", timeout=2)
        cursor = conn.cursor()

        # Parse [PAPER_EXIT] lines
        for line in logs.split('\n'):
            if '[PAPER_EXIT]' not in line:
                continue

            try:
                trade_id = re.search(r'trade_id=(\S+)', line)
                symbol = re.search(r'symbol=(\S+)', line)
                entry = re.search(r'entry=([\d.]+)', line)
                exit_p = re.search(r'exit=([\d.]+)', line)
                pnl_pct = re.search(r'net_pnl_pct=([\d.\-eE+]+)', line)
                reason = re.search(r'reason=(\S+)', line)
                hold = re.search(r'hold_s=([\d.]+)', line)
                outcome = re.search(r'outcome=(\S+)', line)

                if all([trade_id, symbol, entry, exit_p, pnl_pct]):
                    entry_val = float(entry.group(1))
                    exit_val = float(exit_p.group(1))
                    pnl_pct_val = float(pnl_pct.group(1))
                    pnl_usd = entry_val * pnl_pct_val / 100.0

                    cursor.execute("""
                        INSERT OR IGNORE INTO trades
                        (trade_id, symbol, entry_price, exit_price, pnl_pct, pnl_usd, exit_reason, entry_ts, exit_ts)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        trade_id.group(1),
                        symbol.group(1),
                        entry_val,
                        exit_val,
                        pnl_pct_val,
                        pnl_usd,
                        reason.group(1) if reason else 'UNKNOWN',
                        int(time.time()) - 60,  # Approximate
                        int(time.time())
                    ))
            except:
                pass

        conn.commit()
        conn.close()
    except:
        pass

app = Flask(__name__)

# HTML Dashboard Template
HTML_TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CryptoMaster Trading Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #e0e0e0;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1400px; margin: 0 auto; }

        header {
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 2px solid #1e90ff;
            padding-bottom: 20px;
        }
        h1 { color: #1e90ff; font-size: 32px; margin-bottom: 10px; }
        .status { color: #00ff00; font-size: 12px; }
        .timestamp { color: #888; font-size: 12px; margin-top: 10px; }

        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .metric-card {
            background: rgba(26, 31, 58, 0.8);
            border: 1px solid #2a3f5f;
            border-radius: 12px;
            padding: 25px;
            text-align: center;
            transition: transform 0.2s, border-color 0.2s;
            backdrop-filter: blur(10px);
        }
        .metric-card:hover {
            transform: translateY(-5px);
            border-color: #1e90ff;
        }

        .metric-label {
            font-size: 11px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 10px;
        }

        .metric-value {
            font-size: 36px;
            font-weight: bold;
            margin-bottom: 5px;
            font-variant-numeric: tabular-nums;
        }

        .metric-change {
            font-size: 12px;
            color: #aaa;
        }

        .positive { color: #00ff00; }
        .negative { color: #ff4444; }
        .neutral { color: #ffaa00; }

        .charts-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }

        .chart-container {
            background: rgba(26, 31, 58, 0.8);
            border: 1px solid #2a3f5f;
            border-radius: 12px;
            padding: 25px;
            position: relative;
        }

        .chart-title {
            color: #1e90ff;
            font-weight: bold;
            margin-bottom: 20px;
            font-size: 14px;
        }

        .stats-table {
            width: 100%;
            background: rgba(26, 31, 58, 0.8);
            border: 1px solid #2a3f5f;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 40px;
        }

        .stats-table h3 {
            color: #1e90ff;
            margin-bottom: 15px;
        }

        table {
            width: 100%;
            border-collapse: collapse;
        }

        th {
            background: rgba(15, 23, 41, 0.8);
            padding: 12px;
            text-align: left;
            font-weight: bold;
            color: #1e90ff;
            border-bottom: 2px solid #2a3f5f;
            font-size: 12px;
        }

        td {
            padding: 12px;
            border-bottom: 1px solid #2a3f5f;
            font-size: 13px;
        }

        tr:hover { background: rgba(30, 144, 255, 0.05); }

        .footer {
            text-align: center;
            color: #666;
            font-size: 11px;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #2a3f5f;
        }

        .loading {
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #00ff00;
            border-radius: 50%;
            margin-left: 10px;
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }

        @media (max-width: 768px) {
            .metrics-grid { grid-template-columns: 1fr; }
            .charts-section { grid-template-columns: 1fr; }
            h1 { font-size: 24px; }
            .metric-value { font-size: 28px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🤖 CryptoMaster Trading Dashboard</h1>
            <div class="status">
                <span>LIVE</span>
                <span class="loading"></span>
            </div>
            <div class="timestamp" id="timestamp"></div>
        </header>

        <!-- Metrics Grid -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">Closed Trades</div>
                <div class="metric-value" id="closed_trades">0</div>
                <div class="metric-change" id="closed_change">+0</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Profit Factor</div>
                <div class="metric-value" id="profit_factor">0.00x</div>
                <div class="metric-change" id="pf_status">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Win Rate</div>
                <div class="metric-value" id="win_rate">0.0%</div>
                <div class="metric-change" id="wr_status">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Net P&L</div>
                <div class="metric-value" id="net_pnl">$0.00</div>
                <div class="metric-change" id="pnl_status">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Open Positions</div>
                <div class="metric-value" id="open_positions">0</div>
                <div class="metric-change" id="open_change">—</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Last Update</div>
                <div class="metric-value" id="update_status" style="font-size: 14px;">Loading...</div>
                <div class="metric-change" id="refresh_rate">5s refresh</div>
            </div>
        </div>

        <!-- Charts Section -->
        <div class="charts-section">
            <div class="chart-container">
                <div class="chart-title">Exit Distribution</div>
                <canvas id="exitChart"></canvas>
            </div>

            <div class="chart-container">
                <div class="chart-title">Win/Loss Distribution</div>
                <canvas id="winlossChart"></canvas>
            </div>
        </div>

        <!-- Open Positions Table -->
        <div class="stats-table">
            <h3>📈 Open Positions (<span id="openPosCount">0</span> active)</h3>
            <table id="openPositionsTable">
                <thead>
                    <tr>
                        <th>Trade ID</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry Price</th>
                        <th>TP</th>
                        <th>SL</th>
                        <th>Hold (s)</th>
                        <th>Regime</th>
                        <th>Size (USD)</th>
                        <th>P&L %</th>
                    </tr>
                </thead>
                <tbody id="openPositionsBody">
                    <tr><td colspan="10" style="text-align: center; color: #888;">Loading open positions...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Stats Table -->
        <div class="stats-table">
            <h3>📊 Trading Statistics</h3>
            <table>
                <thead>
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Total Closed Trades</td>
                        <td id="stat_closed">0</td>
                        <td id="stat_closed_status">—</td>
                    </tr>
                    <tr>
                        <td>Profit Factor</td>
                        <td id="stat_pf">0.00x</td>
                        <td id="stat_pf_status">Insufficient data</td>
                    </tr>
                    <tr>
                        <td>Win Rate</td>
                        <td id="stat_wr">0.0%</td>
                        <td id="stat_wr_status">—</td>
                    </tr>
                    <tr>
                        <td>Cumulative P&L</td>
                        <td id="stat_pnl">$0.00</td>
                        <td id="stat_pnl_status">—</td>
                    </tr>
                    <tr>
                        <td>Avg Trade Duration</td>
                        <td id="stat_duration">0s</td>
                        <td id="stat_duration_status">—</td>
                    </tr>
                </tbody>
            </table>
        </div>

        <!-- Learning Adjustment Process -->
        <div class="stats-table">
            <h3>🤖 Learning Adjustment Process</h3>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">
                <div style="background: rgba(15, 23, 41, 0.8); padding: 15px; border-radius: 8px;">
                    <div style="color: #888; font-size: 11px; margin-bottom: 5px;">LEARNING STATUS</div>
                    <div id="learning_enabled" style="font-size: 16px; font-weight: bold; color: #00ff00;">—</div>
                </div>
                <div style="background: rgba(15, 23, 41, 0.8); padding: 15px; border-radius: 8px;">
                    <div style="color: #888; font-size: 11px; margin-bottom: 5px;">LEARNING BLEND</div>
                    <div id="learning_blend" style="font-size: 16px; font-weight: bold; color: #1e90ff;">0.0%</div>
                </div>
                <div style="background: rgba(15, 23, 41, 0.8); padding: 15px; border-radius: 8px;">
                    <div style="color: #888; font-size: 11px; margin-bottom: 5px;">ENTRY QUALITY GATE</div>
                    <div id="entry_quality" style="font-size: 16px; font-weight: bold; color: #ffaa00;">—</div>
                </div>
                <div style="background: rgba(15, 23, 41, 0.8); padding: 15px; border-radius: 8px;">
                    <div style="color: #888; font-size: 11px; margin-bottom: 5px;">LIFETIME CLOSES</div>
                    <div id="lifetime_closes" style="font-size: 16px; font-weight: bold; color: #e0e0e0;">0</div>
                </div>
            </div>

            <h4 style="color: #1e90ff; margin-top: 20px; margin-bottom: 10px; font-size: 12px;">Regime TP Strategy (Adaptive Targets)</h4>
            <table id="regimeTable">
                <thead>
                    <tr>
                        <th>Regime</th>
                        <th>Volatility</th>
                        <th>TP Target %</th>
                        <th>Win Rate</th>
                        <th>Closes (n)</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody id="regimeBody">
                    <tr><td colspan="6" style="text-align: center; color: #888;">Loading regime data...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Recent Trades Table -->
        <div class="stats-table">
            <h3>📋 Last 30 Closed Trades</h3>
            <table id="tradesTable">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Entry Price</th>
                        <th>Exit Price</th>
                        <th>P&L %</th>
                        <th>P&L $</th>
                        <th>Exit Reason</th>
                        <th>Hold Time</th>
                    </tr>
                </thead>
                <tbody id="tradesBody">
                    <tr><td colspan="9" style="text-align: center; color: #888;">Loading trades...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="footer">
            CryptoMaster V10.25 | Live Paper Trading Dashboard | Auto-refresh every 5 seconds
        </div>
    </div>

    <script>
        let exitChart = null;
        let winlossChart = null;
        let lastData = {};

        async function fetchMetrics() {
            try {
                const response = await fetch('/api/dashboard/metrics');
                if (!response.ok) throw new Error('API error');
                return await response.json();
            } catch (e) {
                console.error('Fetch error:', e);
                return null;
            }
        }

        async function fetchTrades() {
            try {
                const response = await fetch('/api/trades/recent');
                if (!response.ok) throw new Error('API error');
                return await response.json();
            } catch (e) {
                console.error('Trades fetch error:', e);
                return [];
            }
        }

        async function fetchLearningState() {
            try {
                const response = await fetch('/api/dashboard/learning-state');
                if (!response.ok) throw new Error('API error');
                return await response.json();
            } catch (e) {
                console.error('Learning state fetch error:', e);
                return null;
            }
        }

        function updateLearningMetrics(data) {
            if (!data) return;

            // Update learning status indicators
            document.getElementById('learning_enabled').textContent =
                data.learning_enabled ? '✓ ACTIVE' : '○ INACTIVE';
            document.getElementById('learning_enabled').style.color =
                data.learning_enabled ? '#00ff00' : '#888';

            document.getElementById('learning_blend').textContent =
                (data.learning_blend * 100).toFixed(1) + '%';

            const entryQuality = data.entry_quality_gate || {};
            document.getElementById('entry_quality').textContent =
                entryQuality.passing ? '✓ PASS' : '✗ FAIL';
            document.getElementById('entry_quality').style.color =
                entryQuality.passing ? '#00ff00' : '#ff4444';

            document.getElementById('lifetime_closes').textContent =
                data.lifetime_closes || 0;

            // Update regime TP strategy table
            const regimeBody = document.getElementById('regimeBody');
            const regimeData = data.regime_tp_strategy || {};

            let rows = [];
            for (const [regime, volBands] of Object.entries(regimeData)) {
                for (const [volBand, stats] of Object.entries(volBands || {})) {
                    const tpPct = stats.tp_pct || 0;
                    const wr = (stats.wr || 0) * 100;
                    const n = stats.n || 0;
                    const wrStatus = wr >= 55 ? '✓ HIGH' : wr >= 45 ? '• MID' : '✗ LOW';
                    const wrColor = wr >= 55 ? '#00ff00' : wr >= 45 ? '#ffaa00' : '#ff4444';

                    rows.push(`
                        <tr>
                            <td><strong>${regime}</strong></td>
                            <td>${volBand.replace('_', ' ').toUpperCase()}</td>
                            <td><strong>${(tpPct * 100).toFixed(2)}%</strong></td>
                            <td style="color: ${wrColor};">${wr.toFixed(1)}%</td>
                            <td>${n}</td>
                            <td style="color: ${wrColor};">${wrStatus}</td>
                        </tr>
                    `);
                }
            }

            if (rows.length === 0) {
                regimeBody.innerHTML = '<tr><td colspan="6" style="text-align: center; color: #888;">No regime data yet</td></tr>';
            } else {
                regimeBody.innerHTML = rows.join('');
            }
        }

        function updateTradesTable(trades) {
            const tbody = document.getElementById('tradesBody');
            if (!trades || trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: #888;">No trades yet</td></tr>';
                return;
            }

            tbody.innerHTML = trades.map(t => {
                const pnlClass = t.pnl_pct >= 0 ? 'positive' : 'negative';
                const pnlUsdClass = t.pnl_usd >= 0 ? 'positive' : 'negative';

                // Handle both ISO timestamp strings and Unix timestamps
                let timeStr = '—';
                if (t.exit_ts) {
                    if (typeof t.exit_ts === 'string') {
                        // ISO timestamp
                        timeStr = new Date(t.exit_ts).toLocaleString();
                    } else if (typeof t.exit_ts === 'number') {
                        // Unix timestamp
                        timeStr = new Date(t.exit_ts * (t.exit_ts < 100000000000 ? 1000 : 1)).toLocaleString();
                    }
                }

                return `<tr>
                    <td>${timeStr}</td>
                    <td><strong>${t.symbol}</strong></td>
                    <td>${t.side || '—'}</td>
                    <td>$${parseFloat(t.entry_price).toFixed(4)}</td>
                    <td>$${parseFloat(t.exit_price).toFixed(4)}</td>
                    <td class="${pnlClass}">${(t.pnl_pct || 0).toFixed(4)}%</td>
                    <td class="${pnlUsdClass}">${(t.pnl_usd >= 0 ? '+' : '')}\$${(t.pnl_usd || 0).toFixed(8)}</td>
                    <td>${t.exit_reason || '—'}</td>
                    <td>${t.hold_s ? Math.round(t.hold_s) + 's' : '—'}</td>
                </tr>`;
            }).join('');
        }

        function updateOpenPositionsTable(positions) {
            const tbody = document.getElementById('openPositionsBody');
            const countEl = document.getElementById('openPosCount');
            if (countEl) countEl.textContent = (positions && positions.length) || 0;

            if (!positions || positions.length === 0) {
                tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #888;">No open positions</td></tr>';
                return;
            }

            tbody.innerHTML = positions.map(p => {
                const pnlClass = p.pnl_pct >= 0 ? 'positive' : 'negative';
                return `<tr>
                    <td>${p.trade_id || '—'}</td>
                    <td><strong>${p.symbol || '—'}</strong></td>
                    <td>${p.side || '—'}</td>
                    <td>$${(parseFloat(p.entry_price) || 0).toFixed(4)}</td>
                    <td>$${(parseFloat(p.tp) || 0).toFixed(4)}</td>
                    <td>$${(parseFloat(p.sl) || 0).toFixed(4)}</td>
                    <td>${Math.round(p.current_hold_s || 0)}s</td>
                    <td>${p.regime || '—'}</td>
                    <td>$${(parseFloat(p.size_usd) || 0).toFixed(2)}</td>
                    <td class="${pnlClass}">${(p.pnl_pct || 0).toFixed(4)}%</td>
                </tr>`;
            }).join('');
        }

        function updateCharts(data) {
            if (!data) return;

            // Exit Distribution Chart
            const exitCtx = document.getElementById('exitChart');
            if (exitChart) exitChart.destroy();

            const exits = data.exit_distribution || {};
            exitChart = new Chart(exitCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Timeout', 'TP', 'SL', 'Scratch', 'Stagnation'],
                    datasets: [{
                        data: [
                            exits.timeout || 0,
                            exits.tp || 0,
                            exits.sl || 0,
                            exits.scratch || 0,
                            exits.stagnation || 0
                        ],
                        backgroundColor: ['#1e90ff', '#00ff00', '#ff4444', '#ffaa00', '#ff00ff'],
                        borderColor: '#0a0e27',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: { legend: { labels: { color: '#e0e0e0' } } }
                }
            });

            // Win/Loss Chart
            const winlossCtx = document.getElementById('winlossChart');
            if (winlossChart) winlossChart.destroy();

            const totalTrades = data.closed_trades || 1;
            const wins = Math.round(totalTrades * (data.win_rate_pct || 0) / 100);
            const losses = totalTrades - wins;

            winlossChart = new Chart(winlossCtx, {
                type: 'doughnut',
                data: {
                    labels: ['Wins', 'Losses'],
                    datasets: [{
                        data: [wins, losses],
                        backgroundColor: ['#00ff00', '#ff4444'],
                        borderColor: '#0a0e27',
                        borderWidth: 2
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: true,
                    plugins: { legend: { labels: { color: '#e0e0e0' } } }
                }
            });
        }

        function formatValue(value, type) {
            if (type === 'pnl') {
                const sign = value >= 0 ? '+' : '';
                return sign + '$' + Math.abs(value).toFixed(8);
            }
            if (type === 'pf') return value.toFixed(2) + 'x';
            if (type === 'pct') return value.toFixed(1) + '%';
            return value;
        }

        function getStatusClass(pf, wr) {
            if (pf >= 1.05) return 'positive';
            if (pf >= 1.0) return 'neutral';
            return 'negative';
        }

        async function updateDashboard() {
            const data = await fetchMetrics();
            const learningData = await fetchLearningState();
            if (!data) return;

            lastData = data;

            // Update learning metrics
            if (learningData) {
                updateLearningMetrics(learningData);
            }

            // Update metrics
            document.getElementById('closed_trades').textContent = data.closed_trades || 0;
            document.getElementById('profit_factor').textContent = formatValue(data.profit_factor || 0, 'pf');
            document.getElementById('profit_factor').className = 'metric-value ' + getStatusClass(data.profit_factor || 0, data.win_rate_pct || 0);
            document.getElementById('win_rate').textContent = formatValue(data.win_rate_pct || 0, 'pct');
            document.getElementById('net_pnl').textContent = formatValue(data.net_pnl || 0, 'pnl');
            document.getElementById('net_pnl').className = 'metric-value ' + (data.net_pnl >= 0 ? 'positive' : 'negative');
            document.getElementById('open_positions').textContent = data.open_positions || 0;
            document.getElementById('update_status').textContent = new Date().toLocaleTimeString();

            // Update status indicators
            document.getElementById('pf_status').textContent =
                data.profit_factor >= 1.05 ? '✓ Profitable' :
                data.profit_factor >= 1.0 ? '• Break-even' :
                '✗ Learning';
            document.getElementById('pf_status').className = 'metric-change ' + getStatusClass(data.profit_factor || 0);

            document.getElementById('wr_status').textContent =
                data.win_rate_pct >= 55 ? '✓ Above avg' :
                data.win_rate_pct >= 45 ? '• Average' :
                '✗ Below avg';

            document.getElementById('pnl_status').textContent =
                data.net_pnl > 0 ? '✓ Positive' :
                data.net_pnl === 0 ? '• Break-even' :
                '✗ Negative';

            // Update stats table
            document.getElementById('stat_closed').textContent = data.closed_trades || 0;
            document.getElementById('stat_pf').textContent = formatValue(data.profit_factor || 0, 'pf');
            document.getElementById('stat_wr').textContent = formatValue(data.win_rate_pct || 0, 'pct');
            document.getElementById('stat_pnl').textContent = formatValue(data.net_pnl || 0, 'pnl');

            // Update status text
            document.getElementById('stat_pf_status').textContent =
                data.profit_factor >= 1.05 ? '✓ Edge detected' :
                data.profit_factor >= 1.0 ? '• Near edge' :
                '✗ No edge yet';
            document.getElementById('stat_pf_status').className = getStatusClass(data.profit_factor || 0);

            // Update timestamp
            document.getElementById('timestamp').textContent =
                'Updated: ' + new Date(data.last_update).toLocaleString() + ' UTC';

            // Update open positions table
            updateOpenPositionsTable(data.open_positions_list || []);

            // Update charts
            updateCharts(data);

            // Update trades table
            const trades = await fetchTrades();
            updateTradesTable(trades);
        }

        // Initial load
        updateDashboard();

        // Auto-refresh every 5 seconds
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/dashboard/metrics')
def metrics():
    try:
        from datetime import datetime, timezone
        # LIVE FIX (2026-07-03): read from cache.sqlite (the active close sink)
        # first. The legacy `trades` table is frozen since commit 8abefe25
        # removed its writer, which made the dashboard show stale June-26 data.
        _live = get_live_metrics_from_cache()
        if _live is not None:
            return jsonify(_live)
        # Forward to cryptomaster's actual metrics API
        import urllib.request
        import json as json_module

        # Get metrics from cryptomaster's actual dashboard API on port 5000
        try:
            response = urllib.request.urlopen('http://localhost:5000/api/dashboard/metrics', timeout=5)
            real_metrics = json_module.loads(response.read().decode())

            # Extract metrics (cryptomaster already returns correct format)
            closed_trades = real_metrics.get('closed_trades', 0) or 0
            win_rate = real_metrics.get('win_rate_pct', 0) or 0
            net_pnl = real_metrics.get('net_pnl', 0) or 0.0
            profit_factor = real_metrics.get('profit_factor', 0) or 0.0
            open_positions_list = real_metrics.get('open_positions_list', []) or []

            # Add timestamps to open positions
            now_ts = time.time()
            for pos in open_positions_list:
                try:
                    entry_ts = float(pos.get('entry_ts', now_ts))
                    entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
                    entry_iso = entry_dt.isoformat().replace('+00:00', 'Z')
                    pos['entry_timestamp'] = entry_iso
                    pos['age_seconds'] = int(now_ts - entry_ts)
                except Exception as e:
                    pass

            # Bot API returns recent_trades, convert to closed_trades_list for dashboard
            recent_trades = real_metrics.get('recent_trades', []) or []
            closed_trades_list = []
            for t in recent_trades:
                # Exit timestamp: use exit_ts if available, else estimate from now - hold_s
                hold_s = float(t.get('hold_s', 0))
                if t.get('exit_ts'):
                    exit_ts = float(t.get('exit_ts'))
                else:
                    # Estimate: assume trade closed recently, so exit ~now - hold_s
                    exit_ts = now_ts - hold_s if hold_s > 0 else now_ts

                exit_dt = datetime.fromtimestamp(exit_ts, tz=timezone.utc)
                exit_iso = exit_dt.isoformat().replace('+00:00', 'Z')
                closed_trades_list.append({
                    'trade_id': t.get('trade_id', ''),
                    'symbol': t.get('symbol', ''),
                    'side': t.get('side', 'BUY'),
                    'entry_price': float(t.get('entry_price', 0)),
                    'exit_price': float(t.get('exit_price', 0)),
                    'pnl_pct': float(t.get('pnl_pct', 0)),
                    'reason': t.get('exit_reason', 'UNKNOWN'),
                    'hold_s': hold_s,
                    'exit_time': int(exit_ts),
                    'exit_timestamp': exit_iso
                })

            # Generate ISO timestamp
            iso_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

            # Only return API metrics if they contain actual trades
            # (Bot API gets metrics from logs which may be empty/rotated, so 0 trades means unreliable data)
            # NOTE: Always query database for exit_distribution (don't rely on bot API for accurate exit reasons)
            if closed_trades > 0:
                # Query database for accurate exit_distribution (bot API may have hardcoded/stale data)
                try:
                    db_conn = sqlite3.connect("/opt/cryptomaster/local_learning_storage/learning_database.sqlite", timeout=2)
                    db_cursor = db_conn.cursor()
                    db_cursor.execute("""
                        SELECT
                            SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) = 'tp' THEN 1 ELSE 0 END) as tp,
                            SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) = 'sl' THEN 1 ELSE 0 END) as sl,
                            SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) IN ('scratch', 'scratch_exit') THEN 1 ELSE 0 END) as scratch,
                            SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) IN ('stagnation', 'stagnation_exit') THEN 1 ELSE 0 END) as stagnation,
                            SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) IN ('timeout', 'stale_timeout') THEN 1 ELSE 0 END) as timeout
                        FROM trades
                    """)
                    tp, sl, scratch, stagnation, timeout = db_cursor.fetchone() or (0, 0, 0, 0, 0)
                    db_conn.close()
                    db_exit_distribution = {
                        'tp': int(tp) if tp else 0,
                        'sl': int(sl) if sl else 0,
                        'scratch': int(scratch) if scratch else 0,
                        'stagnation': int(stagnation) if stagnation else 0,
                        'timeout': int(timeout) if timeout else 0
                    }
                except:
                    db_exit_distribution = real_metrics.get('exit_distribution', {})

                # Load lifetime metrics from learning state
                lifetime_metrics = load_lifetime_metrics()

                return jsonify({
                    "closed_trades": int(closed_trades),
                    "lifetime_closed_trades": lifetime_metrics["lifetime_n"],
                    "open_positions": real_metrics.get('open_positions', 0) or 0,
                    "open_positions_list": open_positions_list,
                    "closed_trades_list": closed_trades_list,
                    "profit_factor": float(profit_factor),
                    "win_rate_pct": float(win_rate),
                    "net_pnl": float(net_pnl),
                    "exit_distribution": db_exit_distribution,
                    "timestamp": iso_timestamp,
                    "last_update": iso_timestamp,
                    "lifetime_metrics": {
                        "lifetime_n": lifetime_metrics["lifetime_n"],
                        "lifetime_pf": lifetime_metrics["lifetime_pf"],
                        "lifetime_expectancy": lifetime_metrics["lifetime_expectancy"]
                    }
                })
            else:
                # API returned 0 trades - log-based metrics are unreliable
                # Fall through to database fallback
                import sys
                print(f"[DASH] Port 5000 API returned 0 trades (log-based metrics unreliable). Using database...", file=sys.stderr, flush=True)
        except Exception as api_error:
            import sys
            print(f"[DASH] Port 5000 API failed: {api_error}", file=sys.stderr, flush=True)

        # FALLBACK: Try database if API unavailable or API returned 0 trades
        conn = sqlite3.connect("/opt/cryptomaster/local_learning_storage/learning_database.sqlite", timeout=2)
        cursor = conn.cursor()

        # Get all trade statistics (extended to include exit_reason counts)
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl_usd) as net_pnl,
                SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) = 'tp' THEN 1 ELSE 0 END) as tp_cnt,
                SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) = 'sl' THEN 1 ELSE 0 END) as sl_cnt,
                SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) IN ('scratch', 'scratch_exit') THEN 1 ELSE 0 END) as scratch_cnt,
                SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) IN ('stagnation', 'stagnation_exit') THEN 1 ELSE 0 END) as stagnation_cnt,
                SUM(CASE WHEN LOWER(COALESCE(exit_reason, '')) IN ('timeout', 'stale_timeout') THEN 1 ELSE 0 END) as timeout_cnt
            FROM trades
        """)
        total, wins, net_pnl, tp_cnt, sl_cnt, scratch_cnt, stagnation_cnt, timeout_cnt = cursor.fetchone() or (0, 0, 0, 0, 0, 0, 0, 0)

        # Fallback: compute from database
        closed_trades = int(total) if total else 0
        wins = int(wins) if wins else 0
        net_pnl = float(net_pnl) if net_pnl else 0.0
        win_rate = (wins / closed_trades * 100) if closed_trades > 0 else 0.0
        losses = closed_trades - wins if closed_trades > 0 else 0
        profit_factor = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)

        # Build exit distribution from query results (computed above)
        exits = {
            'tp': int(tp_cnt) if tp_cnt else 0,
            'sl': int(sl_cnt) if sl_cnt else 0,
            'scratch': int(scratch_cnt) if scratch_cnt else 0,
            'stagnation': int(stagnation_cnt) if stagnation_cnt else 0,
            'timeout': int(timeout_cnt) if timeout_cnt else 0
        }

        iso_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        conn.close()

        # Load open positions from JSON (fallback)
        open_positions = 0
        open_positions_list = []
        try:
            import json as json_module
            with open('/opt/cryptomaster/data/paper_open_positions.json') as f:
                positions = json_module.load(f)
                open_positions = len(positions)
                for pos_id, pos_data in (positions.items() if isinstance(positions, dict) else enumerate(positions)):
                    entry_ts = float(pos_data.get('entry_ts', time.time()))
                    pos_dict = {
                        'trade_id': str(pos_id)[:8],
                        'symbol': pos_data.get('symbol', 'N/A'),
                        'side': pos_data.get('side', 'BUY'),
                        'entry_price': float(pos_data.get('entry_price', 0)),
                        'current_price': float(pos_data.get('last_price', pos_data.get('entry_price', 0))),
                        'tp': float(pos_data.get('tp', 0)),
                        'sl': float(pos_data.get('sl', 0)),
                        'entry_ts': entry_ts,
                        'current_hold_s': int(time.time() - entry_ts),
                        'regime': pos_data.get('regime', 'N/A'),
                        'size_usd': float(pos_data.get('size_usd', 0.5)),
                        'pnl_pct': 0.0,
                        'status': 'OPEN'
                    }
                    # Add ISO timestamp for entry (fallback path)
                    try:
                        now_ts = time.time()
                        entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
                        pos_dict['entry_timestamp'] = entry_dt.isoformat().replace('+00:00', 'Z')
                        pos_dict['age_seconds'] = int(now_ts - entry_ts)
                    except:
                        pos_dict['entry_timestamp'] = None
                        pos_dict['age_seconds'] = None
                    open_positions_list.append(pos_dict)
        except:
            pass

        # Load closed trades from database for fallback
        closed_trades_list = []
        try:
            conn2 = sqlite3.connect("/opt/cryptomaster/local_learning_storage/learning_database.sqlite", timeout=2)
            cursor2 = conn2.cursor()
            cursor2.execute("SELECT trade_id, symbol, entry_price, exit_price, pnl_pct, pnl_usd, exit_reason, hold_s, entry_ts, exit_ts FROM trades ORDER BY exit_ts DESC LIMIT 30")
            for row in cursor2.fetchall():
                entry_ts = row[8] if row[8] else time.time()
                exit_ts = row[9] if row[9] else time.time()
                exit_dt = datetime.fromtimestamp(exit_ts, tz=timezone.utc)
                entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
                closed_trades_list.append({
                    'trade_id': row[0],
                    'symbol': row[1],
                    'side': 'BUY',  # Default, would need to be in DB schema for accuracy
                    'entry_price': float(row[2]) if row[2] else 0,
                    'exit_price': float(row[3]) if row[3] else 0,
                    'pnl_pct': float(row[4]) if row[4] else 0,
                    'pnl_usd': float(row[5]) if row[5] else 0,
                    'exit_reason': row[6],
                    'hold_s': int(row[7]) if row[7] else 0,
                    'entry_timestamp': entry_dt.isoformat().replace('+00:00', 'Z'),
                    'exit_timestamp': exit_dt.isoformat().replace('+00:00', 'Z')
                })
            conn2.close()
        except Exception as e:
            import sys
            print(f"[DASHBOARD] Error loading trades: {e}", file=sys.stderr, flush=True)
        finally:
            try:
                conn = sqlite3.connect("local_learning_storage/learning_database.sqlite", timeout=2)
                conn.close()
            except:
                pass

        # Load lifetime metrics from learning state
        lifetime_metrics = load_lifetime_metrics()

        return jsonify({
            "closed_trades": closed_trades,
            "lifetime_closed_trades": lifetime_metrics["lifetime_n"],
            "open_positions": open_positions,
            "open_positions_list": open_positions_list,
            "closed_trades_list": closed_trades_list,
            "profit_factor": float(profit_factor),
            "win_rate_pct": float(win_rate),
            "net_pnl": float(net_pnl),
            "exit_distribution": exits,
            "timestamp": iso_timestamp,
            "last_update": iso_timestamp,
            "lifetime_metrics": {
                "lifetime_n": lifetime_metrics["lifetime_n"],
                "lifetime_pf": lifetime_metrics["lifetime_pf"],
                "lifetime_expectancy": lifetime_metrics["lifetime_expectancy"]
            }
        })
    except Exception as e:
        from datetime import datetime, timezone
        iso_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        return jsonify({"error": str(e), "timestamp": iso_timestamp}), 500

@app.route('/api/dashboard/metrics/enhanced')
def enhanced_metrics():
    """Enhanced metrics with cost-floor analysis and profitability checks"""
    try:
        import os
        import json as json_module
        from datetime import datetime, timezone

        iso_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        # Cost floor constants (from override.conf)
        COST_FLOOR_BPS = 18  # 15bps fee + 3bps slippage

        # Get current TP/SL zones from environment
        try:
            tp_bps = int(os.getenv('PAPER_TP_ZONE_BPS', '35'))
            sl_bps = int(os.getenv('PAPER_SL_ZONE_BPS', '40'))
        except:
            tp_bps = 35
            sl_bps = 40

        # Safety checks
        tp_above_cost_floor = tp_bps > COST_FLOOR_BPS
        tp_margin_bps = tp_bps - COST_FLOOR_BPS
        profitability_status = "SAFE" if tp_margin_bps >= 10 else "CAUTION" if tp_margin_bps >= 0 else "CRITICAL"

        # Try to get recent trades from DB
        closed_trades = 0
        win_rate = 0.0
        profit_factor = 0.0
        net_pnl = 0.0
        tp_exits = 0
        sl_exits = 0
        timeout_exits = 0

        try:
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
            if os.path.exists(db_path):
                conn = sqlite3.connect(db_path, timeout=2)
                cursor = conn.cursor()

                # Get last 100 trades
                cursor.execute("SELECT outcome, exit_reason, net_pnl_pct FROM trades ORDER BY closed_ts DESC LIMIT 100")
                rows = cursor.fetchall()

                closed_trades = len(rows)
                wins = 0
                losses = 0
                total_pnl = 0.0

                for outcome, reason, pnl_pct in rows:
                    total_pnl += float(pnl_pct or 0)
                    if outcome == 'WIN':
                        wins += 1
                    else:
                        losses += 1

                    if reason == 'TP':
                        tp_exits += 1
                    elif reason == 'SL':
                        sl_exits += 1
                    elif reason == 'TIMEOUT':
                        timeout_exits += 1

                win_rate = (wins / closed_trades * 100) if closed_trades > 0 else 0.0
                profit_factor = abs(total_pnl / (total_pnl if total_pnl < 0 else 0.001)) if total_pnl < 0 else (1.0 if total_pnl >= 0 and total_pnl > 0 else 0.0)
                net_pnl = total_pnl

                conn.close()
        except:
            pass

        return jsonify({
            "metrics": {
                "win_rate_pct": float(win_rate),
                "profit_factor": float(profit_factor),
                "net_pnl": float(net_pnl),
                "closed_trades": int(closed_trades),
                "exit_distribution": {
                    "tp": int(tp_exits),
                    "sl": int(sl_exits),
                    "timeout": int(timeout_exits)
                }
            },
            "profitability": {
                "cost_floor_bps": int(COST_FLOOR_BPS),
                "tp_zone_bps": int(tp_bps),
                "sl_zone_bps": int(sl_bps),
                "tp_above_cost_floor": bool(tp_above_cost_floor),
                "tp_margin_bps": int(tp_margin_bps),
                "profitability_status": str(profitability_status),
                "health_check": "🟢 TP viable" if profitability_status == "SAFE" else "🟡 CAUTION" if profitability_status == "CAUTION" else "🔴 CRITICAL"
            },
            "timestamp": iso_timestamp
        })
    except Exception as e:
        from datetime import datetime, timezone
        iso_timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        return jsonify({"error": str(e), "timestamp": iso_timestamp}), 500

@app.route('/api/trades/recent')
def recent_trades():
    """Return last 30 closed trades with ISO timestamps"""
    try:
        from datetime import datetime, timezone

        trades = []

        # FIRST: Try to get trades from real-time cache (most reliable)
        try:
            from src.services.recent_trades_cache import get_recent_trades
            trades = get_recent_trades(30)
            if trades:
                return jsonify(trades)
        except:
            pass

        # FALLBACK: Fetch recent journalctl logs (last 2 hours) and parse [PAPER_EXIT] records
        import subprocess
        try:
            result = subprocess.run(
                ['journalctl', '-u', 'cryptomaster.service', '--since', '2 hours ago', '--no-pager', '-q'],
                capture_output=True,
                text=True,
                timeout=2
            )
            logs = result.stdout

            # Parse [PAPER_EXIT] lines
            for line in logs.split('\n'):
                if '[PAPER_EXIT]' not in line:
                    continue

                try:
                    # Extract fields using regex
                    trade_id_match = re.search(r'trade_id=(\S+)', line)
                    symbol_match = re.search(r'symbol=(\S+)', line)
                    side_match = re.search(r'side=(\S+)', line)
                    entry_match = re.search(r'entry=([\d.]+)', line)
                    exit_match = re.search(r'exit=([\d.]+)', line)
                    pnl_pct_match = re.search(r'net_pnl_pct=([\d.\-eE+]+)', line)
                    reason_match = re.search(r'reason=(\S+)', line)
                    hold_match = re.search(r'hold_s=([\d.]+)', line)
                    timestamp_match = re.search(r'timestamp=(\S+)', line)

                    if all([trade_id_match, symbol_match, entry_match, exit_match, pnl_pct_match]):
                        entry_val = float(entry_match.group(1))
                        exit_val = float(exit_match.group(1))
                        pnl_pct_val = float(pnl_pct_match.group(1))
                        pnl_usd_val = entry_val * pnl_pct_val / 100.0
                        hold_s_val = float(hold_match.group(1)) if hold_match else 600

                        # Use provided timestamp or estimate from now - hold_s
                        if timestamp_match:
                            try:
                                exit_ts = int(datetime.fromisoformat(timestamp_match.group(1).replace('Z', '+00:00')).timestamp())
                            except:
                                exit_ts = int(time.time()) - int(hold_s_val)
                        else:
                            exit_ts = int(time.time()) - int(hold_s_val)

                        exit_dt = datetime.fromtimestamp(exit_ts, tz=timezone.utc)
                        exit_iso = exit_dt.isoformat().replace('+00:00', 'Z')

                        entry_ts = exit_ts - int(hold_s_val)
                        entry_dt = datetime.fromtimestamp(entry_ts, tz=timezone.utc)
                        entry_iso = entry_dt.isoformat().replace('+00:00', 'Z')

                        trades.append({
                            'trade_id': trade_id_match.group(1),
                            'symbol': symbol_match.group(1),
                            'side': side_match.group(1) if side_match else 'BUY',
                            'entry_price': entry_val,
                            'exit_price': exit_val,
                            'pnl_pct': pnl_pct_val,
                            'pnl_usd': pnl_usd_val,
                            'exit_reason': reason_match.group(1) if reason_match else 'UNKNOWN',
                            'entry_ts': entry_iso,
                            'exit_ts': exit_iso,
                            'hold_s': int(hold_s_val)
                        })
                except:
                    pass

            # Sort by exit time (newest first) and limit to 30
            trades = sorted(trades, key=lambda t: t['exit_ts'], reverse=True)[:30]

            if trades:
                return jsonify(trades)
        except Exception as e:
            print(f"[DASHBOARD] Error parsing journalctl logs: {e}")

        # Fallback to database if journalctl parsing fails
        # BUT ONLY RETURN TODAY'S TRADES (last 24 hours) to avoid stale data
        try:
            from datetime import datetime, timezone, timedelta
            db_path = 'local_learning_storage/learning_database.sqlite'
            conn = sqlite3.connect(db_path, timeout=2)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Only get trades from last 24 hours
            cutoff_ts = time.time() - (24 * 3600)
            cursor.execute("""
                SELECT trade_id, symbol, side, entry_price, exit_price,
                       entry_ts, exit_ts, pnl_pct, pnl_usd, exit_reason, hold_s
                FROM trades
                WHERE exit_ts > ?
                ORDER BY exit_ts DESC
                LIMIT 30
            """, (cutoff_ts,))

            for row in cursor.fetchall():
                entry_ts = row['entry_ts']
                exit_ts = row['exit_ts']

                if entry_ts and entry_ts > 0 and entry_ts < 100000000000:
                    entry_ts_iso = datetime.fromtimestamp(entry_ts, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                else:
                    entry_ts_iso = str(entry_ts) if entry_ts else None

                if exit_ts and exit_ts > 0 and exit_ts < 100000000000:
                    exit_ts_iso = datetime.fromtimestamp(exit_ts, tz=timezone.utc).isoformat().replace('+00:00', 'Z')
                else:
                    exit_ts_iso = str(exit_ts) if exit_ts else None

                trades.append({
                    'trade_id': row['trade_id'],
                    'symbol': row['symbol'],
                    'side': row['side'] or '—',
                    'entry_price': float(row['entry_price']) if row['entry_price'] else 0,
                    'exit_price': float(row['exit_price']) if row['exit_price'] else 0,
                    'pnl_pct': float(row['pnl_pct']) if row['pnl_pct'] else 0,
                    'pnl_usd': float(row['pnl_usd']) if row['pnl_usd'] else 0,
                    'exit_reason': row['exit_reason'] or '—',
                    'entry_ts': entry_ts_iso,
                    'exit_ts': exit_ts_iso,
                    'hold_s': int(row['hold_s']) if row['hold_s'] else 0
                })

            conn.close()

            # If we have fresh trades from today, return them
            if trades:
                return jsonify(trades)
        except Exception as e:
            print(f"[DASHBOARD] Database fallback error: {e}")

        # Final fallback: return empty list rather than stale data
        # Better to show no trades than 6-day-old trades
        print(f"[DASHBOARD] No fresh trades found in last 24h - returning empty list")
        return jsonify([])

    except Exception as e:
        print(f"[DASHBOARD] Error in recent_trades: {e}")
        return jsonify([])

@app.route('/v2/', methods=['GET'])
@app.route('/v2/<path:path>', methods=['GET'])
def react_dashboard(path=''):
    """Serve React SPA at /v2/"""
    import os
    print(f"[REACT_DASHBOARD] path='{path}'")
    # Try both relative (from project root when run locally) and absolute (Hetzner deployment)
    for dist_base in ['/opt/cryptomaster/dashboard_modern/dist', os.path.join(os.getcwd(), 'dashboard_modern', 'dist')]:
        if os.path.isdir(dist_base):
            dist_dir = dist_base
            print(f"[REACT_DASHBOARD] Using dist_dir={dist_dir}")
            break
    else:
        print(f"[REACT_DASHBOARD] Dashboard not found in any location")
        return 'Dashboard not found', 404

    if path and not path.startswith('assets/'):
        path = ''  # Client-side routing: serve index.html for all routes
    index_file = os.path.join(dist_dir, path or 'index.html')
    try:
        with open(index_file, 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}
    except FileNotFoundError:
        with open(os.path.join(dist_dir, 'index.html'), 'r') as f:
            return f.read(), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/v2/assets/<path:filename>', methods=['GET'])
def react_assets(filename):
    """Serve React assets (JS/CSS/fonts)"""
    import os
    # Try both relative (from project root when run locally) and absolute (Hetzner deployment)
    for dist_base in ['/opt/cryptomaster/dashboard_modern/dist/assets', os.path.join(os.getcwd(), 'dashboard_modern', 'dist', 'assets')]:
        if os.path.isdir(dist_base):
            dist_dir = dist_base
            break
    else:
        return '', 404

    try:
        with open(os.path.join(dist_dir, filename), 'rb') as f:
            content = f.read()
        if filename.endswith('.js'):
            return content, 200, {'Content-Type': 'application/javascript; charset=utf-8'}
        elif filename.endswith('.css'):
            return content, 200, {'Content-Type': 'text/css; charset=utf-8'}
        else:
            return content, 200, {'Content-Type': 'application/octet-stream'}
    except FileNotFoundError:
        return '', 404


@app.route('/api/dashboard/readiness')
def readiness_check():
    """Get trading readiness status."""
    try:
        from src.services.trading_readiness_checker import check_readiness
        from src.services.readiness_monitor import get_current_metrics

        # Get current metrics
        metrics = get_current_metrics()
        if not metrics:
            return jsonify({
                "error": "No metrics available yet",
                "readiness_score": 0,
                "is_ready_for_trading": False,
                "blocker_reasons": ["Insufficient trading history"]
            }), 200

        # Run readiness check
        result = check_readiness(metrics)

        return jsonify(result), 200
    except Exception as e:
        log.error(f"[READINESS_CHECK_ERROR] {e}", exc_info=True)
        return jsonify({"error": str(e), "readiness_score": 0, "is_ready_for_trading": False}), 500


@app.route('/api/dashboard/readiness/status')
def readiness_status():
    """Get cached readiness status (lightweight)."""
    try:
        from src.services.trading_readiness_checker import get_readiness_status
        status = get_readiness_status()
        return jsonify(status), 200
    except Exception as e:
        log.error(f"[READINESS_STATUS_ERROR] {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/dashboard/learning-state')
def learning_state():
    """Expose learning system auto-adjustment process and regime TP strategy."""
    try:
        import os
        from pathlib import Path

        learning_state_file = Path("server_local_backups/paper_adaptive_learning_state.json")

        if not learning_state_file.exists():
            return jsonify({
                "learning_enabled": False,
                "status": "no_learning_state_file",
                "regime_tp_strategy": {},
                "lifetime_closes": 0,
                "message": "Learning system not yet initialized"
            }), 200

        with open(learning_state_file, 'r') as f:
            state = json.load(f)

        regime_tp_strategy = state.get("regime_tp_strategy", {})
        rolling20 = state.get("rolling20", [])
        rolling50 = state.get("rolling50", [])

        non_timeout_count_50 = sum(
            1 for trade in rolling50
            if len(trade) >= 2 and (trade[1] != "FLAT" or trade[0] != 0)
        )
        entry_success_rate_50 = non_timeout_count_50 / len(rolling50) if rolling50 else 0.0

        recent_trades_50 = []
        for i, trade in enumerate(reversed(rolling50[-10:])):
            if len(trade) >= 4:
                recent_trades_50.append({
                    "index": len(rolling50) - i - 1,
                    "pnl_pct": float(trade[0]),
                    "outcome": trade[1],
                    "symbol_regime": trade[2] if len(trade) > 2 else "UNKNOWN",
                    "timestamp": trade[3] if len(trade) > 3 else None
                })

        return jsonify({
            "timestamp": int(time.time()),
            "learning_enabled": state.get("regime_tp_learning_enabled", False),
            "learning_blend": float(state.get("regime_tp_learning_blend", 0.0)),
            "lifecycle": state.get("lifecycle", "UNKNOWN"),
            "lifetime_closes": int(state.get("lifetime_n", 0)),
            "lifetime_pf": float(state.get("lifetime_pf", 1.0)),
            "lifetime_expectancy": float(state.get("lifetime_expectancy", 0.0)),
            "entry_quality_gate": {
                "passing": entry_success_rate_50 > 0.75,
                "non_timeout_pct": float(entry_success_rate_50 * 100)
            },
            "regime_tp_strategy": regime_tp_strategy,
            "rolling_windows": {
                "rolling20_size": len(rolling20),
                "rolling50_size": len(rolling50),
                "rolling50_recent_10_trades": recent_trades_50
            },
            "status": "active"
        }), 200

    except Exception as e:
        log.error(f"[LEARNING_STATE_ERROR] {e}", exc_info=True)
        return jsonify({"error": str(e), "status": "error"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)  # Use 5001 to avoid conflict with cryptomaster's internal dashboard
