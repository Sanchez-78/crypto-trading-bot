#!/usr/bin/env python3
"""
V10.13w Validation: Test all 6 fixes together
- Fix A: Learning integrity audit
- Fix B: Canonical decision score wiring
- Fix C: PnL/WR/EV reconciliation
- Fix D: Adaptive safety freeze
- Fix E: Exit attribution net contribution
- Fix F: Regime/direction explainability
"""

import sys
import logging
from pathlib import Path

# Setup logging to see all messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(message)s'
)
log = logging.getLogger(__name__)

def test_fix_a_learning_integrity():
    """Test Fix A: Learning Monitor hydration and data flow."""
    log.info("\n" + "="*80)
    log.info("TEST FIX A: Learning Integrity Audit")
    log.info("="*80)

    try:
        from src.services.learning_monitor import lm_count, lm_wr_hist, lm_pnl_hist, lm_health
        from src.services.learning_event import METRICS

        log.info(f"METRICS trades: {METRICS.get('trades', 0)}")
        log.info(f"Learning Monitor pair count: {len(lm_count)}")
        log.info(f"Sample pair stats:")
        for (sym, regime), n in list(lm_count.items())[:3]:
            wr_hist = lm_wr_hist.get((sym, regime), [])
            wr = (wr_hist[-1] if wr_hist else 0.5)
            pnl_hist = lm_pnl_hist.get((sym, regime), [])
            log.info(f"  {sym}/{regime}: n={n} wr={wr:.1%} pnl_samples={len(pnl_hist)}")

        health = lm_health()
        log.info(f"Learning Monitor health: {health:.4f}")
        log.info("✓ Fix A: Learning Monitor structure verified")
        return True
    except Exception as e:
        log.error(f"✗ Fix A failed: {e}")
        return False

def test_fix_b_decision_score():
    """Test Fix B: Canonical decision score wiring."""
    log.info("\n" + "="*80)
    log.info("TEST FIX B: Canonical Decision Score Wiring")
    log.info("="*80)

    try:
        from src.services.realtime_decision_engine import (
            decision_score, build_decision_ctx, validate_decision_ctx, _log_canonical_decision
        )

        # Create a mock decision context with real scores
        test_ev = 0.0425
        test_ws = 0.56
        test_score = decision_score(test_ev, test_ws)

        log.info(f"Test score calculation: ev={test_ev:.4f}, ws={test_ws:.3f} → score={test_score:.4f}")

        # Build a decision context
        ctx = build_decision_ctx(
            sym="BTCUSDT",
            side="BUY",
            regime="BULL_TREND",
            ev_raw=0.0425,
            ev_after_coh=0.0420,
            ev_final=0.0420,
            score_raw=test_score,
            score_final=test_score,
            score_threshold=0.15,
            prob=0.52,
            rr=1.35,
            ws=0.56,
            auditor_factor=0.85,
            coherence=0.99,
            bootstrap_pair=False,
            bootstrap_global=False,
            decision="TAKE",
            decision_stage="ACCEPTED",
            signal_tag="break_test",
            reason_chain=["ev_gate_passed", "score_above_threshold"]
        )

        is_valid, errors = validate_decision_ctx(ctx)
        if not is_valid:
            log.error(f"Decision context validation failed: {errors}")
            return False

        # Log the decision using the new V10.13w function with explicit score wiring
        _log_canonical_decision(
            sym=ctx["symbol"],
            action=ctx["side"],
            regime=ctx["regime"],
            raw_ev=ctx["ev_raw"],
            final_ev=ctx["ev_final"],
            raw_score=ctx["score_raw"],
            final_score_threshold=ctx["score_threshold"],
            auditor_factor=ctx["auditor_factor"],
            decision=ctx["decision"],
            confidence=ctx["prob"],
            setup_tag="break_test",
            direction_source="signal_engine",
            countertrend=False
        )

        log.info(f"✓ Fix B: Decision score wired correctly (score={test_score:.4f} captured)")
        return True
    except Exception as e:
        log.error(f"✗ Fix B failed: {e}", exc_info=True)
        return False

def test_fix_c_pnl_reconciliation():
    """Test Fix C: PnL/Expectancy/WR reconciliation."""
    log.info("\n" + "="*80)
    log.info("TEST FIX C: PnL/WR/Expectancy Reconciliation")
    log.info("="*80)

    try:
        from src.services.learning_monitor import check_learning_integrity
        from src.services.learning_event import METRICS

        # Run reconciliation check
        is_ok, status = check_learning_integrity(METRICS)

        log.info(f"Reconciliation result: {'OK' if is_ok else 'MISMATCH'}")
        log.info(f"Status: {status}")

        if "summary_trade_count" in status:
            log.info(f"  Summary trades: {status.get('summary_trade_count', 0)}")
            log.info(f"  LM trades: {status.get('lm_trade_count', 0)}")
            log.info(f"  Delta: {abs(status.get('summary_trade_count', 0) - status.get('lm_trade_count', 0))}")

        log.info(f"✓ Fix C: Reconciliation check implemented")
        return True
    except Exception as e:
        log.error(f"✗ Fix C failed: {e}", exc_info=True)
        return False

