"""
order_book_depth.py — Shared L2 Order Book State (Phase 4 / Task 1)

Single source of truth for live Binance depth data. Used by both:
  • execution_engine.py  — wall_exit proactive close of open positions
  • signal_engine.py     — L2 gate at entry time (REJECTED_L2_WALL)

Exposes two families of checks:

  Current-price walls (execution path — reactive wall on existing positions)
    is_sell_wall(sym, current_price)  — large ask pressure above current price
    is_buy_wall(sym, current_price)   — large bid pressure below current price

  TP-approach walls (signal gate — prospective wall before entry)
    is_sell_wall_near_tp(sym, price, tp) — massive ask wall between price and TP
    is_buy_wall_near_tp(sym, price, tp)  — massive bid wall between price and TP

Design rationale:
  is_sell_wall / is_buy_wall: reactive trailing stops exit *after* price has
  already fallen.  A large sell wall sitting just above current price is a
  leading indicator — preemptive exit captures the mid-price before slippage.

  is_sell_wall_near_tp / is_buy_wall_near_tp: signal gate fires *before* entry
  when TP is reachable but a wall sits in the approach band.  The bot avoids
  entering trades that will hit the wall and timeout instead of reaching TP.

Parameters (tunable via module constants):
    SELL_WALL_RATIO    : ask_vol must be ≥ this multiple of bid_vol in band
    TP_WALL_RATIO      : stricter ratio for TP-approach check (default 5×)
    WALL_BAND_PCT      : scan band width relative to reference price (0.3%)
    TP_APPROACH_PCT    : only fire TP-wall check within this % of TP (0.2%)
    STALE_S            : depth snapshot older than this is ignored (seconds)
    MIN_PROFIT_TO_EXIT : minimum positive move before wall exit is allowed
"""

import time as _time
import threading as _threading

# ── Constants ─────────────────────────────────────────────────────────────────

SELL_WALL_RATIO    = 4.0    # ask_vol > 4× bid_vol → sell wall for BUY exits
BUY_WALL_RATIO     = 4.0    # bid_vol > 4× ask_vol → buy wall for SELL exits
WALL_BAND_PCT      = 0.003  # scan ±0.3% from current price
STALE_S            = 5.0    # ignore depth older than 5 s (stale WebSocket data)
MIN_PROFIT_TO_EXIT = 0.001  # only fire if unrealised gain ≥ 0.10%

# TP-approach wall detection (Phase 4 / signal gate)
TP_WALL_RATIO      = 5.0    # stricter: 5× avg level vol = TP wall
TP_APPROACH_PCT    = 0.002  # only fire check when within 0.2% of TP

# ── State ─────────────────────────────────────────────────────────────────────

# {sym: {"bids": [(price, qty), ...], "asks": [(price, qty), ...], "ts": float}}
_depth: dict = {}
_lock = _threading.Lock()


# ── Public API ─────────────────────────────────────────────────────────────────

def update_depth(sym: str, bids: list, asks: list) -> None:
    """Store a new depth snapshot for `sym`.

    Parameters
    ----------
    sym  : e.g. "BTCUSDT"
    bids : list of [price_str, qty_str] from Binance @depth20 message
    asks : list of [price_str, qty_str]
    """
    try:
        parsed_bids = [(float(p), float(q)) for p, q in bids if float(q) > 0]
        parsed_asks = [(float(p), float(q)) for p, q in asks if float(q) > 0]
    except (ValueError, TypeError):
        return

    with _lock:
        _depth[sym] = {
            "bids": sorted(parsed_bids, key=lambda x: -x[0]),  # descending: best bid first
            "asks": sorted(parsed_asks, key=lambda x:  x[0]),  # ascending:  best ask first
            "ts":   _time.time(),
        }


def is_sell_wall(sym: str, current_price: float,
                 band_pct: float = WALL_BAND_PCT,
                 ratio: float = SELL_WALL_RATIO) -> bool:
    """Return True when a large sell wall sits just above current_price.

    Scans the ask side in (current_price, current_price × (1 + band_pct)].
    A wall is detected when total ask volume in that band ≥ ratio × total
    bid volume in the symmetric band below current_price.

    Only returns True for positions that are already profitable (caller must
    check unrealised move > MIN_PROFIT_TO_EXIT before calling).

    Returns False if:
      - no depth data exists for sym
      - depth is stale (> STALE_S seconds old)
      - bid or ask volume in band is zero (avoids division edge cases)
    """
    snap = _get_snap(sym)
    if snap is None:
        return False

    upper = current_price * (1.0 + band_pct)
    lower = current_price * (1.0 - band_pct)

    ask_vol = sum(q for p, q in snap["asks"] if current_price < p <= upper)
    bid_vol = sum(q for p, q in snap["bids"] if lower <= p < current_price)

    if bid_vol <= 0 or ask_vol <= 0:
        return False
    return ask_vol >= ratio * bid_vol


