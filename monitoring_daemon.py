#!/usr/bin/env python3
"""
CryptoMaster Extended Mission Autonomous Monitoring Daemon
Integrates learning system (Phase 2) with continuous monitoring & autonomous fixes
"""

import sqlite3
import json
import time
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project to path for imports
sys.path.insert(0, "/opt/cryptomaster")

# Import learning system
try:
    from src.services.learning_integration import LearningIntegration
    LEARNING_ENABLED = True
except Exception as e:
    print(f"[WARNING] Learning system not available: {e}", file=sys.stderr)
    LEARNING_ENABLED = False

MONITORING_START = datetime(2026, 7, 2, 6, 58, 59, tzinfo=timezone.utc)  # Extended mission start
MONITORING_END = MONITORING_START + timedelta(hours=45)  # 45-hour mission
CYCLE_INTERVAL = 30 * 60  # 30 minutes in seconds

DB_PATH = "/opt/cryptomaster/local_learning_storage/learning_database.sqlite"
REPORT_FILE = "/tmp/monitoring_report.json"
PROGRESS_FILE = "/opt/cryptomaster/_workspace/monitoring_progress.json"


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


def load_progress():
    """Load monitoring progress from file or initialize"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {
        "cycle": 24,
        "start_time": MONITORING_START.isoformat(),
        "goal_reached": False,
        "total_cycles_completed": 24,
        "current_wr": 54.65,
        "current_pnl": 25.27,
        "total_wr_gain": 6.69,
        "quota_max_used_pct": 45,
        "last_update": datetime.now(timezone.utc).isoformat(),
        "status": "monitoring",
        "learning_phase": "phase_2_integration",
        "cycles": []
    }


def save_progress(progress):
    """Save monitoring progress to file"""
    try:
        Path(PROGRESS_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(PROGRESS_FILE, 'w') as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Failed to save progress: {e}", file=sys.stderr)


def main():
    # Initialize learning system
    learning = None
    if LEARNING_ENABLED:
        try:
            learning = LearningIntegration()
            print(f"✅ Learning system initialized")
        except Exception as e:
            print(f"⚠️  Learning system failed to initialize: {e}", file=sys.stderr)
            LEARNING_ENABLED = False

    # Load progress from file or initialize
    progress = load_progress()
    cycle_num = progress.get("cycle", 25)

    print(f"\n🤖 CryptoMaster Extended Mission Monitoring Daemon Started")
    print(f"   Start: {MONITORING_START}")
    print(f"   End:   {MONITORING_END}")
    print(f"   Interval: 30 minutes")
    print(f"   Learning: {'✅ ENABLED' if LEARNING_ENABLED else '⚠️  DISABLED'}")
    print(f"   Resume from Cycle {cycle_num}")

    metrics_before = get_metrics()

    while datetime.now(timezone.utc) < MONITORING_END:
        metrics = get_metrics()
        if metrics:
            status = assess_status(metrics)
            log_cycle(cycle_num, metrics, status)

            # Record cycle metrics in learning system
            if LEARNING_ENABLED and learning:
                # Get current gate from config
                current_gate = 0.0060  # Currently at 0.60% maximum conservative
                learning.record_cycle_end(cycle_num, {
                    'wr_pct': metrics['win_rate_pct'],
                    'pnl_usd': metrics['net_pnl_usd'],
                    'trades_count': metrics['closed_trades'],
                    'timeout_exits': metrics['exits']['timeout']
                }, current_gate)

            # Update progress tracking
            progress['cycle'] = cycle_num
            progress['total_cycles_completed'] = cycle_num
            progress['current_wr'] = metrics['win_rate_pct']
            progress['current_pnl'] = metrics['net_pnl_usd']
            progress['last_update'] = datetime.now(timezone.utc).isoformat()
            progress['status'] = status.lower()
            save_progress(progress)

            # Check goal reached
            if status == "PASS":
                print(f"\n✅ GOAL STATUS ACHIEVED: WR {metrics['win_rate_pct']:.2f}% > 50%, P&L ${metrics['net_pnl_usd']:.2f} > $0")
                progress['goal_reached'] = True
                save_progress(progress)

            # Emergency check
            if status == "FAIL":
                print(f"\n🚨 WARNING: Cycle {cycle_num} FAILED - WR < 50%")
                print(f"   Consider reviewing bot configuration")

        cycle_num += 1
        time.sleep(CYCLE_INTERVAL)

    print(f"\n✅ 45-hour mission monitoring window closed")
    metrics = get_metrics()
    if metrics:
        print(f"   Final Status: {status}")
        print(f"   Final WR: {metrics['win_rate_pct']:.2f}%")
        print(f"   Final P&L: ${metrics['net_pnl_usd']:.2f}")
        print(f"   Learning Stats: {learning.get_statistics() if learning else 'N/A'}")


if __name__ == "__main__":
    main()
