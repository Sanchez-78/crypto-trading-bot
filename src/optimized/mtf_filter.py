from __future__ import annotations


def mtf_score(
    data_1h: dict,
    data_15m: dict,
    data_5m: dict,
    direction: str,
) -> tuple[float, str]:
    """Multi-timeframe confluence score 0-10.

    Scoring breakdown:
      EMA alignment (3 pts) + ADX (1 pt) + RSI/MACD (1 pt) +
      EMA 15m (1 pt) + volume surge (1.5 pts) + no-exhaust (1.5 pts)

    Thresholds:
      ≥ 7.0 → ENTER 1.0×
      4-6   → ENTER 0.5×
      < 4   → SKIP

    Timeframe hierarchy (Elder ~5×): 1h → trend, 15m → confirmation, 5m → entry.
    Sources: freqtrade TrendRider 10k+ trades → 67.9% WR PF 2.12;
    MTF 45% → 58-70% WR (+15-25 pp).
    """
    try:
        import talib
    except ImportError:
        return 5.0, "talib_missing"

    c1h = data_1h["close"]
    is_long = direction.upper() == "LONG"

    ema50 = talib.EMA(c1h, 50)[-1]
    ema200 = talib.EMA(c1h, 200)[-1]
    adx = talib.ADX(data_1h["high"], data_1h["low"], c1h, 14)[-1]
    rsi1h = talib.RSI(c1h, 14)[-1]
    _, _, hist1h = talib.MACD(c1h)

    ema_ok = (ema50 > ema200) if is_long else (ema50 < ema200)
    if not ema_ok:
        return 0.0, "1H_EMA_WRONG_SIDE"
    if adx < 20:
        return 1.0, "1H_NO_TREND"

    score = 3.0  # EMA aligned
    score += 1.0 if adx > 25 else 0.5
    score += 1.0 if (rsi1h > 50 if is_long else rsi1h < 50) else 0
    score += 1.0 if (hist1h[-1] > 0 if is_long else hist1h[-1] < 0) else 0

    c15m = data_15m["close"]
    rsi15m = talib.RSI(c15m, 14)[-1]
    ema20 = talib.EMA(c15m, 20)[-1]
    ema50m = talib.EMA(c15m, 50)[-1]
    if is_long and rsi15m > 75:
        return score, "15M_EXHAUSTED"
    if not is_long and rsi15m < 25:
        return score, "15M_OVERSOLD"
    score += 1.0 if (ema20 > ema50m if is_long else ema20 < ema50m) else 0

    c5m = data_5m["close"]
    rsi5m = talib.RSI(c5m, 14)[-1]
    vol5m = data_5m.get("volume", [0])
    vol_avg = sum(list(vol5m)[-20:]) / 20 if len(vol5m) >= 20 else 0
    score += 1.5 if vol5m[-1] > vol_avg * 1.5 and vol_avg > 0 else 0
    score += 1.5 if (rsi5m < 80 if is_long else rsi5m > 20) else 0

    return score, f"MTF:{score:.1f}"


def mtf_size(score: float) -> float:
    """Convert MTF score to position size fraction."""
    return 1.0 if score >= 7.0 else 0.5 if score >= 4.0 else 0.0
