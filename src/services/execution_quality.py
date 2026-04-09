"""
execution_quality.py — Execution Quality Layer (V10.11)

Computes a multiplicative exec_quality score [0.5, 1.0] from real market
microstructure conditions at the moment of signal evaluation.

Components
──────────
  spread_penalty  — bid-ask spread width (HARD SKIP if > 0.15%)
  slip_penalty    — expected fill cost (spread + ATR volatility)
  fill_penalty    — L1 order book pressure in trade direction
  latency_penalty — micro price jump since last tick

All effects are multiplicative penalties — exec_quality can only REDUCE size,
never increase it.

Single hard block: spread > 0.0015 (0.15%) — cost certain to exceed edge.

Integration
───────────
Called from trade_executor.handle_signal() AFTER all existing sizing multipliers
(policy_ev, auditor_factor, meta, correlation, risk_budget) and BEFORE exec_order.

    from src.services.execution_quality import exec_quality_score
    result = exec_quality_score(sym, action, entry, atr_pct, ob)
    if result["skip"]:
        return          # extreme spread — only hard block
    size *= result["exec_quality"]
"""

from __future__ import annotations

from typing import Any


# ── Thresholds ─────────────────────────────────────────────────────────────────

SPREAD_HARD_SKIP  = 0.0015   # > 0.15% bid-ask → skip entirely
SPREAD_SOFT_THR   = 0.0010   # > 0.10% → penalty 0.70, else 1.0
SPREAD_SOFT_PEN   = 0.70

LATENCY_THR       = 0.002    # micro-move > 0.2% → penalty 0.60
LATENCY_HARD_PEN  = 0.60

WALL_L2_PEN       = 0.70     # wall detected against trade direction

EXEC_QUALITY_MIN  = 0.50     # clamp floor


# ── Main function ──────────────────────────────────────────────────────────────

def exec_quality_score(
    sym:     str,
    action:  str,    # "BUY" | "SELL"
    entry:   float,
    atr_pct: float,
    ob:      Any,    # execution.OrderBook (synthetic fallback)
) -> dict[str, Any]:
    """
    Compute execution quality score for one signal.

    Returns
    -------
    dict with keys:
      skip          bool   True → hard block (extreme spread only)
      exec_quality  float  [0.5, 1.0] — multiply into size
      spread        float  raw bid-ask spread fraction
      slip          float  estimated slippage fraction
      fill          float  fill_penalty component
      lat           float  latency_penalty component
    """
    # ── 1. Spread ─────────────────────────────────────────────────────────────
    bid, ask = _get_bid_ask(sym, ob)
    mid      = (bid + ask) / 2.0
    spread   = (ask - bid) / max(mid, 1e-9)

    if spread > SPREAD_HARD_SKIP:
        return {
            "skip": True, "exec_quality": 0.0,
            "spread": spread, "slip": 0.0, "fill": 0.0, "lat": 0.0,
        }

    spread_penalty = SPREAD_SOFT_PEN if spread > SPREAD_SOFT_THR else 1.0

    # ── 2. Slippage estimate ───────────────────────────────────────────────────
    slippage    = spread * 0.5 + atr_pct * 0.3
    slip_penalty = max(0.5, 1.0 - slippage * 10.0)

    # ── 3. Fill probability (L1 order book pressure) ──────────────────────────
    bid_vol, ask_vol = _get_l1_volumes(sym, ob)
    fill_penalty     = _fill_penalty(action, bid_vol, ask_vol)

    # ── 4. Latency / micro-move ────────────────────────────────────────────────
    prev_price   = _get_prev_price(sym, entry)
    micro_move   = abs(entry - prev_price) / max(prev_price, 1e-9)
    lat_penalty  = LATENCY_HARD_PEN if micro_move > LATENCY_THR else 1.0

    # ── 5. Base exec_quality ──────────────────────────────────────────────────
    eq = spread_penalty * slip_penalty * fill_penalty * lat_penalty

    # ── 6. Optional L2 wall penalty ───────────────────────────────────────────
    if _wall_against(sym, action, entry):
        eq *= WALL_L2_PEN

    eq = max(EXEC_QUALITY_MIN, min(1.0, eq))

    return {
        "skip":         False,
        "exec_quality": eq,
        "spread":       spread,
        "slip":         slippage,
        "fill":         fill_penalty,
        "lat":          lat_penalty,
    }


# ── Internal helpers ───────────────────────────────────────────────────────────

def _get_bid_ask(sym: str, ob: Any) -> tuple[float, float]:
    """Return (bid, ask) — real L2 snapshot preferred, synthetic ob fallback."""
    try:
        from src.services.order_book_depth import get_depth_snapshot
        snap = get_depth_snapshot(sym)
        if snap and snap.get("bids") and snap.get("asks"):
            bid = snap["bids"][0][0]   # best bid
            ask = snap["asks"][0][0]   # best ask
            if bid > 0 and ask > bid:
                return bid, ask
    except Exception:
        pass
    # Fallback to synthetic OrderBook (ob.bid / ob.ask)
    try:
        return float(ob.bid), float(ob.ask)
    except Exception:
        return 0.0, 0.0


def _get_l1_volumes(sym: str, ob: Any) -> tuple[float, float]:
    """Return (bid_vol, ask_vol) at best level — real L2 preferred."""
    try:
        from src.services.order_book_depth import get_depth_snapshot
        snap = get_depth_snapshot(sym)
        if snap and snap.get("bids") and snap.get("asks"):
            bv = sum(q for _, q in snap["bids"][:5])   # top-5 bid depth
            av = sum(q for _, q in snap["asks"][:5])   # top-5 ask depth
            if bv > 0 or av > 0:
                return bv, av
    except Exception:
        pass
    # Fallback to OrderBook aggregates
    try:
        return float(ob.bid_vol), float(ob.ask_vol)
    except Exception:
        return 1.0, 1.0


def _fill_penalty(action: str, bid_vol: float, ask_vol: float) -> float:
    """
    Pressure ratio in trade direction.
    BUY  needs ask liquidity → measure bid vs ask (more bids = easier fill).
    SELL needs bid liquidity → measure ask vs bid.
    """
    eps = 1e-6
    if action == "BUY":
        pressure = bid_vol / (ask_vol + eps)
    else:
        pressure = ask_vol / (bid_vol + eps)

    if pressure > 1.5:
        return 1.00
    if pressure > 1.0:
        return 0.90
    return 0.75


def _get_prev_price(sym: str, current: float) -> float:
    """Return the previous tick price for the latency micro-move check."""
    try:
        from src.services.learning_event import _last_prices
        pair = _last_prices.get(sym)
        if pair and pair[1] and pair[1] > 0:
            return float(pair[1])
    except Exception:
        pass
    try:
        from src.services.signal_generator import prices as _sg_prices
        hist = _sg_prices.get(sym, [])
        if len(hist) >= 2:
            return float(hist[-2])
    except Exception:
        pass
    return current   # no prev data → micro_move = 0 → no penalty


def _wall_against(sym: str, action: str, price: float) -> bool:
    """
    True when an L2 liquidity wall is detected in the direction the trade
    must push through (sell wall for BUY, buy wall for SELL).
    Uses existing order_book_depth guards (same logic as trailing exit).
    """
    try:
        from src.services.order_book_depth import is_sell_wall, is_buy_wall
        if action == "BUY":
            return is_sell_wall(sym, price)
        else:
            return is_buy_wall(sym, price)
    except Exception:
        return False
