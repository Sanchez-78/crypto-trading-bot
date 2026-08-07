"""Phase P0.9 -- order-flow imbalance and microprice (Evidence-First Strategy
Expansion v2, §11).

Diagnostic feature set + confirmation/conflict filter for trend signals
(§11's own framing: "Initially implement this as: 1. A diagnostic feature
set. 2. A confirmation or conflict filter... 3. An A/B evidence mechanism.
Do not initially create an independent high-frequency OFI trading strategy.").

No existing top-of-book-imbalance/microprice/signed-trade-delta
implementation was found in Gate G0's reconnaissance of
src/services/order_book_depth.py (which handles wall detection, a different
concern) -- this module is new, not a duplicate of anything.

This module never opens a position and is never itself a StrategySignal
source; P0.9's shadow-counterfactual pattern (§11.7 Pattern A) records
whether OFI *would have* confirmed or conflicted with an already-admitted
trend candidate, as a diagnostic annotation, not a second trade.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Sequence

_EPS = 1e-9

# Reason codes (§11.8) -- stable, machine-readable.
FLOW_CONFIRM_BULLISH = "FLOW_CONFIRM_BULLISH"
FLOW_CONFIRM_BEARISH = "FLOW_CONFIRM_BEARISH"
FLOW_NEUTRAL = "FLOW_NEUTRAL"
FLOW_CONFLICT_LONG = "FLOW_CONFLICT_LONG"
FLOW_CONFLICT_SHORT = "FLOW_CONFLICT_SHORT"
FLOW_STALE = "FLOW_STALE"
FLOW_WARMUP = "FLOW_WARMUP"
FLOW_INSUFFICIENT_TRADES = "FLOW_INSUFFICIENT_TRADES"
FLOW_BOOK_INVALID = "FLOW_BOOK_INVALID"
FLOW_SPREAD_EXPANSION = "FLOW_SPREAD_EXPANSION"
FLOW_LARGE_TRADE_CONFLICT = "FLOW_LARGE_TRADE_CONFLICT"

# Configuration-shaped constants (§11.6: "Thresholds must be configuration
# driven... use conservative defaults and retain raw continuous values" --
# the raw continuous values are always returned alongside the pass/fail
# verdict, per §11.6's "Do not make the evidence schema store only
# pass/fail").
BULLISH_MICROPRICE_OFFSET_BPS = 0.5
BEARISH_MICROPRICE_OFFSET_BPS = -0.5
BULLISH_IMBALANCE_THRESHOLD = 0.10
BEARISH_IMBALANCE_THRESHOLD = -0.10
MIN_TRADES_FOR_FLOW = 5
LARGE_TRADE_NOTIONAL_MULTIPLE = 5.0  # vs average trade size in the window
MAX_SPREAD_BPS_FOR_FLOW = 20.0
STALE_BOOK_AGE_MS = 3_000


def top_of_book_imbalance(bid_qty: float, ask_qty: float) -> Optional[float]:
    """§11.1. Returns None (invalid) rather than a fabricated 0.0 when the
    denominator is degenerate -- distinguishes "no signal" from "neutral
    signal", which §11.6 requires evidence to preserve."""
    if bid_qty < 0 or ask_qty < 0:
        raise ValueError(f"quantities must be non-negative: bid_qty={bid_qty} ask_qty={ask_qty}")
    denom = bid_qty + ask_qty
    if denom <= _EPS:
        return None
    return (bid_qty - ask_qty) / denom


def microprice(bid_price: float, ask_price: float, bid_qty: float, ask_qty: float) -> float:
    """§11.2."""
    if bid_price <= 0 or ask_price <= 0 or ask_price < bid_price:
        raise ValueError(f"invalid book: bid={bid_price} ask={ask_price}")
    if bid_qty < 0 or ask_qty < 0:
        raise ValueError("quantities must be non-negative")
    denom = bid_qty + ask_qty
    if denom <= _EPS:
        return (bid_price + ask_price) / 2.0  # falls back to plain mid, documented
    return (ask_price * bid_qty + bid_price * ask_qty) / denom


def microprice_offset_bps(bid_price: float, ask_price: float, bid_qty: float, ask_qty: float) -> float:
    """§11.2."""
    mp = microprice(bid_price, ask_price, bid_qty, ask_qty)
    mid = (bid_price + ask_price) / 2.0
    if mid <= 0:
        raise ValueError("non-positive mid price")
    return (mp - mid) / mid * 10_000.0


