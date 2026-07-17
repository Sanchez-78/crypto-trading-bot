#!/usr/bin/env python3
"""
CryptoMaster Modern Web Dashboard (V10.25)
Complete responsive dashboard with live metrics and charts
"""

from flask import Flask, render_template_string, jsonify
import sqlite3
import json
import time
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


def _android_contract_fields(state=None):
    """Android contract fields (dashboard_audit 2026-07-14, M1/M3/M4).

    closed_today counts durable rolling-window entries closed since UTC
    start-of-day (survives bot restarts). learning_status / recommendation use
    the Czech labels required by the android-dashboard-contract skill.
    """
    from datetime import datetime, timezone
    if state is None:
        state = _load_learning_state()
    rolling = state.get('rolling100') or state.get('rolling50') or []
    midnight = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    closed_today = sum(
        1 for e in rolling
        if isinstance(e, (list, tuple))
        and any(isinstance(x, (int, float)) and x > 1e9 and x >= midnight for x in e)
    )
    lifetime_n = int(state.get('lifetime_n', 0) or 0)
    if state.get('regime_tp_learning_enabled'):
        learning_status = 'UČENÍ'
    elif lifetime_n > 0:
        learning_status = 'PŘIPRAVEN'
    else:
        learning_status = 'VYPNUTO'
    return {
        'closed_today': closed_today,
        'learning_status': learning_status,
        # No live signal feed in this process; ČEKAT is the safe honest default.
        'recommendation': 'ČEKAT',
    }


def _closed_trades_from_rolling(rolling, limit=30):
    """Build a closed-trades list from the durable learning rolling window.

    Rolling entries look like:
        [pnl_pct, "WIN"/"LOSS"/"FLAT", "SYMBOL:REGIME:SIDE", ts, source, bucket]
    This window survives bot restarts (unlike cache.sqlite / journald), so it is
    the fallback used when the ephemeral session sink is empty. Exit-reason is NOT
    stored here, so we honestly surface the WIN/LOSS/FLAT outcome as the reason
    rather than inventing a TP/SL split.
    """
    from datetime import datetime, timezone
    out = []
    try:
        for e in reversed(list(rolling)[-limit:]):
            if not isinstance(e, (list, tuple)) or len(e) < 3:
                continue
            pnl = e[0] if isinstance(e[0], (int, float)) else 0.0
            outcome = ''
            for x in e:
                if isinstance(x, str) and x.upper() in ('WIN', 'LOSS', 'FLAT'):
                    outcome = x.upper()
                    break
            if not outcome:
                outcome = 'WIN' if pnl > 0 else 'LOSS'
            seg = next((x for x in e if isinstance(x, str) and ':' in x), '::')
            parts = seg.split(':')
            ts = next((x for x in e if isinstance(x, (int, float)) and x > 1e9), 0)
            exit_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') if ts else ''
            out.append({
                'trade_id': '', 'symbol': parts[0] if parts and parts[0] else '?',
                'side': parts[2] if len(parts) > 2 else 'BUY',
                'entry_price': 0, 'exit_price': 0,
                'pnl_pct': round(float(pnl), 4), 'pnl_usd': 0.0,
                'reason': outcome, 'exit_reason': outcome,
                'hold_s': 0, 'regime': parts[1] if len(parts) > 1 else 'UNKNOWN',
                'win': 1 if outcome == 'WIN' else 0,
                'exit_time': int(ts),
                'entry_ts': '', 'entry_timestamp': '',
                'exit_ts': exit_iso, 'exit_timestamp': exit_iso,
            })
    except Exception:
        pass
    return out


