"""
V10.13x.2 Monitoring — Integrace scratch forensics + health v2 do dashboard

Tiskne:
1. Scratch forensic report (při otevření session)
2. Health decomposition v2 s warnings
3. Scratch pressure alerts (na každou aktualizaci)
4. Expectancy decomposition stub

Voláno z bot2/main.py v monitoring loop.
"""

import logging

log = logging.getLogger(__name__)


def print_v10_13x_2_header():
    """Tiskne hlavičku V10.13x.2 při startu."""
    print("\n" + "=" * 60)
    print("🔬 V10.13x.2 — Scratch Forensics & Health Decomposition v2")
    print("=" * 60)
    print("Priority diagnostics: SCRATCH_EXIT audit, health transparency")
    print("=" * 60)


def print_scratch_forensic_snapshot():
    """Tiskne current snapshot SCRATCH_EXIT analýzy."""
    try:
        from src.services.scratch_forensics import scratch_report, scratch_pressure_alert
    except Exception as e:
        log.warning(f"[V10.13x.2] Could not import scratch_forensics: {e}")
        return

    try:
        report = scratch_report()
        if report.get("status") == "NO_DATA":
            return  # Není dost dat

        total = report.get("total_count", 0)
        net = report.get("net_pnl", 0.0)
        avg = report.get("avg_pnl", 0.0)

        print(f"\n📊 SCRATCH_EXIT Forensics:")
        print(f"   Count: {total}  Net: {net:+.8f}  Avg: {avg:+.8f}")

        # By symbol
        by_sym = report.get("by_symbol", {})
        if by_sym:
            print(f"   By Symbol:")
            for sym, data in sorted(by_sym.items(), key=lambda x: -x[1]["count"])[:3]:
                sym_short = sym.replace("USDT", "")
                print(f"     {sym_short:<6} n={data['count']:<3} net={data['net_pnl']:+.8f} "
                      f"avg={data['avg_pnl']:+.8f}")

        # By PnL bucket
        by_pnl = report.get("by_pnl_bucket", {})
        if by_pnl:
            print(f"   By PnL Bucket:")
            for bucket, data in sorted(by_pnl.items()):
                print(f"     {bucket:<10} n={data['count']:<3} net={data['net_pnl']:+.8f}")

        # Pressure alert
        alert = scratch_pressure_alert()
        if alert.get("alert_level") in ("WARNING", "CRITICAL"):
            print(f"   ⚠️  {alert.get('scratch_impact', '')}")

    except Exception as e:
        log.debug(f"[SCRATCH_FORENSIC] Error: {e}")


def print_health_decomposition_v2():
    """Tiskne detailní health decomposition."""
    try:
        from src.services.learning_monitor import lm_health_components
    except Exception as e:
        log.warning(f"[V10.13x.2] Could not import learning_monitor: {e}")
        return

    try:
        h_dict = lm_health_components()
        status = h_dict.get('status', '?')
        overall = h_dict.get('overall', h_dict.get('final', 0.0))
        components = h_dict.get('components', {})
        warnings = h_dict.get('warnings', [])

        print(f"\n🏥 Health Decomposition v2:")
        print(f"   Overall: {overall:.4f}  [{status}]")

        # Positive components
        print(f"   Components:")
        comp_names = [
            ("edge_strength", "Edge"),
            ("convergence", "Conv"),
            ("stability", "Stab"),
            ("breadth", "Breadth"),
            ("calibration", "Calib"),
        ]
        for key, label in comp_names:
            val = components.get(key, 0.0)
            val_str = f"{val:+.3f}"
            print(f"     {label:<8} {val_str}")

        # Penalties
        scratch_p = components.get('scratch_penalty', 0.0)
        bootstrap_p = components.get('bootstrap_penalty', 0.0)
        if scratch_p < 0 or bootstrap_p < 0:
            print(f"   Penalties:")
            if scratch_p < 0:
                print(f"     Scratch   {scratch_p:+.3f}")
            if bootstrap_p < 0:
                print(f"     Bootstrap {bootstrap_p:+.3f}")

        # Warnings
        if warnings:
            print(f"   ⚠️  Warnings ({len(warnings)}):")
            for w in warnings[:4]:
                print(f"     - {w}")

    except Exception as e:
        log.debug(f"[HEALTH_V2] Error: {e}")


def print_v10_13x_2_monitoring():
    """Main monitoring function — voláno z bot2/main.py."""
    print_scratch_forensic_snapshot()
    print_health_decomposition_v2()


def check_v10_13x_2_alerts():
    """Check for critical alerts — voláno z bot2/main.py v urgent path."""
    try:
        from src.services.scratch_forensics import scratch_pressure_alert
        alert = scratch_pressure_alert()
        level = alert.get('alert_level', 'OK')

        if level == "CRITICAL":
            return f"🚨 {alert.get('scratch_impact', 'SCRATCH_EXIT CRITICAL')}"
        elif level == "WARNING":
            return f"⚠️  {alert.get('scratch_impact', 'SCRATCH_EXIT WARNING')}"

    except Exception as e:
        log.debug(f"[ALERTS_V2] {e}")

    return None  # OK
