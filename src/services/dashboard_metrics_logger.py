"""
V10.20: Dashboard metrics logger

Logs trading metrics in format expected by dashboard_http_server.py
which parses logs via regex: closed_today=N, profit_factor=X.XX, net_pnl=Y.YY

This ensures dashboard shows live metrics even when Firebase is unavailable.
"""

import sqlite3
import logging
import time

_log = logging.getLogger(__name__)

def log_dashboard_metrics():
    """Query local SQLite and log metrics in dashboard-friendly format."""
    try:
        conn = sqlite3.connect("local_learning_storage/learning_database.sqlite", timeout=2)
        cursor = conn.cursor()

        # Get closed trades today
        cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                   SUM(CASE WHEN pnl_pct < 0 THEN 1 ELSE 0 END) as losses,
                   SUM(pnl_usd) as net_pnl
            FROM trades
            WHERE close_ts > strftime('%s', 'now', 'start of day')
        """)

        row = cursor.fetchone()
        total = row[0] if row[0] else 0
        wins = row[1] if row[1] else 0
        losses = row[2] if row[2] else 0
        net_pnl = row[3] if row[3] else 0.0

        # Calculate profit factor
        pf = 1.0
        if wins > 0 and losses > 0:
            cursor.execute("""
                SELECT SUM(ABS(pnl_usd)) FROM trades
                WHERE close_ts > strftime('%s', 'now', 'start of day') AND pnl_usd > 0
            """)
            wins_pnl = cursor.fetchone()[0] or 0.0

            cursor.execute("""
                SELECT SUM(ABS(pnl_usd)) FROM trades
                WHERE close_ts > strftime('%s', 'now', 'start of day') AND pnl_usd < 0
            """)
            losses_pnl = cursor.fetchone()[0] or 0.0

            if losses_pnl > 0:
                pf = wins_pnl / losses_pnl
        elif total == 0:
            pf = 1.0

        conn.close()

        # Log in format dashboard expects
        _log.info(f"[DASHBOARD_METRICS] closed_today={total} profit_factor={pf:.2f} net_pnl={net_pnl:.8f} wins={wins} losses={losses}")

    except Exception as e:
        _log.warning(f"[DASHBOARD_METRICS_ERROR] {e}")

# Call this periodically (e.g., every 30 seconds) from main bot loop