@dataclass(frozen=True)
class TradeEvent:
    """Normalized aggTrade-equivalent event (§8.2's sign convention reused,
    not reinvented: signed_qty = quantity if not buyer_is_maker else
    -quantity)."""

    event_time_ms: int
    price: float
    quantity: float
    buyer_is_maker: bool

    @property
    def signed_quantity(self) -> float:
        return self.quantity if not self.buyer_is_maker else -self.quantity

    @property
    def signed_notional(self) -> float:
        return self.price * self.signed_quantity

    @property
    def notional(self) -> float:
        return self.price * self.quantity


@dataclass(frozen=True)
class FlowWindowStats:
    """§11.3 -- aggregate signed-flow statistics for one rolling window."""

    window_seconds: float
    signed_notional_delta: float
    absolute_notional: float
    buy_aggressor_notional: float
    sell_aggressor_notional: float
    aggressor_buy_ratio: Optional[float]
    trade_count: int
    average_trade_size: float
    large_trade_signed_delta: float


class RollingTradeWindow:
    """§8.4 bounded rolling window -- a deque pruned by event time, not an
    unbounded list. Feeds FlowWindowStats for one configured window length."""

    def __init__(self, window_seconds: float) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.window_seconds = window_seconds
        self._events: Deque[TradeEvent] = deque()

    def add(self, event: TradeEvent) -> None:
        self._events.append(event)

    def prune(self, now_ms: int) -> None:
        cutoff = now_ms - int(self.window_seconds * 1000)
        while self._events and self._events[0].event_time_ms < cutoff:
            self._events.popleft()

    def stats(self, now_ms: int, large_trade_notional_threshold: Optional[float] = None) -> FlowWindowStats:
        self.prune(now_ms)
        events = list(self._events)
        n = len(events)
        if n == 0:
            return FlowWindowStats(
                window_seconds=self.window_seconds, signed_notional_delta=0.0,
                absolute_notional=0.0, buy_aggressor_notional=0.0,
                sell_aggressor_notional=0.0, aggressor_buy_ratio=None,
                trade_count=0, average_trade_size=0.0, large_trade_signed_delta=0.0,
            )
        signed_notional = sum(e.signed_notional for e in events)
        absolute_notional = sum(e.notional for e in events)
        buy_notional = sum(e.notional for e in events if e.signed_quantity > 0)
        sell_notional = sum(e.notional for e in events if e.signed_quantity < 0)
        buy_sell_total = buy_notional + sell_notional
        ratio = (buy_notional / buy_sell_total) if buy_sell_total > _EPS else None
        avg_size = absolute_notional / n

        threshold = large_trade_notional_threshold
        if threshold is None:
            threshold = avg_size * LARGE_TRADE_NOTIONAL_MULTIPLE
        large_delta = sum(e.signed_notional for e in events if e.notional >= threshold)

        return FlowWindowStats(
            window_seconds=self.window_seconds, signed_notional_delta=signed_notional,
            absolute_notional=absolute_notional, buy_aggressor_notional=buy_notional,
            sell_aggressor_notional=sell_notional, aggressor_buy_ratio=ratio,
            trade_count=n, average_trade_size=avg_size, large_trade_signed_delta=large_delta,
        )


def persistence_fraction(window_stats_sequence: Sequence[FlowWindowStats], *, bullish: bool) -> float:
    """§11.4 -- fraction of the given (already time-ordered, non-overlapping
    or overlapping-by-design -- caller's choice) sub-windows whose signed
    delta agrees with the requested direction. One isolated tick must not
    decide a trade (§11.4); this is the mechanism that enforces that by
    construction -- callers should feed multiple sub-windows, not one."""
    if not window_stats_sequence:
        return 0.0
    agree = 0
    counted = 0
    for w in window_stats_sequence:
        if w.trade_count == 0:
            continue
        counted += 1
        if bullish and w.signed_notional_delta > 0:
            agree += 1
        elif not bullish and w.signed_notional_delta < 0:
            agree += 1
    return agree / counted if counted else 0.0


@dataclass(frozen=True)
class FlowEvaluation:
    """Full diagnostic evaluation -- raw continuous values ALWAYS included
    alongside the reason code (§11.6: never pass/fail-only)."""

    reason_code: str
    microprice_offset_bps: Optional[float]
    top_of_book_imbalance: Optional[float]
    signed_notional_delta_short: Optional[float]
    signed_notional_delta_medium: Optional[float]
    persistence_fraction_short: float
    aggressor_buy_ratio: Optional[float]
    large_trade_conflict: bool