def _rolling_window_metrics(cache_path, limit=100):
    """Headline WR / PF / net from the newest N closed trades in cache.sqlite.

    This is the AUTHORITATIVE source for the dashboard headline (bug 2026-07-15):
    it reflects the bot's RECENT form (last <=100 rows of closed_trades, ordered by
    exit_ts DESC) — NOT the lifetime aggregate (dominated by the pre-fix losing era,
    16k+ trades) and NOT the durable learning rolling window (which can disagree with
    the cache close-sink). Before this, the headline profit_factor was sourced from
    lifetime_pf and win_rate from roll_wins/roll_n, so the app showed a red 41%/0.38
    while the actual recent window was ~62% WR / positive.

    Win rule: pnl_usd>0, or pnl_pct>0 when pnl_usd is NULL/0.
    Profit factor: gross_win/gross_loss from pnl_usd; if every pnl_usd is 0/NULL,
    fall back to pnl_pct as the P&L basis.

    Returns {'n','wins','win_rate_pct','profit_factor','net_pnl'} or None on ANY
    error / empty cache. Uses a read-only sqlite connection (mode=ro) with a short
    timeout and NEVER raises, so callers can fall back and preserve never-500/blank.
    """
    try:
        if not cache_path or not os.path.exists(cache_path):
            return None
        conn = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True, timeout=2)
        try:
            rows = conn.execute(
                "SELECT pnl_usd, pnl_pct FROM closed_trades "
                "ORDER BY exit_ts DESC LIMIT ?", (int(limit),)
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return None

    if not rows:
        return None

    def _num(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    usd = [_num(r[0]) for r in rows]
    pct = [_num(r[1]) for r in rows]
    # Choose one P&L basis for gross/net so units stay consistent: prefer USD,
    # fall back to pct only when no row carries a non-zero pnl_usd.
    basis_is_usd = any(v is not None and v != 0.0 for v in usd)

    n = len(rows)
    wins = 0
    gross_win = 0.0
    gross_loss = 0.0
    net = 0.0
    for u, p in zip(usd, pct):
        # Per-row win: USD sign when present, else pct sign (task spec).
        if u is not None and u != 0.0:
            is_win = u > 0
        else:
            is_win = p is not None and p > 0
        if is_win:
            wins += 1
        val = (u if u is not None else 0.0) if basis_is_usd else (p if p is not None else 0.0)
        if val > 0:
            gross_win += val
        elif val < 0:
            gross_loss += -val
        net += val

    if gross_loss > 0:
        pf = gross_win / gross_loss
    elif gross_win > 0:
        pf = 99.0  # wins with no losing P&L in the window; capped, JSON-safe
    else:
        pf = 0.0

    return {
        'n': n,
        'wins': wins,
        'win_rate_pct': round(wins / n * 100.0, 2) if n else 0.0,
        'profit_factor': round(pf, 3),
        'net_pnl': round(net, 6),
    }


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
                # C8 (dashboard_audit 2026-07-14): read the stored side; legacy
                # cache.sqlite files predate the side column, so fall back to NULL.
                _q = ("SELECT trade_id, symbol, entry_price, exit_price, pnl_usd, pnl_pct, "
                      "exit_reason, entry_ts, exit_ts, regime, win, {side} "
                      "FROM closed_trades ORDER BY exit_ts DESC LIMIT 30")
                try:
                    rows = list(cur.execute(_q.format(side="side")))
                except sqlite3.OperationalError:  # legacy DB without side column
                    rows = list(cur.execute(_q.format(side="NULL")))
                for r in rows:
                    tid, sym, ep, xp, pu, pp, reason, ets, xts, regime, win, side = r
                    ep = float(ep or 0)
                    xp = float(xp or 0)
                    if pp is None:
                        # Legacy NULL pnl_pct: recompute long-formula, then correct sign
                        pp = ((xp / ep - 1.0) * 100.0) if ep else 0.0
                        if (side or '').upper() in ('SELL', 'SHORT'):
                            pp = -pp  # short: direction-corrected
                        elif side is None and pu is not None and pp * float(pu) < 0:
                            pp = -pp  # legacy row: trust side-aware pnl_usd sign
                    ets = float(ets or 0)
                    xts = float(xts or 0)
                    closed_trades_list.append({
                        'trade_id': tid, 'symbol': sym, 'side': (side or 'BUY'),
                        'entry_price': ep, 'exit_price': xp,
                        'pnl_pct': float(pp or 0), 'pnl_usd': float(pu or 0),
                        'reason': reason, 'exit_reason': reason,
                        'hold_s': int(xts - ets) if (xts and ets) else 0,
                        'regime': regime or 'UNKNOWN', 'win': int(win or 0),
                        'exit_time': int(xts) if xts else 0,
                        'entry_timestamp': datetime.fromtimestamp(ets, tz=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') if ets else '',
                        'exit_timestamp': datetime.fromtimestamp(xts, tz=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z') if xts else '',
                    })
                conn.close()
            except Exception:
                pass

        # --- Fallback list from durable rolling window (cache empty post-restart) ---
        if not closed_trades_list and rolling:
            closed_trades_list = _closed_trades_from_rolling(rolling, 30)

        # --- Honest exit_distribution fallback when the session sink is empty ---
        # cache.sqlite (ephemeral) is the only source of TP/SL/timeout reasons; it
        # is wiped on every bot restart. The durable rolling window carries only
        # WIN/LOSS/FLAT outcomes, so surface those counts rather than leaving the
        # chart all-zeros. We do NOT fabricate a TP/SL split we don't have.
        if session_n == 0 and rolling:
            exits['win'] = sum(1 for e in rolling if _outcome(e) == 'WIN')
            exits['loss'] = sum(1 for e in rolling if _outcome(e) == 'LOSS')
            exits['flat'] = sum(1 for e in rolling if _outcome(e) == 'FLAT')
            exits['basis'] = 'outcome'  # marks reasons unavailable, only win/loss known

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
                # Android contract (M7/M8): side-aware live pnl_pct + age_s/hold_s keys
                _ep = float(p.get('entry_price', 0))
                _cp = float(p.get('last_price', p.get('entry_price', 0)))
                _side = p.get('side', 'BUY')
                _pnl = ((_cp / _ep - 1.0) * 100.0) if _ep else 0.0
                if str(_side).upper() in ('SELL', 'SHORT'):
                    _pnl = -_pnl
                open_positions_list.append({
                    'trade_id': str(pid)[:12], 'symbol': p.get('symbol', 'N/A'),
                    'side': _side,
                    'entry_price': _ep,
                    'current_price': _cp,
                    'tp': float(p.get('tp', 0)), 'sl': float(p.get('sl', 0)),
                    'entry_ts': ets, 'age_seconds': int(now_ts - ets),
                    'age_s': int(now_ts - ets),
                    'current_hold_s': int(now_ts - ets),
                    'hold_s': int(now_ts - ets),
                    'regime': p.get('regime', 'N/A'),
                    'size_usd': float(p.get('size_usd', 0.5)),
                    'pnl_pct': round(_pnl, 4), 'status': 'OPEN',
                    'entry_timestamp': datetime.fromtimestamp(ets, tz=timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                })
        except Exception:
            pass

        # --- Headline from the RECENT window (bug 2026-07-15) ---------------
        # The headline WR/PF must reflect current bot form, sourced from ONE
        # authoritative place: the newest <=100 rows of cache.sqlite:closed_trades.
        # Previously PF came from lifetime_pf (16k+ trades, pre-fix losing era) and
        # WR from the durable rolling window (roll_wins/roll_n), which disagreed with
        # the recent closed trades. Fall back to the old learning-state values ONLY
        # when the cache is empty/unavailable, so never-500 / never-blank is kept.
        rolling_hdr = _rolling_window_metrics(cache_path, 100)
        if rolling_hdr:
            headline_pf = round(float(rolling_hdr['profit_factor']), 3)
            headline_wr = round(float(rolling_hdr['win_rate_pct']), 2)
            headline_window = int(rolling_hdr['n'])
            net_pnl_window = round(float(rolling_hdr['net_pnl']), 6)
        else:
            headline_pf = round(float(lifetime_metrics.get('lifetime_pf', 0.0) or 0.0), 3)
            headline_wr = round(win_rate, 2)
            headline_window = roll_n
            net_pnl_window = round(session_net, 6)

        iso = datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
        return {
            'closed_trades': lifetime_n,
            'total_trades': lifetime_n,  # Android contract alias (M2)
            **_android_contract_fields(state),
            'session_closed_trades': session_n,
            'lifetime_closed_trades': lifetime_n,
            'open_positions': len(open_positions_list),
            'open_positions_list': open_positions_list,
            'closed_trades_list': closed_trades_list,
            'profit_factor': headline_pf,
            'win_rate_pct': headline_wr,
            'win_rate_window': headline_window,
            'net_pnl': round(session_net, 6),
            'net_pnl_window': net_pnl_window,
            'exit_distribution': exits,
            'timestamp': iso,
            'last_update': iso,
            'last_update_utc': iso,  # Android contract (M5), ms-precision ISO8601 Z
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
            // Prefer the TP/SL/timeout reason split (from the live session sink).
            // After a bot restart that sink is empty; fall back to the durable
            // WIN/LOSS/FLAT outcome counts so the chart is honest, not blank.
            const reasonTotal = (exits.timeout || 0) + (exits.tp || 0) + (exits.sl || 0)
                + (exits.scratch || 0) + (exits.stagnation || 0);
            let exitLabels, exitData, exitColors;
            if (reasonTotal > 0) {
                exitLabels = ['Timeout', 'TP', 'SL', 'Scratch', 'Stagnation'];
                exitData = [exits.timeout || 0, exits.tp || 0, exits.sl || 0, exits.scratch || 0, exits.stagnation || 0];
                exitColors = ['#1e90ff', '#00ff00', '#ff4444', '#ffaa00', '#ff00ff'];
            } else {
                exitLabels = ['Wins', 'Losses', 'Flat'];
                exitData = [exits.win || 0, exits.loss || 0, exits.flat || 0];
                exitColors = ['#00ff00', '#ff4444', '#888888'];
            }
            exitChart = new Chart(exitCtx, {
                type: 'doughnut',
                data: {
                    labels: exitLabels,
                    datasets: [{
                        data: exitData,
                        backgroundColor: exitColors,
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
    """Primary Android metrics via the single dashboard read model (audit PR4)."""
    from src.services.dashboard_read_model import get_metrics
    return jsonify(get_metrics())

@app.route('/api/dashboard/metrics/enhanced')
def enhanced_metrics():
    """Enhanced metrics: identical headline to /metrics plus diagnostics (audit PR4)."""
    from src.services.dashboard_read_model import get_enhanced_metrics
    return jsonify(get_enhanced_metrics())

@app.route('/api/trades/recent')
def recent_trades():
    """Last 30 closed trades from the single read model - same cache as the headline (audit PR4)."""
    from src.services.dashboard_read_model import get_recent_trades
    return jsonify(get_recent_trades(30))

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
        # Never-500 (dashboard_audit 2026-07-14, Fix 5): degrade with HTTP 200.
        return jsonify({"error": str(e), "readiness_score": 0, "is_ready_for_trading": False,
                        "blocker_reasons": ["service_degraded"]}), 200


@app.route('/api/dashboard/readiness/status')
def readiness_status():
    """Get cached readiness status (lightweight)."""
    try:
        from src.services.trading_readiness_checker import get_readiness_status
        status = get_readiness_status()
        return jsonify(status), 200
    except Exception as e:
        log.error(f"[READINESS_STATUS_ERROR] {e}", exc_info=True)
        # Never-500 (dashboard_audit 2026-07-14, Fix 5): degrade with HTTP 200.
        return jsonify({"error": str(e), "status": "degraded"}), 200


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
        # Never-500 (dashboard_audit 2026-07-14, Fix 5): degrade with HTTP 200.
        return jsonify({"error": str(e), "status": "error", "learning_enabled": False,
                        "regime_tp_strategy": {}, "lifetime_closes": 0}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)  # Use 5001 to avoid conflict with cryptomaster's internal dashboard
