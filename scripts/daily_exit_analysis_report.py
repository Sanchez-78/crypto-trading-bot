#!/usr/bin/env python3
"""
Daily Exit Analysis Report — Monitors scratch/stagnation exit effectiveness

Runs daily (via cron) to produce:
- Exit attribution breakdown (count, PnL by type)
- Scratch/stagnation analysis (count, net loss, MFE)
- PF-first metrics (profit factor, net PnL, expectancy)
- Recommendations for Phase 3 implementation
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.services.canonical_metrics import (
    canonical_profit_factor_with_meta,
    classify_health_status
)
from src.services.exit_attribution import analyze_scratch_stagnation_exits


def load_closed_trades() -> list:
    """Load closed trades from Firebase or local backup."""
    # For now, return empty (will use live data from Firebase on Hetzner)
    # This script runs on Hetzner where Firebase client is configured
    return []


def generate_daily_report() -> str:
    """Generate comprehensive daily exit analysis report."""

    timestamp = datetime.utcnow().isoformat()
    closed_trades = load_closed_trades()

    if not closed_trades:
        return f"[DAILY_EXIT_ANALYSIS] {timestamp} — No trades found\n"

    # Calculate metrics
    pf_meta = canonical_profit_factor_with_meta(closed_trades)
    pf = pf_meta.get("pf", 0.0)
    net_pnl = pf_meta.get("net_pnl", 0.0)
    wins = pf_meta.get("wins", 0)
    losses = pf_meta.get("losses", 0)
    total = pf_meta.get("closed_trades", 0)

    expectancy = net_pnl / total if total > 0 else 0.0
    wr = wins / (wins + losses) if (wins + losses) > 0 else 0.0

    # Analyze exits
    exit_analysis = analyze_scratch_stagnation_exits(closed_trades)

    # Classify health
    health = classify_health_status(pf, net_pnl, expectancy)

    # Build report
    lines = [
        "═" * 80,
        f"DAILY EXIT ANALYSIS REPORT — {timestamp}",
        "═" * 80,
        "",
        "📊 CANONICAL METRICS",
        f"  Closed trades: {total}",
        f"  Wins: {wins} / Losses: {losses}",
        f"  Win Rate: {wr:.1%}",
        f"  Profit Factor: {pf:.2f}x",
        f"  Net PnL: {net_pnl:.8f} USD",
        f"  Expectancy: {expectancy:.8f} USD/trade",
        f"  Health Status: {health['status']}",
        "",
        "🚪 EXIT ATTRIBUTION",
        f"  SCRATCH_EXIT: {exit_analysis['scratch_n']} trades, "
        f"net {exit_analysis['scratch_net']:.8f} USD, "
        f"MFE median {exit_analysis['scratch_mfe_median']:.8f}",
        f"  STAGNATION_EXIT: {exit_analysis['stag_n']} trades, "
        f"net {exit_analysis['stag_net']:.8f} USD, "
        f"MFE median {exit_analysis['stag_mfe_median']:.8f}",
        "",
        "💡 RECOMMENDATION",
        f"  {exit_analysis['recommendation'] or 'No action needed (exits are profitable)'}",
        "",
        "ℹ️  Next: Monitor for 24-48h, then evaluate Phase 3 (exit repair) implementation",
        "═" * 80,
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    report = generate_daily_report()
    print(report)

    # Log to file
    log_file = Path(__file__).parent.parent / "logs" / "daily_exit_analysis.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a") as f:
        f.write(report + "\n\n")

    print(f"\n✅ Report logged to {log_file}")
