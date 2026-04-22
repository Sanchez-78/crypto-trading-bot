#!/usr/bin/env python
"""
V10.13v (Fix 6 + Fix 7): Test script showing canonical decision and exit output.

This script demonstrates the expected log output format for:
- Fix 6: Canonical decision logging with eliminated ambiguous combinations
- Fix 7: Exit outcome distribution and realized edge attribution
"""

import sys
sys.path.insert(0, '/root/CryptoMaster_srv')

from src.services.realtime_decision_engine import (
    validate_decision_ctx, build_decision_ctx
)
from src.services.exit_attribution import (
    build_exit_ctx, validate_exit_ctx, update_exit_attribution,
    render_exit_attribution_summary, EXIT_TYPES
)

def test_fix6_canonical_decision():
    """Test Fix 6: Canonical decision logging."""
    print("\n" + "="*80)
    print("FIX 6: CANONICAL DECISION LOGGING")
    print("="*80)
    
    # Example 1: Accepted decision with positive EV
    ctx_accept = build_decision_ctx(
        sym="BTCUSDT",
        side="BUY",
        regime="BULL_TREND",
        ev_raw=0.0500,
        ev_after_coh=0.0348,
        ev_final=0.0348,
        score_raw=0.1850,
        score_final=0.1850,
        score_threshold=0.1728,
        prob=0.533,
        rr=1.25,
        ws=0.500,
        auditor_factor=0.70,
        coherence=0.500,
        bootstrap_pair=False,
        bootstrap_global=False,
        decision="TAKE",
        decision_stage="RDE",
        signal_tag="MOMENTUM_UP",
    )
    
    is_valid, errors = validate_decision_ctx(ctx_accept)
    print("\n✅ ACCEPTED DECISION (Valid={})".format(is_valid))
    print(f"[V10.13v DECISION] {ctx_accept['symbol']} {ctx_accept['side']} {ctx_accept['regime']} {ctx_accept['alignment']}")
    print(f"  tag={ctx_accept['signal_tag']} stage={ctx_accept['decision_stage']}")
    print(f"  ev_raw={ctx_accept['ev_raw']:.4f} ev_coh={ctx_accept['ev_after_coherence']:.4f} ev_final={ctx_accept['ev_final']:.4f}")
    print(f"  score_raw={ctx_accept['score_raw']:.4f} score_final={ctx_accept['score_final']:.4f} thr={ctx_accept['score_threshold']:.4f}")
    print(f"  p={ctx_accept['prob']:.3f} rr={ctx_accept['rr']:.2f} ws={ctx_accept['ws']:.3f} af={ctx_accept['auditor_factor']:.2f} coh={ctx_accept['coherence']:.3f}")
    print(f"  bootstrap=pair:{ctx_accept['bootstrap_pair']} global:{ctx_accept['bootstrap_global']}")
    print(f"  result={ctx_accept['decision']}")
    
    # Example 2: Rejected decision with negative EV
    ctx_reject = build_decision_ctx(
        sym="ETHUSDT",
        side="SELL",
        regime="BEAR_TREND",
        ev_raw=-0.0500,
        ev_after_coh=-0.0399,
        ev_final=-0.0399,
        score_raw=0.1310,
        score_final=0.1310,
        score_threshold=0.1728,
        prob=0.479,
        rr=1.50,
        ws=0.555,
        auditor_factor=0.70,
        coherence=0.797,
        bootstrap_pair=False,
        bootstrap_global=False,
        decision="REJECT",
        decision_stage="EV_GATE",
        signal_tag="BEARISH_BREAKDOWN",
    )
    
    is_valid, errors = validate_decision_ctx(ctx_reject)
    print("\n❌ REJECTED DECISION (Valid={})".format(is_valid))
    if errors:
        print("  Validation errors:")
        for err in errors:
            print(f"    - {err}")
    print(f"[V10.13v DECISION] {ctx_reject['symbol']} {ctx_reject['side']} {ctx_reject['regime']} {ctx_reject['alignment']}")
    print(f"  tag={ctx_reject['signal_tag']} stage={ctx_reject['decision_stage']}")
    print(f"  ev_raw={ctx_reject['ev_raw']:.4f} ev_coh={ctx_reject['ev_after_coherence']:.4f} ev_final={ctx_reject['ev_final']:.4f}")
    print(f"  score_raw={ctx_reject['score_raw']:.4f} score_final={ctx_reject['score_final']:.4f} thr={ctx_reject['score_threshold']:.4f}")
    print(f"  p={ctx_reject['prob']:.3f} rr={ctx_reject['rr']:.2f} ws={ctx_reject['ws']:.3f} af={ctx_reject['auditor_factor']:.2f} coh={ctx_reject['coherence']:.3f}")
    print(f"  bootstrap=pair:{ctx_reject['bootstrap_pair']} global:{ctx_reject['bootstrap_global']}")
    print(f"  result={ctx_reject['decision']} (reason: {ctx_reject['decision_stage']})")


