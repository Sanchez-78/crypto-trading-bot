"""
Flask endpoint for dashboard metrics API.
Serves all trading metrics for Android app integration.
"""

from flask import Blueprint, jsonify
from datetime import datetime
import sqlite3
import json
import logging
import os

log = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/api')


def _get_db_path():
    """Get path to learning database."""
    return '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'


def _query_db(query: str, params=None):
    """Execute query against learning database."""
    try:
        db_path = _get_db_path()
        if not os.path.exists(db_path):
            log.warning(f"[DASHBOARD_API] DB not found: {db_path}")
            return None

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        result = cursor.fetchall()
        conn.close()
        return result
    except Exception as e:
        log.error(f"[DASHBOARD_API] Query error: {e}")
        return None


@dashboard_bp.route('/dashboard/metrics', methods=['GET'])
def get_dashboard_metrics():
    """
    Aggregate all dashboard metrics from local learning storage database.

    Returns: {
        win_rate_pct: float,        # 0-100
        profit_factor: float,       # 1.0 = breakeven
        net_pnl: float,
        closed_trades: int,
        exit_distribution: {...},
        readiness_by_symbol: [...],
        timestamp: int (Unix),
        last_update: str
    }
    """
    try:
        # Get success metrics
        result = _query_db('''
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses,
                AVG(pnl_pct) as expectancy,
                SUM(pnl_usd) as net_pnl
            FROM trades
        ''')

        metrics_row = result[0] if result else None
        if not metrics_row:
            return jsonify({
                'error': 'No trades recorded yet',
                'timestamp': int(datetime.now().timestamp())
            }), 404

        total = metrics_row['total']
        wins = metrics_row['wins'] or 0
        losses = metrics_row['losses'] or 0
        expectancy = metrics_row['expectancy'] or 0.0
        net_pnl = metrics_row['net_pnl'] or 0.0

        # Calculate PF
        profit_factor = (wins / (losses + 0.0001)) if losses > 0 else (1.0 if wins > 0 else 0.0)
        win_rate_pct = (wins / total * 100) if total > 0 else 0.0

        # Get exit distribution
        exit_result = _query_db('''
            SELECT exit_reason, COUNT(*) as cnt
            FROM trades
            GROUP BY exit_reason
        ''')

        exits = {
            'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0
        }
        if exit_result:
            for row in exit_result:
                reason = (row['exit_reason'] or 'unknown').lower()
                if reason == 'tp':
                    exits['tp'] = row['cnt']
                elif reason == 'sl':
                    exits['sl'] = row['cnt']
                elif reason in ['scratch', 'scratch_exit']:
                    exits['scratch'] = row['cnt']
                elif reason in ['stagnation', 'stagnation_exit']:
                    exits['stagnation'] = row['cnt']
                elif reason in ['timeout', 'stale_timeout']:
                    exits['timeout'] = row['cnt']

        # Get readiness by symbol (skip if table doesn't exist)
        readiness_by_symbol = []
        try:
            readiness_result = _query_db('''
                SELECT symbol, readiness_status, readiness_pct, closed_trades,
                       win_rate, profit_factor, expectancy
                FROM readiness_status
                ORDER BY readiness_pct DESC
            ''')

            if readiness_result:
                for row in readiness_result:
                    readiness_by_symbol.append({
                        'symbol': row['symbol'],
                        'closed_trades': row['closed_trades'],
                        'win_rate': row['win_rate'],
                        'profit_factor': row['profit_factor'],
                        'expectancy': row['expectancy'],
                        'min_trades_ok': row['closed_trades'] >= 50,
                        'wr_ok': row['win_rate'] >= 0.65,
                        'pf_ok': row['profit_factor'] >= 1.05,
                        'exp_ok': row['expectancy'] > 0,
                        'readiness_status': row['readiness_status'],
                        'readiness_pct': row['readiness_pct'],
                        'last_update': int(datetime.now().timestamp())
                    })
        except Exception as e:
            log.info(f"[DASHBOARD_METRICS] readiness_status table not available: {e}")

        # Get open positions count
        open_positions = 0
        try:
            pos_file = '/opt/cryptomaster/data/paper_open_positions.json'
            if os.path.exists(pos_file):
                with open(pos_file) as f:
                    positions = json.load(f)
                    open_positions = len(positions)
        except Exception as e:
            log.warning(f"[DASHBOARD_METRICS] Could not read positions: {e}")

        # Build response
        response = {
            'win_rate_pct': round(win_rate_pct, 1),
            'profit_factor': round(profit_factor, 2),
            'net_pnl': round(net_pnl, 8),
            'closed_trades': total,
            'open_positions': open_positions,
            'exit_distribution': exits,
            'readiness_by_symbol': readiness_by_symbol,
            'timestamp': int(datetime.now().timestamp()),
            'last_update': datetime.now().isoformat()
        }

        log.info(
            f"[DASHBOARD_METRICS_API] pf={profit_factor:.2f}x "
            f"wr={win_rate_pct:.1f}% net_pnl={net_pnl:.8f} "
            f"closed={total} symbols={len(readiness_by_symbol)}"
        )

        return jsonify(response), 200

    except Exception as e:
        log.error(f"[DASHBOARD_METRICS_API] Error: {e}")
        return jsonify({'error': str(e)}), 500


