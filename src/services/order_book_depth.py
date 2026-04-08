"""
order_book_depth.py — per-symbol Level-2 order book state.

Receives depth snapshots pushed by market_stream.py (Binance @depth20@100ms
WebSocket stream) and exposes two proactive exit signals:

    is_sell_wall(sym, price) — massive ask pressure above a BUY position
    is_buy_wall(sym, price)  — massive bid pressure below a SELL position

Design rationale:
  Reactive trailing stops (Chandelier, adaptive_sl_tightening) exit *after* price
  has already fallen through a threshold.  A large sell wall sitting just above the
  current price is a leading indicator — price is statistically unlikely to break
  through it in the short window the bot holds positions (5–17 ticks @ 1 s/symbol).
  Exiting proactively before the wall captures the current mid-price rather than
  the post-wall bid, improving realised PnL on winning trades.

  The guard only fires when the position already has positive unrealised gain
  (move > MIN_PROFIT_TO_EXIT), so it never exits a losing trade on wall noise.

Parameters (tunable via module constants):
    SELL_WALL_RATIO : ask volume must be ≥ this multiple of bid volume in band
    WALL_BAND_PCT   : how far above/below current price to scan (default 0.3%)
    STALE_S         : depth snapshot older than this is ignored (seconds)
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


# ── Internal ──────────────────────────────────────────────────────────────────

def _get_snap(sym: str) -> dict | None:
    with _lock:
        snap = _depth.get(sym)
    if snap is None:
        return None
    if _time.time() - snap["ts"] > STALE_S:
        return None
    return snap
