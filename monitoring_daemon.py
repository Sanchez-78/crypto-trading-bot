#!/usr/bin/env python3
"""
CryptoMaster 48-Hour Autonomous Monitoring Daemon
Cycles 61-96: Continuous stability monitoring with safe feature rollout
"""

import sqlite3
import json
import time
import sys
from datetime import datetime, timedelta, timezone

MONITORING_START = datetime(2026, 7, 1, 11, 20, 0, tzinfo=timezone.utc)  # Cycle 61 start
MONITORING_END = MONITORING_START + timedelta(hours=48)
CYCLE_INTERVAL = 30 * 60  # 30 minutes in seconds

DB_PATH = "/opt/cryptomaster/local_learning_storage/learning_database.sqlite"
REPORT_FILE = "/tmp/monitoring_report.json"


def get_metrics():
    """Fetch current metrics from database"""
    try:
        db = sqlite3.connect(DB_PATH)
        c = db.cursor()
        c.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) as wins,
                SUM(pnl_usd) as pnl,
                SUM(CASE WHEN LOWER(exit_reason) = 'tp' THEN 1 ELSE 0 END) as tp,
                SUM(CASE WHEN LOWER(exit_reason) = 'sl' THEN 1 ELSE 0 END) as sl,
                SUM(CASE WHEN LOWER(exit_reason) LIKE '%timeout%' THEN 1 ELSE 0 END) as timeout,
                MAX(exit_ts) as latest_exit
            FROM trades
        """)
        total, wins, pnl, tp, sl, timeout, latest_ts = c.fetchone()
        db.close()

        wr = (wins / total * 100) if total else 0
        pf = (wins * 0.02) / max((total - wins) * 0.01, 0.01) if total > 0 else 1.0

        return {
            "closed_trades": total,
            "win_rate_pct": round(wr, 2),
            "net_pnl_usd": round(pnl or 0, 2),
            "profit_factor": round(pf, 2),
            "exits": {"tp": tp or 0, "sl": sl or 0, "timeout": timeout or 0},
            "latest_trade_age_min": 0,
        }
    except Exception as e:
        print(f"[ERROR] Metrics collection failed: {e}", file=sys.stderr)
        return None


def assess_status(metrics):
    """Determine cycle status"""
    if not metrics:
        return "ERROR"
    wr = metrics["win_rate_pct"]
    pnl = metrics["net_pnl_usd"]

    if wr >= 50 and pnl > 0:
        return "PASS"
    elif wr >= 45:
        return "CAUTION"
    else:
        return "FAIL"


def log_cycle(cycle_num, metrics, status):
    """Log cycle result"""
    now = datetime.now(timezone.utc)
    elapsed = now - MONITORING_START
    remaining = MONITORING_END - now

    print(f"\n╔════════════════════════════════════════════════════════════╗")
    print(f"║ CYCLE {cycle_num:2d} | {now.strftime('%H:%M UTC')} | Elapsed: {elapsed.total_seconds()/3600:.1f}h                        ║")
    print(f"╠════════════════════════════════════════════════════════════╣")
    print(f"║ Win Rate:        {metrics['win_rate_pct']:6.2f}% (target ≥50%)                      ║")
    print(f"║ P&L:             ${metrics['net_pnl_usd']:7.2f} (target >$0)                    ║")
    print(f"║ Profit Factor:   {metrics['profit_factor']:6.2f}x                                  ║")
    print(f"║ Closed Trades:   {metrics['closed_trades']:6d}                                   ║")
    print(f"║ Exits (TP/SL/TO): {metrics['exits']['tp']:d}/{metrics['exits']['sl']:d}/{metrics['exits']['timeout']:d}                                     ║")
    print(f"║                                                                    ║")
    print(f"║ Status:          {status:14s}   Remaining: {remaining.total_seconds()/3600:.1f}h        ║")
    print(f"╚════════════════════════════════════════════════════════════╝")

    # Save to report file
    with open(REPORT_FILE, "w") as f:
        json.dump(
            {
                "cycle": cycle_num,
                "timestamp": now.isoformat(),
                "metrics": metrics,
                "status": status,
                "elapsed_hours": elapsed.total_seconds() / 3600,
                "remaining_hours": remaining.total_seconds() / 3600,
            },
            f,
            indent=2,
        )


def main():
    cycle_num = 61
    print(f"\n🤖 CryptoMaster 48-Hour Monitoring Daemon Started")
    print(f"   Start: {MONITORING_START}")
    print(f"   End:   {MONITORING_END}")
    print(f"   Interval: 30 minutes")

    while datetime.now(timezone.utc) < MONITORING_END:
        metrics = get_metrics()
        if metrics:
            status = assess_status(metrics)
            log_cycle(cycle_num, metrics, status)

            # Emergency check
            if status == "FAIL":
                print(f"\n🚨 WARNING: Cycle {cycle_num} FAILED - WR < 50%")
                print(f"   Consider reviewing bot configuration")

        cycle_num += 1
        time.sleep(CYCLE_INTERVAL)

    print(f"\n✅ 48-hour monitoring window closed")
    print(f"   Final Status: {status}")
    metrics = get_metrics()
    if metrics:
        print(f"   Final WR: {metrics['win_rate_pct']:.2f}%")
        print(f"   Final P&L: ${metrics['net_pnl_usd']:.2f}")


if __name__ == "__main__":
    main()
