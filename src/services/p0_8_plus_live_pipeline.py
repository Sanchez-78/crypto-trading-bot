"""Live-open pipeline for the P0.8+ strategies -- Evidence-First Strategy
Expansion v2, Gate G7 final wiring step.

Completes the work `_workspace/18_live_wiring_plan.md` scoped and
deliberately stopped short of ("the actual decision to wire a real
open_paper_position() call still needs... a dedicated review cycle before
flipping anything live"). That review cycle is this patch, going through
the full evidence-based-patch-orchestrator (trading-safety-agent,
reviewer-agent, test-regression-agent) before any deploy.

STRUCTURALLY BOUNDED, not unrestricted: this module does NOT flip
`evidence_only` on any strategy registration (that stays True -- see each
strategy_*.py's own docstring, §2.4). What it adds is call site #7 (per
docs/P0_7_P1_3_REPOSITORY_ARCHITECTURE.md §3's entry-path inventory) for
the ALREADY-EXISTING P0_ADMIT_EVIDENCE_COLLECTION admission path --
signal_router.py's own architecture (§2.4) explicitly allows a strategy
marked evidence_only=True to still be admitted into bounded evidence
collection (never strict_ev/scaled admission) once P0SegmentEVGate agrees
the symbol/regime segment is in-scope for it. This module is the caller
that finally acts on that existing, already-reviewed admission decision --
it does not create a new admission pathway, it activates one that was
already designed and tested but never had a caller.

Safety properties, all inherited rather than reimplemented:
  - Cost/edge gate: cost_model.evaluate_edge() (signal_router.py step 5-6)
  - P0 segment eligibility: P0SegmentEVGate, same class the legacy path
    already uses (signal_router.py step 7-8). 2026-08-17 correction
    (reviewer-agent finding C4 -- an earlier version of this docstring
    claimed BULL_TREND/BEAR_TREND were both in scope; verified against
    p0_segment_ev_gate.py, that is false): `is_quarantined_for_strict_ev`
    is checked BEFORE `EVIDENCE_COLLECTION_REGIMES` and unconditionally
    rejects (P0_REJECT_QUARANTINED, regardless of evidence-collection
    eligibility) when `regime in QUARANTINED_REGIMES = {"BEAR_TREND"}`
    ("paper trading is long-only" per that constant's own comment) or
    `symbol in QUARANTINED_SYMBOLS = {"BTCUSDT", "SOLUSDT"}`. Real scope:
    BULL_TREND only, and never BTCUSDT/SOLUSDT regardless of regime. This
    also means sideways_mean_reversion_v1 and volatility_breakout_v1
    candidates will typically evaluate admitted=False (neither strategy's
    core setup is BULL_TREND-only by design) until a SEPARATE, deliberate
    decision widens these shared, pre-existing constants -- which also
    affect the legacy signal path, so out of scope for this patch.
    Disclosed, not worked around, here.
  - Risk guard: p0_risk_guard_v1.py (signal_router.py step 9)
  - Position caps: paper_trade_executor._check_exploration_exposure_caps
    (max 1 open per symbol across ALL exploration buckets, max 2 per
    bucket, max 1 per symbol+bucket) -- applies automatically because
    every position this module opens sets extra["explore_bucket"]=BUCKET.
  - Cost-floor TP/SL clamp: paper_trade_executor's existing
    _min_valid_tp_bps() clamp on the extra["tp_from_executor"] path.
  - Real-price requirement: this module only opens a position when
    quote_source == "live" (see _resolve_best_bid_ask in the shadow
    evaluator), AND re-fetches that same live_quote_cache_v1 quote itself
    to book the fill (crossing the ask on a long, the bid on a short) --
    2026-08-17 fix (trading-safety-agent review): an earlier version of
    this module passed r.signal.reference_price (always the strategy's
    candle-close reference, even when quote_source=="live") as the open
    price, which technically satisfied open_paper_position()'s "must be a
    real traded price" requirement but silently ignored the live quote the
    "live" label promised, biasing evidence quality without any actual
    real-money risk. Fixed to actually use the live bid/ask; falls closed
    (skips, does not fall back to the candle close) if the quote happens to
    age out between evaluate_symbol()'s check and this call.

What is NOT wired by this module (disclosed gaps, not oversights):
  - dynamic_trend_exit_v1.py (P1.0's custom exit hierarchy) is still not
    called anywhere -- positions opened here exit through the SAME
    existing generic TP/SL/timeout exit machinery every other paper
    position uses, seeded with the strategy's own initial_stop_price/
    target_reference_price where available. Wiring P1.0's exit hierarchy
    itself is a separate, later phase.
  - No new bucket-specific dashboard visualization; positions are visible
    via the standard bucket/explore_bucket fields already surfaced.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import List, Optional, Sequence, Tuple

from src.services import candle_cache_v1
from src.services import live_quote_cache_v1
from src.services import p0_8_plus_shadow_evaluator as live_evaluator
from src.services.p0_8_plus_shadow_evaluator import (
    CandidateEvaluation,
    _env_symbols,
    ensure_registered,
    evaluate_symbol,
)

log = logging.getLogger(__name__)

# Distinct identifiers for this pipeline's positions in dashboards, segment
# stats, and the audit trail. NEVER reuse "PAPER_STARVATION_DISCOVERY" --
# that is the unrelated legacy starvation-exploration mechanism this same
# session spent multiple cycles getting right (_workspace/24, /27); mixing
# the two evidence streams would corrupt both.
PAPER_SOURCE = "p0_8_plus_evidence_collection"
BUCKET = "P0_8_PLUS_EVIDENCE_COLLECTION"


def _normalize_side(side: str) -> str:
    s = side.upper()
    if s == "LONG":
        return "BUY"
    if s == "SHORT":
        return "SELL"
    return s


def _map_to_legacy_signal(candidate: CandidateEvaluation, booked_price: float) -> Tuple[dict, dict]:
    """Map a CandidateEvaluation (StrategySignal + SignalEvaluation) into
    the (signal, extra) dict pair open_paper_position() expects. Explicit
    field-by-field mapping, not a **kwargs passthrough, so any future
    StrategySignal field addition is a conscious decision here (mirrors
    _try_discovery_admission's extraction discipline in
    realtime_decision_engine.py).

    `booked_price` is the ACTUAL live price the position will open at
    (ask/bid crossed from live_quote_cache_v1, resolved by the caller) --
    used to re-anchor the strategy's TP/SL geometry (reviewer-agent finding
    C3, _workspace/33): the strategy computed target_reference_price/
    initial_stop_price as absolute prices against its own candle-close
    reference_price, which is a DIFFERENT price than what actually gets
    booked once a live quote is available. Passing those absolute prices
    through unchanged would silently skew the strategy's intended
    risk:reward around whatever the entry/reference gap happens to be.
    Re-deriving the absolute-price *offset* (target/stop minus the
    strategy's own reference_price) and reapplying it to the booked price
    preserves the intended geometry.

    NOTE ON ATTRIBUTION (reviewer-agent finding C6, FIXED 2026-08-18,
    _workspace/38_admission_path_unification.md): open_paper_position()
    used to run its own internal P0.3B/P0.3C gate a second time on every
    P0.8+ position (a different, underscore-separated segment-key format,
    its own closed-trade history lookup) -- independent of, and redundant
    with, signal_router.py's already-applied decision. For a brand-new
    evidence-only strategy with no history under that legacy shape, this
    ALWAYS found reject_p0=True and rerouted, unconditionally overwriting
    signal["learning_source"]/["p0_gate_reason"]/["segment_key"] and
    extra["paper_source"] on the way to storage. This is now bypassed
    entirely for the "P0_8_PLUS_EVIDENCE_COLLECTION" bucket specifically
    (paper_trade_executor.py's own comment at that bypass explains the
    scoping) -- every field set below now survives onto the stored
    position unchanged, and this pipeline has a genuinely single central
    admission path, not two independently-decided ones. The legacy signal
    path (every other bucket) is completely unaffected."""
    sig = candidate.signal
    ev = candidate.evaluation
    side = _normalize_side(sig.side)

    signal_dict = {
        "symbol": candidate.symbol,
        "side": side,
        "action": side,
        "regime": candidate.regime,
        "confidence": sig.confidence,
        # P0.8+ signals are already admitted via signal_router.py's
        # purpose-built cost_model.evaluate_edge() + net-edge gate (bps
        # scale) before ever reaching here -- the legacy weak-EV floor
        # (_MIN_EV_THRESHOLD=0.01) was tuned for a different, fractional
        # "ev" concept computed elsewhere in this file. Converting
        # bps->fraction keeps this field honest for display without
        # re-deriving a second, competing edge estimate. BUCKET is
        # explicitly exempted from that floor in paper_trade_executor.py
        # (mirrors the existing PAPER_STARVATION_DISCOVERY exemption)
        # precisely because the floor's threshold assumes the other scale.
        # KNOWN CONSEQUENCE (reviewer-agent finding C7): at typical
        # net_expected_edge_bps (single/low-double-digit bps), this
        # fraction is always well under _calculate_dynamic_position_size's
        # 0.03 floor, so every P0.8+ evidence-collection position sizes at
        # the smallest 0.3x multiplier. Conservative, not unsafe, but
        # deliberate and disclosed here rather than an accidental side
        # effect of the unit conversion.
        "ev": max(0.0, ev.net_expected_edge_bps / 10000.0),
        "score": sig.confidence,
        "learning_source": sig.learning_source,
        "strict_ev": ev.p0_strict_ev,
        "readiness_eligible": ev.p0_readiness_eligible,
        "segment_key": ev.p0_segment_key,
        "p0_gate_reason": ev.decision_code,
        "trade_id": sig.signal_id,
    }

    extra = {
        "paper_source": PAPER_SOURCE,
        "explore_bucket": BUCKET,
        "training_bucket": BUCKET,
        "tp_sl_profile": sig.exit_profile,
        "admission_reason": ev.decision_code,
        "cost_edge_ok": True,
        "cost_edge_bypassed": False,
        "expected_move_pct": sig.gross_expected_move_bps / 10000.0,
        "expected_move_src": candidate.strategy_id,
        "strategy_id": candidate.strategy_id,
        "strategy_version": sig.strategy_version,
        "quote_source": candidate.quote_source,
    }
    # Only pass strategy-supplied TP/SL through when BOTH are present --
    # open_paper_position() only honors this pair when both keys exist
    # together (paper_trade_executor.py); a lone target with no stop (or
    # vice versa) falls back to the executor's own default geometry rather
    # than risk an incomplete override. Re-anchored to booked_price (see
    # docstring) rather than passed through as the strategy's raw absolute
    # prices.
    if sig.target_reference_price is not None:
        tp_offset = sig.target_reference_price - sig.reference_price
        sl_offset = sig.initial_stop_price - sig.reference_price
        extra["tp_from_executor"] = booked_price + tp_offset
        extra["sl_from_executor"] = booked_price + sl_offset

    return signal_dict, extra


def run_live_tick(
    symbols: Optional[Sequence[str]] = None,
    *,
    cache: Optional[candle_cache_v1.CandleCache] = None,
) -> List[dict]:
    """One live-open pass. Reuses evaluate_symbol() verbatim (the shadow
    evaluator's already-reviewed candle fetch / regime classify / candidate
    generation / router evaluation) -- the only new behavior here is: for
    each admitted CandidateEvaluation backed by a real (not synthetic)
    quote, call open_paper_position(). Everything upstream of that call is
    the identical function the pure-shadow path already uses and has been
    logging for days, so this can never silently diverge from what shadow
    evidence has already shown.

    Never raises -- one symbol's or one candidate's failure is logged and
    skipped, matching evaluate_symbol()'s own per-strategy exception
    discipline (§8.1 spirit)."""
    from src.services.paper_trade_executor import open_paper_position

    # 2026-08-17 (reviewer-agent finding C2): the shadow evaluator's own
    # run_shadow_tick() calls this before its loop (p0_8_plus_shadow_
    # evaluator.py:262) -- this function reads the same cache directly
    # (evaluate_symbol -> _resolve_best_bid_ask, and again below for the
    # booked price) and must not silently depend on the shadow thread
    # staying enabled to keep the subscription alive. Idempotent.
    live_quote_cache_v1.ensure_subscribed()

    syms = tuple(symbols) if symbols is not None else _env_symbols()
    ensure_registered(syms)
    opened: List[dict] = []
    for symbol in syms:
        try:
            results = evaluate_symbol(symbol, cache=cache)
        except Exception as exc:
            log.warning("[P0_8_PLUS_LIVE] evaluate_symbol failed for %s: %r", symbol, exc)
            continue
        for r in results:
            log.info(
                "[P0_8_PLUS_LIVE] %s %s %s regime=%s quote=%s admitted=%s code=%s net_edge=%.2fbps",
                r.symbol, r.strategy_id, r.side, r.regime, r.quote_source,
                r.evaluation.admitted, r.evaluation.decision_code, r.evaluation.net_expected_edge_bps,
            )
            if not r.evaluation.admitted:
                continue
            if r.quote_source != "live":
                # A synthetic candle-close spread is good enough for shadow
                # logging but not for committing paper capital -- see
                # module docstring's "Real-price requirement".
                log.info(
                    "[P0_8_PLUS_LIVE_SKIP] %s %s admitted but quote_source=synthetic -- "
                    "waiting for a real quote, not opening",
                    r.symbol, r.strategy_id,
                )
                continue
            # 2026-08-17 (trading-safety-agent review, _workspace/33): the
            # evaluated CandidateEvaluation only records that a live quote
            # WAS used for the cost gate (r.quote_source) -- it does not
            # carry the quote itself. r.signal.reference_price is always
            # the strategy's candle-close reference, even when
            # quote_source=="live", which would silently commit paper
            # capital at a stale/approximate price despite the "live" gate
            # above. Re-fetch the same live quote and cross it properly
            # (long crosses the ask, short crosses the bid -- same §15A.2
            # convention the shadow evaluator's synthetic fallback already
            # follows) so the price actually booked matches what the "live"
            # label promises.
            live_quote = live_quote_cache_v1.get_last_quote(r.symbol, max_age_s=live_evaluator.QUOTE_MAX_AGE_S)
            if live_quote is None:
                # Aged out between evaluate_symbol()'s check and here (race,
                # expected to be rare given the calls are back-to-back) --
                # fail closed rather than fall back to the candle close.
                log.info(
                    "[P0_8_PLUS_LIVE_SKIP] %s %s live quote aged out between evaluation and open -- not opening",
                    r.symbol, r.strategy_id,
                )
                continue
            price = live_quote.ask if _normalize_side(r.side) == "BUY" else live_quote.bid
            try:
                signal_dict, extra = _map_to_legacy_signal(r, price)
                result = open_paper_position(
                    signal_dict, price, time.time(),
                    reason="P0_8_PLUS_EVIDENCE_COLLECTION",
                    extra=extra,
                )
                log.warning(
                    "[P0_8_PLUS_LIVE_OPEN] %s %s strategy=%s status=%s reason=%s",
                    r.symbol, r.side, r.strategy_id,
                    result.get("status"), result.get("reason"),
                )
                if result.get("status") == "opened":
                    opened.append(result)
            except Exception as exc:
                log.warning(
                    "[P0_8_PLUS_LIVE] open_paper_position failed for %s/%s: %r",
                    symbol, r.strategy_id, exc,
                )
                continue
    # 2026-08-17 (found during the first post-enable monitoring cycle,
    # _workspace/33_p0_8_plus_live_wiring.md): the shadow evaluator's
    # run_shadow_tick() logs a "tick complete" summary even on 0 candidates
    # -- this function only logged per-candidate lines, so a tick with 0
    # candidates (the common case) produced NO log output at all. That made
    # "thread is alive and found nothing" indistinguishable from "thread
    # silently died" from journalctl alone -- exactly the observability gap
    # that let SKIP_SCORE_HARD's discovery bypass go unnoticed for 66+
    # hours earlier this session (_workspace/28). Added for the same reason
    # the shadow evaluator already has it: liveness must never depend on
    # something interesting having happened.
    log.info(
        "[P0_8_PLUS_LIVE] tick complete: %d opened across %d symbol(s)",
        len(opened), len(syms),
    )
    return opened


def start_live_pipeline_thread(
    interval_s: float = 60.0,
    symbols: Optional[Sequence[str]] = None,
) -> Optional[threading.Thread]:
    """Start a daemon background thread that calls run_live_tick() every
    `interval_s` seconds -- same pattern as
    p0_8_plus_shadow_evaluator.start_shadow_monitoring_thread().

    Gated by PAPER_P0_8_PLUS_LIVE_ENABLED (default 'false' -- unlike the
    shadow evaluator, this thread CAN open real paper positions, so it
    ships opt-in pending the full orchestrator review's verdict on the
    default, not opt-out). Set to 'true'/'1'/'yes'/'on' to enable via the
    systemd overlay once that review has run.

    Returns the Thread if started, or None if disabled.
    """
    enabled = os.getenv("PAPER_P0_8_PLUS_LIVE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        log.info("[P0_8_PLUS_LIVE] pipeline thread disabled (default) via PAPER_P0_8_PLUS_LIVE_ENABLED")
        return None

    def _loop() -> None:
        while True:
            try:
                run_live_tick(symbols=symbols)
            except Exception as exc:  # never let one bad tick kill the thread
                log.warning("[P0_8_PLUS_LIVE] tick failed: %r", exc)
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, name="p0-8-plus-live-pipeline", daemon=True)
    t.start()
    log.info(
        "[P0_8_PLUS_LIVE] pipeline thread started (interval=%.0fs, symbols=%s)",
        interval_s, list(symbols) if symbols is not None else list(_env_symbols()),
    )
    return t