@dashboard_bp.route('/dashboard/readiness', methods=['GET'])
def get_readiness_status():
    """Get readiness status for all symbols."""
    try:
        result = _query_db('''
            SELECT * FROM readiness_status
            ORDER BY readiness_pct DESC
        ''')

        if not result:
            return jsonify([]), 200

        readiness_list = []
        for row in result:
            readiness_list.append({
                'symbol': row['symbol'],
                'closed_trades': row['closed_trades'],
                'win_rate': row['win_rate'],
                'profit_factor': row['profit_factor'],
                'expectancy': row['expectancy'],
                'min_trades_ok': row['closed_trades'] >= 50,
                'wr_ok': row['win_rate'] >= 0.65,
                'pf_ok': row['profit_factor'] >= 1.05,
                'exp_ok': row['expectancy'] > 0,
                'readiness_status': row['readiness_status'],
                'readiness_pct': row['readiness_pct'],
                'last_update': int(datetime.now().timestamp())
            })

        return jsonify(readiness_list), 200

    except Exception as e:
        log.error(f"[DASHBOARD_READINESS_API] Error: {e}")
        return jsonify({'error': str(e)}), 500


@dashboard_bp.route('/dashboard/readiness/<symbol>', methods=['GET'])
def get_symbol_readiness(symbol):
    """Get readiness status for specific symbol."""
    try:
        result = _query_db(
            'SELECT * FROM readiness_status WHERE symbol = ?',
            (symbol.upper(),)
        )

        if not result:
            return jsonify({'error': f'Symbol {symbol} not found'}), 404

        row = result[0]
        response = {
            'symbol': row['symbol'],
            'closed_trades': row['closed_trades'],
            'win_rate': row['win_rate'],
            'profit_factor': row['profit_factor'],
            'expectancy': row['expectancy'],
            'min_trades_ok': row['closed_trades'] >= 50,
            'wr_ok': row['win_rate'] >= 0.65,
            'pf_ok': row['profit_factor'] >= 1.05,
            'exp_ok': row['expectancy'] > 0,
            'readiness_status': row['readiness_status'],
            'readiness_pct': row['readiness_pct'],
            'last_update': int(datetime.now().timestamp())
        }

        return jsonify(response), 200

    except Exception as e:
        log.error(f"[DASHBOARD_SYMBOL_READINESS_API] Error: {e}")
        return jsonify({'error': str(e)}), 500


@dashboard_bp.route('/dashboard/exits', methods=['GET'])
def get_exit_distribution():
    """Get exit type distribution."""
    try:
        result = _query_db('''
            SELECT exit_reason, COUNT(*) as cnt
            FROM trades
            GROUP BY exit_reason
        ''')

        exits = {
            'tp': 0, 'sl': 0, 'scratch': 0, 'stagnation': 0, 'timeout': 0, 'total': 0
        }

        if result:
            for row in result:
                reason = (row['exit_reason'] or 'unknown').lower()
                if reason == 'tp':
                    exits['tp'] = row['cnt']
                elif reason == 'sl':
                    exits['sl'] = row['cnt']
                elif reason in ['scratch', 'scratch_exit']:
                    exits['scratch'] = row['cnt']
                elif reason in ['stagnation', 'stagnation_exit']:
                    exits['stagnation'] = row['cnt']
                elif reason in ['timeout', 'stale_timeout']:
                    exits['timeout'] = row['cnt']
                exits['total'] += row['cnt']

        return jsonify(exits), 200

    except Exception as e:
        log.error(f"[DASHBOARD_EXITS_API] Error: {e}")
        return jsonify({'error': str(e)}), 500


@dashboard_bp.route('/api/dashboard/trades', methods=['GET'])
def get_trades_history():
    """
    Get recent closed trades with full details.

    Returns last 100 trades with all metadata:
    - Entry/exit prices and timestamps
    - PnL (% and USD)
    - Exit reason, regime, MFE/MAE
    - Learning source
    """
    try:
        db_path = _get_db_path()
        if not os.path.exists(db_path):
            return jsonify([]), 200

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get last 100 trades
        cursor.execute('''
            SELECT
                trade_id,
                symbol,
                side,
                entry_price,
                exit_price,
                entry_ts,
                exit_ts,
                pnl_pct,
                pnl_usd,
                mfe_pct,
                mae_pct,
                exit_reason,
                regime,
                size_usd,
                cost_edge_ok,
                learning_source
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

        log.info(f"[DASHBOARD_TRADES_API] Returned {len(trades)} trades")
        return jsonify(trades), 200

    except Exception as e:
        log.error(f"[DASHBOARD_TRADES_API] Error: {e}")
        return jsonify({'error': str(e)}), 500


@dashboard_bp.route('/api/dashboard/trades/<symbol>', methods=['GET'])
def get_symbol_trades(symbol):
    """Get trades for specific symbol."""
    try:
        db_path = _get_db_path()
        if not os.path.exists(db_path):
            return jsonify([]), 200

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                trade_id,
                symbol,
                side,
                entry_price,
                exit_price,
                entry_ts,
                exit_ts,
                pnl_pct,
                pnl_usd,
                mfe_pct,
                mae_pct,
                exit_reason,
                regime,
                size_usd,
                cost_edge_ok,
                learning_source
            FROM trades
            WHERE symbol = ?
            ORDER BY exit_ts DESC
            LIMIT 50
        ''', (symbol.upper(),))

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
        return jsonify(trades), 200

    except Exception as e:
        log.error(f"[DASHBOARD_SYMBOL_TRADES_API] Error: {e}")
        return jsonify({'error': str(e)}), 500


def register_dashboard_endpoints(app):
    """Register dashboard endpoints with Flask app."""
    app.register_blueprint(dashboard_bp)
    log.info("[DASHBOARD_ENDPOINTS] Registered /api/dashboard/* endpoints")