def is_buy_wall(sym: str, current_price: float,
                band_pct: float = WALL_BAND_PCT,
                ratio: float = BUY_WALL_RATIO) -> bool:
    """Return True when a large buy wall sits just below current_price.

    Mirror of is_sell_wall for SELL positions: scans the bid side in
    [current_price × (1 - band_pct), current_price).  A wall fires when
    total bid volume ≥ ratio × ask volume in the symmetric band above.
    """
    snap = _get_snap(sym)
    if snap is None:
        return False

    upper = current_price * (1.0 + band_pct)
    lower = current_price * (1.0 - band_pct)

    bid_vol = sum(q for p, q in snap["bids"] if lower <= p < current_price)
    ask_vol = sum(q for p, q in snap["asks"] if current_price < p <= upper)

    if ask_vol <= 0 or bid_vol <= 0:
        return False
    return bid_vol >= ratio * ask_vol


def get_depth_snapshot(sym: str) -> dict | None:
    """Return raw depth snapshot for diagnostics / dashboard."""
    return _get_snap(sym)


# ── TP-approach wall detection (Phase 4 / signal gate) ───────────────────────

def is_sell_wall_near_tp(
    sym: str,
    current_price: float,
    tp_price: float,
    approach_pct: float = TP_APPROACH_PCT,
    ratio: float = TP_WALL_RATIO,
) -> bool:
    """
    True when a massive ask wall sits between current_price and tp_price.

    Fires only when current_price is within `approach_pct` of tp_price
    (i.e. position/entry is already "approaching" TP).

    Used by:
      execution_engine — wall_exit of open BUY position near TP
      signal_engine    — REJECTED_L2_WALL gate for BUY entry signals

    Parameters
    ----------
    sym           : symbol string ("BTCUSDT")
    current_price : current mid-price (entry price for signal gate)
    tp_price      : estimated take-profit price
    approach_pct  : only fire when (tp - price) / price ≤ this value
    ratio         : wall threshold — wall_vol ≥ ratio × avg_vol_per_level
    """
    approach = (tp_price - current_price) / max(current_price, 1e-9)
    if approach > approach_pct:
        return False   # not close enough to TP yet

    snap = _get_snap(sym)
    if snap is None:
        return False

    asks: list[tuple[float, float]] = snap["asks"]
    if not asks:
        return False

    upper    = tp_price * (1.0 + WALL_BAND_PCT)
    wall_vol = sum(q for p, q in asks if tp_price < p <= upper)
    avg_vol  = sum(q for _, q in asks) / len(asks)

    return avg_vol > 0 and wall_vol >= ratio * avg_vol


def is_buy_wall_near_tp(
    sym: str,
    current_price: float,
    tp_price: float,
    approach_pct: float = TP_APPROACH_PCT,
    ratio: float = TP_WALL_RATIO,
) -> bool:
    """
    Mirror of is_sell_wall_near_tp for SELL positions.
    tp_price is lower than current_price for SELL trades.

    Used by:
      execution_engine — wall_exit of open SELL position near TP
      signal_engine    — REJECTED_L2_WALL gate for SELL entry signals
    """
    approach = (current_price - tp_price) / max(tp_price, 1e-9)
    if approach > approach_pct:
        return False

    snap = _get_snap(sym)
    if snap is None:
        return False

    bids: list[tuple[float, float]] = snap["bids"]
    if not bids:
        return False

    lower    = tp_price * (1.0 - WALL_BAND_PCT)
    wall_vol = sum(q for p, q in bids if lower <= p < tp_price)
    avg_vol  = sum(q for _, q in bids) / len(bids)

    return avg_vol > 0 and wall_vol >= ratio * avg_vol


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_snap(sym: str) -> dict | None:
    with _lock:
        snap = _depth.get(sym)
    if snap is None:
        return None
    if _time.time() - snap["ts"] > STALE_S:
        return None
    return snap