def test_fix7_exit_attribution():
    """Test Fix 7: Exit outcome distribution and attribution."""
    print("\n" + "="*80)
    print("FIX 7: EXIT OUTCOME DISTRIBUTION AND ATTRIBUTION")
    print("="*80)
    
    # Simulate several trades with different exit types
    trades = [
        {"sym": "BTCUSDT", "regime": "BULL_TREND", "side": "BUY", "exit": "TP", "hold": 45, "gross": 0.00150, "fee": 0.00010, "net": 0.00140, "mfe": 0.020, "mae": 0.001, "winner": True},
        {"sym": "ETHUSDT", "regime": "BULL_TREND", "side": "BUY", "exit": "TP", "hold": 60, "gross": 0.00120, "fee": 0.00012, "net": 0.00108, "mfe": 0.015, "mae": 0.002, "winner": True},
        {"sym": "ADAUSDT", "regime": "BULL_TREND", "side": "BUY", "exit": "TP", "hold": 30, "gross": 0.00090, "fee": 0.00009, "net": 0.00081, "mfe": 0.012, "mae": 0.001, "winner": True},
        {"sym": "BTCUSDT", "regime": "BEAR_TREND", "side": "SELL", "exit": "SL", "hold": 15, "gross": -0.00080, "fee": 0.00010, "net": -0.00090, "mfe": 0.001, "mae": 0.008, "winner": False},
        {"sym": "ETHUSDT", "regime": "RANGING", "side": "BUY", "exit": "SL", "hold": 12, "gross": -0.00100, "fee": 0.00010, "net": -0.00110, "mfe": 0.002, "mae": 0.010, "winner": False},
        {"sym": "ADAUSDT", "regime": "RANGING", "side": "BUY", "exit": "SCRATCH_EXIT", "hold": 25, "gross": -0.00005, "fee": 0.00008, "net": -0.00013, "mfe": 0.001, "mae": 0.001, "winner": False},
        {"sym": "BTCUSDT", "regime": "RANGING", "side": "SELL", "exit": "SCRATCH_EXIT", "hold": 18, "gross": -0.00004, "fee": 0.00008, "net": -0.00012, "mfe": 0.001, "mae": 0.001, "winner": False},
        {"sym": "ETHUSDT", "regime": "BULL_TREND", "side": "BUY", "exit": "SCRATCH_EXIT", "hold": 30, "gross": -0.00003, "fee": 0.00008, "net": -0.00011, "mfe": 0.001, "mae": 0.001, "winner": False},
        {"sym": "ADAUSDT", "regime": "RANGING", "side": "SELL", "exit": "TIMEOUT_FLAT", "hold": 90, "gross": 0.00002, "fee": 0.00008, "net": -0.00006, "mfe": 0.001, "mae": 0.001, "winner": False},
        {"sym": "BTCUSDT", "regime": "HIGH_VOL", "side": "BUY", "exit": "TIMEOUT_PROFIT", "hold": 120, "gross": 0.00060, "fee": 0.00010, "net": 0.00050, "mfe": 0.008, "mae": 0.003, "winner": True},
        {"sym": "ETHUSDT", "regime": "BEAR_TREND", "side": "SELL", "exit": "PARTIAL_TP_50", "hold": 35, "gross": 0.00080, "fee": 0.00008, "net": 0.00072, "mfe": 0.010, "mae": 0.002, "winner": True},
    ]
    
    print("\nProcessing {} simulated trades...".format(len(trades)))
    for trade in trades:
        exit_ctx = build_exit_ctx(
            sym=trade["sym"],
            regime=trade["regime"],
            side=trade["side"],
            entry_price=100.0,
            exit_price=100.0 + (0.01 if trade["winner"] else -0.01),
            size=1.0,
            hold_seconds=trade["hold"],
            gross_pnl=trade["gross"],
            fee_cost=trade["fee"],
            slippage_cost=0.0,
            net_pnl=trade["net"],
            mfe=trade["mfe"],
            mae=trade["mae"],
            final_exit_type=trade["exit"],
            was_winner=trade["winner"],
        )
        
        is_valid, errors = validate_exit_ctx(exit_ctx)
        if not is_valid:
            print(f"  ❌ Validation failed for {trade['sym']}: {errors}")
        else:
            update_exit_attribution(exit_ctx)
            print(f"  ✅ {trade['sym']} {trade['exit']:20s} | hold={trade['hold']:3d}s | pnl={trade['net']:+.6f}")
    
    # Print summary
    print("\n" + render_exit_attribution_summary())


if __name__ == "__main__":
    print("\n" + "█"*80)
    print("V10.13v: FIX 6 + FIX 7 OUTPUT VERIFICATION")
    print("█"*80)
    
    test_fix6_canonical_decision()
    test_fix7_exit_attribution()
    
    print("\n" + "█"*80)
    print("TEST COMPLETE")
    print("█"*80 + "\n")