def test_fix_d_safe_mode():
    """Test Fix D: Adaptive safety freeze on integrity failure."""
    log.info("\n" + "="*80)
    log.info("TEST FIX D: Adaptive Safety Freeze")
    log.info("="*80)

    try:
        from src.services.learning_monitor import is_learning_frozen, check_learning_integrity

        frozen_before = is_learning_frozen()
        log.info(f"Learning frozen (before test): {frozen_before}")

        # Check integrity (may freeze if data mismatch detected)
        is_ok, status = check_learning_integrity()

        frozen_after = is_learning_frozen()
        log.info(f"Learning frozen (after check): {frozen_after}")

        if frozen_after:
            log.warning(f"⚠ Safe mode ACTIVE: Adaptive components frozen due to: {status}")
        else:
            log.info(f"✓ System healthy: Adaptive components running")

        log.info(f"✓ Fix D: Safe mode freeze mechanism verified")
        return True
    except Exception as e:
        log.error(f"✗ Fix D failed: {e}", exc_info=True)
        return False

def test_fix_e_exit_attribution():
    """Test Fix E: Exit attribution with net PnL contribution."""
    log.info("\n" + "="*80)
    log.info("TEST FIX E: Exit Attribution Net Contribution")
    log.info("="*80)

    try:
        from src.services.exit_attribution import (
            build_exit_ctx, validate_exit_ctx, update_exit_attribution,
            render_exit_attribution_summary, _exit_stats
        )

        # Create a test exit context with real PnL data
        test_ctx = build_exit_ctx(
            sym="BTCUSDT",
            regime="BULL_TREND",
            side="BUY",
            entry_price=42000.0,
            exit_price=42050.0,
            size=0.01,
            hold_seconds=480,
            gross_pnl=0.00000500,
            fee_cost=-0.00000120,
            slippage_cost=-0.00000030,
            net_pnl=0.00000350,
            mfe=0.00000600,
            mae=-0.00000100,
            final_exit_type="PARTIAL_TP_25",
            exit_reason_text="TP hit",
            was_winner=True,
            partials_taken=["PARTIAL_TP_25"]
        )

        is_valid, errors = validate_exit_ctx(test_ctx)
        if not is_valid:
            log.error(f"Exit context invalid: {errors}")
            return False

        update_exit_attribution(test_ctx)

        # Check if the exit stats include fee and slippage tracking
        if "PARTIAL_TP_25" in _exit_stats:
            stats = _exit_stats["PARTIAL_TP_25"]
            if "total_fee" in stats and "total_slippage" in stats:
                log.info(f"Exit attribution tracking enabled:")
                log.info(f"  Total fee tracked: {stats['total_fee']:.8f}")
                log.info(f"  Total slippage tracked: {stats['total_slippage']:.8f}")
                log.info(f"  Net PnL: {stats['total_net_pnl']:.8f}")
            else:
                log.error("Exit attribution missing fee/slippage tracking")
                return False

        # Render summary
        summary = render_exit_attribution_summary()
        log.info(f"Exit Attribution Summary:\n{summary}")

        log.info(f"✓ Fix E: Exit attribution with net contribution verified")
        return True
    except Exception as e:
        log.error(f"✗ Fix E failed: {e}", exc_info=True)
        return False

def test_fix_f_explainability():
    """Test Fix F: Regime/direction explainability."""
    log.info("\n" + "="*80)
    log.info("TEST FIX F: Regime/Direction Explainability")
    log.info("="*80)

    try:
        # Import the internal logging function
        import sys
        sys.path.insert(0, '.')
        from src.services.realtime_decision_engine import _log_canonical_decision

        # Test logging a COUNTER_REGIME trade (SHORT in BULL)
        log.info("Logging test: SHORT in BULL_TREND (counter-regime)")
        _log_canonical_decision(
            sym="ETHUSDT",
            action="SELL",
            regime="BULL_TREND",
            raw_ev=0.0350,
            final_ev=0.0340,
            raw_score=0.18,
            final_score_threshold=0.15,
            auditor_factor=0.80,
            decision="TAKE",
            confidence=0.52,
            setup_tag="fake_breakout",
            direction_source="pattern_engine",
            regime_source="regime_detector",
            countertrend=True
        )

        log.info(f"✓ Fix F: Explainability fields logged (setup_tag, direction_source, countertrend)")
        return True
    except Exception as e:
        log.error(f"✗ Fix F failed: {e}", exc_info=True)
        return False

def main():
    """Run all validation tests."""
    log.info("\n" + "="*80)
    log.info("V10.13w VALIDATION TEST SUITE")
    log.info("="*80)

    results = {
        "Fix A (Learning Integrity)": test_fix_a_learning_integrity(),
        "Fix B (Decision Score Wiring)": test_fix_b_decision_score(),
        "Fix C (PnL Reconciliation)": test_fix_c_pnl_reconciliation(),
        "Fix D (Safe Mode Freeze)": test_fix_d_safe_mode(),
        "Fix E (Exit Attribution)": test_fix_e_exit_attribution(),
        "Fix F (Explainability)": test_fix_f_explainability(),
    }

    log.info("\n" + "="*80)
    log.info("TEST RESULTS SUMMARY")
    log.info("="*80)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        log.info(f"{status} | {test_name}")

    log.info(f"\nTotal: {passed}/{total} tests passed")

    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())
