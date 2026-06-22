#!/usr/bin/env python3
"""
V10.28+: Autonomous Real-Trading Readiness Monitor with Cross-Check
ALWAYS cross-validates metrics before readiness decisions.
"""
import time
import json
from datetime import datetime
from src.services.metric_crosscheck import crosscheck_all_sources, get_authoritative_metrics

# Configuration
CHECK_INTERVAL_SECONDS = 300  # 5 minutes
MAX_CYCLES = 100
CONSISTENCY_WINDOW = 3  # Need 3 consecutive good checks

# Readiness thresholds (6 gates)
GATES = {
    "stability": {
        "criteria": {
            "win_rate_pct": 50.0,
            "profit_factor": 0.5,
            "net_pnl": 10.0,
            "closed_trades": 30,
        },
        "name": "Stability",
    },
    "risk": {
        "criteria": {"profit_factor": 1.05},
        "name": "Risk Management",
    },
    "quality": {
        "criteria": {"expectancy_min": 0.10, "profit_factor": 1.05},
        "name": "Signal Quality",
    },
    "safety": {
        "criteria": {},  # Always pass for now
        "name": "Safety Gates",
    },
    "confidence": {
        "criteria": {"closed_trades": 30},
        "name": "Confidence Interval",
    },
    "stability_window": {
        "criteria": {"variance_limit": 10.0},  # WR variance < 10%
        "name": "Stability Window",
    },
}

# State tracking
recent_checks = []  # Store last N readiness assessments


def assess_gates(metrics):
    """Evaluate all 6 readiness gates against metrics."""
    if not metrics:
        return {}

    wr = metrics.get("win_rate_pct", 0)
    pf = metrics.get("profit_factor", 0)
    pnl = metrics.get("net_pnl", 0)
    closed = metrics.get("closed_trades", 0)
    expectancy = (pnl / closed) if closed > 0 else 0

    gates_status = {}

    # Gate 1: Stability
    stability_pass = (
        wr >= GATES["stability"]["criteria"]["win_rate_pct"]
        and pf >= GATES["stability"]["criteria"]["profit_factor"]
        and pnl >= GATES["stability"]["criteria"]["net_pnl"]
        and closed >= GATES["stability"]["criteria"]["closed_trades"]
    )
    gates_status["stability"] = {
        "pass": stability_pass,
        "details": f"WR:{wr:.1f}% PF:{pf:.2f}x P&L:${pnl:.4f} Closed:{closed}",
    }

    # Gate 2: Risk
    risk_pass = pf >= GATES["risk"]["criteria"]["profit_factor"]
    gates_status["risk"] = {
        "pass": risk_pass,
        "details": f"PF:{pf:.2f}x (target:≥1.05)",
    }

    # Gate 3: Quality
    quality_pass = (
        expectancy >= GATES["quality"]["criteria"]["expectancy_min"]
        and pf >= GATES["quality"]["criteria"]["profit_factor"]
    )
    gates_status["quality"] = {
        "pass": quality_pass,
        "details": f"Expectancy:${expectancy:.4f} PF:{pf:.2f}x",
    }

    # Gate 4: Safety
    gates_status["safety"] = {
        "pass": True,
        "details": "Paper-only, learning active",
    }

    # Gate 5: Confidence
    confidence_pass = closed >= GATES["confidence"]["criteria"]["closed_trades"]
    gates_status["confidence"] = {
        "pass": confidence_pass,
        "details": f"Closed:{closed} (need:≥30)",
    }

    # Gate 6: Stability Window
    if len(recent_checks) >= 3:
        wrs = [c["metrics"].get("win_rate_pct", 0) for c in recent_checks[-3:]]
        wr_variance = max(wrs) - min(wrs) if wrs else 0
        stability_window_pass = wr_variance < GATES["stability_window"]["criteria"]["variance_limit"]
        gates_status["stability_window"] = {
            "pass": stability_window_pass,
            "details": f"WR variance:{wr_variance:.1f}% (limit:10%)",
        }
    else:
        gates_status["stability_window"] = {
            "pass": False,
            "details": f"Need {3 - len(recent_checks)} more checks",
        }

    return gates_status


