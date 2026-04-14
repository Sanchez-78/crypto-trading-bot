from __future__ import annotations

# Asset base parameters: [sl_mult, tp_mult, atr_period]
# Sources: LuxAlgo 2× ATR stop → -32% max drawdown; Bialkowski (2023) 147 cryptos.
# Anti-hunt buffer: +10% ATR on SL. Breakeven at 1.5× SL. Chandelier trail 3.5× ATR.
ASSET_BASE: dict[str, dict] = {
    "BTC":     {"sl": 2.0, "tp": 3.0, "period": 14},
    "ETH":     {"sl": 2.2, "tp": 3.2, "period": 14},
    "SOL":     {"sl": 2.7, "tp": 3.7, "period": 10},
    "DEFAULT": {"sl": 3.0, "tp": 4.0, "period": 10},
}

# ────────────────────────────────────────────────────────────────────────────
# PATCH 1: TP/SL Runtime Fix — Regime-aware adaptive targets
# ────────────────────────────────────────────────────────────────────────────
def compute_tp_sl(atr, regime):
    """PATCH 1: Quick regime-specific TP/SL multipliers for runtime deployment.
    
    Replaces complex asset_base logic with aggressive, fast-exit targets.
    Trending: wide TP (let winners run), tight SL
    Ranging: balanced TP/SL
    Quiet: tight everything (low ATR, consolidation)
    
    Returns: (tp_multiplier, sl_multiplier)  — multiply with ATR to get distances
    """
    if regime in ["BULL_TREND", "BEAR_TREND"]:
        return 0.6 * atr, 0.4 * atr
    if regime == "RANGING":
        return 0.5 * atr, 0.4 * atr
    if regime == "QUIET_RANGE":
        return 0.4 * atr, 0.35 * atr
    return 0.5 * atr, 0.4 * atr

# Regime ATR-ratio → SL multiplier adjustment
# <0.70 → 0.75×  |  0.70-1.20 → 1.0×  |  1.20-1.50 → 1.25×  |  >1.50 → 1.50×


def get_asset_key(symbol: str) -> str:
    for k in ASSET_BASE:
        if k != "DEFAULT" and symbol.upper().startswith(k):
            return k
    return "DEFAULT"


def calculate_sl_tp(
    direction: str,
    entry: float,
    atr: float,
    atr_ratio: float = 1.0,
    symbol: str = "",
) -> dict:
    """Compute ATR-dynamic SL/TP with per-asset and regime adjustments.

    Returns dict with keys: sl, tp, breakeven_trigger, rr_ratio, sl_dist_pct.
    """
    b = ASSET_BASE[get_asset_key(symbol)]
    adj = (
        1.50 if atr_ratio > 1.50
        else 1.25 if atr_ratio > 1.20
        else 0.75 if atr_ratio < 0.70
        else 1.00
    )
    sl_dist = atr * b["sl"] * adj * 1.10  # +10% anti-hunt buffer
    tp_dist = atr * b["tp"] * adj

    if direction.upper() == "LONG":
        sl = entry - sl_dist
        tp = entry + tp_dist
        be = entry + sl_dist * 1.5
    else:
        sl = entry + sl_dist
        tp = entry - tp_dist
        be = entry - sl_dist * 1.5

    return {
        "sl": round(sl, 8),
        "tp": round(tp, 8),
        "breakeven_trigger": round(be, 8),
        "rr_ratio": round(tp_dist / sl_dist, 2),
        "sl_dist_pct": round(sl_dist / entry * 100, 4),
    }