def evaluate_flow_for_side(
    *,
    side: str,
    best_bid: float,
    best_ask: float,
    bid_qty: float,
    ask_qty: float,
    book_age_ms: float,
    short_window_stats: FlowWindowStats,
    medium_window_stats: FlowWindowStats,
    persistence_windows: Sequence[FlowWindowStats],
    spread_bps: float,
) -> FlowEvaluation:
    """§11.5 conflict/confirmation logic + §11.8 reason codes.

    This function NEVER admits or rejects a trade -- it returns a diagnostic
    verdict for the central router/strategy glue to log or (later, per
    §11.7) attach as a shadow counterfactual. It has no P0/admission
    authority of its own (mirrors §10.9's "no promotion logic in the
    strategy" discipline, extended to this diagnostic module).
    """
    side_u = str(side or "").upper()
    if side_u not in ("BUY", "SELL", "LONG", "SHORT"):
        raise ValueError(f"unknown side: {side!r}")
    is_long = side_u in ("BUY", "LONG")

    if book_age_ms > STALE_BOOK_AGE_MS:
        return FlowEvaluation(FLOW_STALE, None, None, None, None, 0.0, None, False)

    if spread_bps > MAX_SPREAD_BPS_FOR_FLOW:
        return FlowEvaluation(FLOW_SPREAD_EXPANSION, None, None, None, None, 0.0, None, False)

    try:
        imb = top_of_book_imbalance(bid_qty, ask_qty)
        offset = microprice_offset_bps(best_bid, best_ask, bid_qty, ask_qty)
    except ValueError:
        return FlowEvaluation(FLOW_BOOK_INVALID, None, None, None, None, 0.0, None, False)

    if short_window_stats.trade_count < MIN_TRADES_FOR_FLOW:
        return FlowEvaluation(
            FLOW_INSUFFICIENT_TRADES, offset, imb,
            short_window_stats.signed_notional_delta, medium_window_stats.signed_notional_delta,
            0.0, short_window_stats.aggressor_buy_ratio, False,
        )

    persistence = persistence_fraction(persistence_windows, bullish=is_long)
    large_trade_conflict = (
        (is_long and short_window_stats.large_trade_signed_delta < 0)
        or (not is_long and short_window_stats.large_trade_signed_delta > 0)
    )

    bullish_confirm = (
        (offset is not None and offset > BULLISH_MICROPRICE_OFFSET_BPS)
        and (imb is not None and imb > BULLISH_IMBALANCE_THRESHOLD)
        and short_window_stats.signed_notional_delta > 0
        and medium_window_stats.signed_notional_delta > 0
    )
    bearish_confirm = (
        (offset is not None and offset < BEARISH_MICROPRICE_OFFSET_BPS)
        and (imb is not None and imb < BEARISH_IMBALANCE_THRESHOLD)
        and short_window_stats.signed_notional_delta < 0
        and medium_window_stats.signed_notional_delta < 0
    )

    if large_trade_conflict:
        code = FLOW_LARGE_TRADE_CONFLICT
    elif is_long and bearish_confirm:
        code = FLOW_CONFLICT_LONG
    elif not is_long and bullish_confirm:
        code = FLOW_CONFLICT_SHORT
    elif is_long and bullish_confirm:
        code = FLOW_CONFIRM_BULLISH
    elif not is_long and bearish_confirm:
        code = FLOW_CONFIRM_BEARISH
    else:
        code = FLOW_NEUTRAL

    return FlowEvaluation(
        reason_code=code,
        microprice_offset_bps=offset,
        top_of_book_imbalance=imb,
        signed_notional_delta_short=short_window_stats.signed_notional_delta,
        signed_notional_delta_medium=medium_window_stats.signed_notional_delta,
        persistence_fraction_short=persistence,
        aggressor_buy_ratio=short_window_stats.aggressor_buy_ratio,
        large_trade_conflict=large_trade_conflict,
    )


def shadow_counterfactual(evaluation: FlowEvaluation, side: str) -> bool:
    """§11.7 Pattern A -- shadow counterfactual: "would the OFI filter have
    admitted this candidate?" Diagnostic only -- the caller must NOT open a
    second position based on this; it is recorded alongside the canonically
    admitted trade for later A/B evidence comparison (§11.7, §16.5's
    decision-counterfactual vs fill-counterfactual distinction -- this
    function only ever answers the decision-counterfactual question)."""
    side_u = str(side or "").upper()
    is_long = side_u in ("BUY", "LONG")
    if is_long:
        return evaluation.reason_code == FLOW_CONFIRM_BULLISH
    return evaluation.reason_code == FLOW_CONFIRM_BEARISH