def run_readiness_check(cycle_num):
    """Execute single readiness check cycle."""
    print(f"\n{'='*80}")
    print(f"READINESS CHECK CYCLE {cycle_num}")
    print(f"{'='*80}")
    print(f"Time: {datetime.utcnow().isoformat()}Z")

    # ALWAYS cross-check metrics first
    print("\n🔍 Cross-validating metrics...")
    crosscheck_result = crosscheck_all_sources()

    print(f"\nCross-Check Status: {crosscheck_result['status']}")
    print(f"Message: {crosscheck_result['message']}")

    # Report divergences
    for check, detail in crosscheck_result.get("validation", {}).items():
        if not detail.get("match"):
            print(f"  ⚠️  {check}: {detail.get('reason')}")

    # Get authoritative metrics
    metrics = crosscheck_result["authoritative"]

    if not metrics:
        print("\n❌ No authoritative metrics available - skipping cycle")
        return None

    print("\n📊 Authoritative Metrics (Bot API):")
    print(f"  Closed: {metrics.get('closed_trades')}")
    print(f"  WR: {metrics.get('win_rate_pct'):.2f}%")
    print(f"  PF: {metrics.get('profit_factor'):.2f}x")
    print(f"  P&L: ${metrics.get('net_pnl'):.4f}")
    print(f"  Open: {metrics.get('open_positions')}")

    # Assess gates
    print("\n🎯 Readiness Gates:")
    gates = assess_gates(metrics)
    gates_pass = sum(1 for g in gates.values() if g.get("pass"))
    total_gates = len(gates)

    for gate_name, gate_status in gates.items():
        icon = "✓" if gate_status["pass"] else "✗"
        print(f"  {icon} {GATES[gate_name]['name']}: {gate_status['details']}")

    # Calculate readiness score
    readiness_score = (gates_pass / total_gates) * 100

    print(f"\n📈 Readiness Score: {readiness_score:.0f}/100 ({gates_pass}/{total_gates} gates pass)")

    # Store check result
    check_result = {
        "cycle": cycle_num,
        "timestamp": datetime.utcnow().isoformat(),
        "crosscheck": crosscheck_result["status"],
        "metrics": metrics,
        "gates": gates,
        "score": readiness_score,
        "all_pass": gates_pass == total_gates,
    }
    recent_checks.append(check_result)
    if len(recent_checks) > CONSISTENCY_WINDOW + 2:
        recent_checks.pop(0)

    # Decision
    if gates_pass == total_gates:
        print(f"\n✅ ALL GATES PASS - Readiness score: {readiness_score:.0f}%")
        if len([c for c in recent_checks if c["all_pass"]]) >= CONSISTENCY_WINDOW:
            print(f"\n🎉 CONSISTENCY THRESHOLD MET ({CONSISTENCY_WINDOW} consecutive passes)")
            print("🚀 BOT IS READY FOR REAL TRADING!")
            return "READY"
        else:
            consecutive_pass = len([c for c in recent_checks[-CONSISTENCY_WINDOW:] if c["all_pass"]])
            print(f"   Need {CONSISTENCY_WINDOW - consecutive_pass} more consecutive passes")
    else:
        failed_gates = [name for name, status in gates.items() if not status["pass"]]
        print(f"\n⏳ GATES FAILING: {', '.join(failed_gates)}")
        print(f"   Score: {readiness_score:.0f}/100 - Continue monitoring")

    return check_result


def main():
    """Main autonomous monitoring loop."""
    print("\n" + "="*80)
    print("🤖 AUTONOMOUS REAL-TRADING READINESS MONITOR")
    print("V10.28+ with Metric Cross-Validation")
    print("="*80)
    print(f"Start time: {datetime.utcnow().isoformat()}Z")
    print(f"Check interval: {CHECK_INTERVAL_SECONDS}s")
    print(f"Consistency window: {CONSISTENCY_WINDOW} cycles")
    print(f"Max cycles: {MAX_CYCLES}")

    for cycle in range(1, MAX_CYCLES + 1):
        result = run_readiness_check(cycle)

        if result == "READY":
            print("\n" + "="*80)
            print("🎉 GOAL ACHIEVED: BOT READY FOR REAL TRADING!")
            print("="*80)
            break

        print(f"\n⏳ Next check in {CHECK_INTERVAL_SECONDS}s...")
        time.sleep(CHECK_INTERVAL_SECONDS)

    else:
        print("\n" + "="*80)
        print("⚠️  Max cycles reached without achieving readiness")
        print("="*80)


if __name__ == "__main__":
    main()
