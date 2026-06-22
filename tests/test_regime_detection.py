"""
Unit tests for signal_generator._regime() classification.

Context (forensic evidence, 2026-06-11 / 2026-06-22 audit):
  - 6 SELL trades lost -48 bps avg while market rose +17 to +42 bps uniformly.
  - Regime was tagged BEAR_TREND during a rising-price reversal tail.
  - The SAME regime label had BUY trades at +88% WR — i.e. the direction logic
    is fine, but a STALE BEAR_TREND label (lagging DI/ADX from a prior
    downtrend) leaked into a sharp upside reversal and drove SELL entries.

Audit conclusion:
  The di_p > di_m comparison is NOT inverted (verified empirically on clean
  up/down trends). Root cause is regime LAG during sharp reversals. The fix
  adds a fast-EMA slope confirmation guard so a BEAR_TREND cannot be emitted
  while price is actually rising (and BULL_TREND cannot be emitted while
  price is actually falling).

These tests drive _regime() through synthetic price arrays that exercise the
underlying _adx()/_atr() indicators, covering all 5 regime branches, boundary
conditions, mixed signals, and the lag-reversal regression.
"""

from src.services.signal_generator import _adx, _atr, _regime


# ── Helpers ─────────────────────────────────────────────────────────────────

def _classify(series):
    """Run the full indicator pipeline exactly as production does."""
    adx, di_p, di_m = _adx(series)
    atr_v = _atr(series)
    return _regime(series, adx, di_p, di_m, atr_v)


def _linear(start, step, n=60):
    """Strictly linear price series (deterministic, no noise)."""
    return [start + step * i for i in range(n)]


# ── BULL_TREND branch ───────────────────────────────────────────────────────

def test_bull_trend_steady_uptrend():
    """Steady uptrend: high ADX, di_p > di_m, slope up -> BULL_TREND."""
    assert _classify(_linear(100.0, 0.5)) == "BULL_TREND"


def test_bull_trend_di_p_greater_than_di_m():
    """In an uptrend di_p must dominate di_m (sanity on the indicator)."""
    adx, di_p, di_m = _adx(_linear(100.0, 0.5))
    assert di_p > di_m
    assert adx > 25


def test_bull_trend_gentle_but_strong_uptrend():
    """A modest-slope but clean uptrend still classifies as BULL_TREND."""
    assert _classify(_linear(100.0, 0.2)) == "BULL_TREND"


# ── BEAR_TREND branch ───────────────────────────────────────────────────────

def test_bear_trend_steady_downtrend():
    """Steady downtrend: high ADX, di_m > di_p, slope down -> BEAR_TREND."""
    assert _classify(_linear(200.0, -0.5)) == "BEAR_TREND"


def test_bear_trend_di_m_greater_than_di_p():
    """In a downtrend di_m must dominate di_p (logic NOT inverted)."""
    adx, di_p, di_m = _adx(_linear(200.0, -0.5))
    assert di_m > di_p
    assert adx > 25


def test_bear_trend_gentle_but_strong_downtrend():
    assert _classify(_linear(200.0, -0.2)) == "BEAR_TREND"


# ── HIGH_VOL branch ─────────────────────────────────────────────────────────

def test_high_vol_large_swings():
    """Large alternating swings -> atr_pct > 0.012 -> HIGH_VOL."""
    # ~3% peak-to-peak oscillation around 100 => ATR pct well above 1.2%
    series = [100.0 + (3.0 if i % 2 else -3.0) for i in range(60)]
    assert _classify(series) == "HIGH_VOL"


def test_high_vol_priority_over_trend():
    """Mixed signal: strong uptrend with huge volatility must prioritise HIGH_VOL.

    HIGH_VOL is the first branch in _regime(); even when ADX is high and
    di_p > di_m, an atr_pct above the 0.012 threshold wins.
    """
    # Strong upward drift PLUS large oscillation -> trend present but vol dominates
    series = [100.0 + i * 0.5 + (4.0 if i % 2 else -4.0) for i in range(60)]
    adx, di_p, di_m = _adx(series)
    atr_v = _atr(series)
    assert atr_v / series[-1] > 0.012          # vol gate is triggered
    assert _regime(series, adx, di_p, di_m, atr_v) == "HIGH_VOL"


# ── QUIET_RANGE branch ──────────────────────────────────────────────────────

def test_quiet_range_flat_market():
    """Dead-flat market: low ADX, narrow bands -> QUIET_RANGE."""
    series = [100.0 + (0.001 if i % 2 else -0.001) for i in range(60)]
    assert _classify(series) == "QUIET_RANGE"


def test_quiet_range_micro_oscillation():
    """Imperceptible symmetric oscillation, no drift -> QUIET_RANGE (adx<20)."""
    series = [100.0 + (0.0005 if i % 2 else -0.0005) for i in range(60)]
    assert _classify(series) == "QUIET_RANGE"


# ── RANGING branch ──────────────────────────────────────────────────────────

def test_ranging_moderate_chop_wide_bands():
    """Moderate non-trending chop with wide bands but sub-HIGH_VOL atr -> RANGING.

    Oscillation (~0.3 amplitude => atr_pct ~0.6%, below the 1.2% HIGH_VOL gate)
    with no directional trend (low ADX) and bands too wide for QUIET_RANGE.
    """
    series = [100.0 + (0.3 if i % 2 else -0.3) for i in range(60)]
    r = _classify(series)
    # Not a trend, not high-vol
    assert r not in ("BULL_TREND", "BEAR_TREND", "HIGH_VOL")
    assert r == "RANGING"


def test_chop_above_vol_threshold_is_high_vol():
    """Large symmetric chop (atr_pct > 1.2%) is correctly HIGH_VOL, not a trend."""
    series = [100.0 + (0.8 if i % 2 else -0.8) for i in range(60)]
    r = _classify(series)
    assert r == "HIGH_VOL"
    assert r not in ("BULL_TREND", "BEAR_TREND")


# ── Boundary conditions ─────────────────────────────────────────────────────

def test_boundary_adx_exactly_25_not_trend():
    """adx == 25.0 is NOT > 25, so the trend branches must not fire."""
    # Synthesise inputs directly at the boundary on a flat series.
    flat = [100.0] * 60
    atr_v = _atr(flat)
    # adx exactly at the boundary, di_p > di_m, slope flat
    assert _regime(flat, 25.0, 60.0, 40.0, atr_v) != "BULL_TREND"


def test_boundary_adx_just_above_25_is_trend():
    """adx slightly above 25 with di_p > di_m and rising slope -> BULL_TREND."""
    up = _linear(100.0, 0.5)
    atr_v = _atr(up)
    assert _regime(up, 25.01, 60.0, 40.0, atr_v) == "BULL_TREND"


def test_boundary_atr_pct_just_above_threshold_is_high_vol():
    """atr_pct just over 0.012 -> HIGH_VOL regardless of trend inputs."""
    series = _linear(100.0, 0.5)
    curr = series[-1]
    atr_over = 0.0121 * curr  # atr_pct = 0.0121 > 0.012
    assert _regime(series, 90.0, 99.0, 1.0, atr_over) == "HIGH_VOL"


def test_boundary_atr_pct_just_below_threshold_not_high_vol():
    """atr_pct just under 0.012 must NOT be HIGH_VOL."""
    series = _linear(100.0, 0.5)
    curr = series[-1]
    atr_under = 0.0119 * curr  # atr_pct = 0.0119 < 0.012
    assert _regime(series, 90.0, 99.0, 1.0, atr_under) != "HIGH_VOL"


def test_boundary_adx_20_quiet_range_edge():
    """adx == 20 is NOT < 20, so QUIET_RANGE branch must not fire on adx=20."""
    flat = [100.0] * 60
    atr_v = _atr(flat)
    # adx exactly 20, narrow bands -> falls through to RANGING (adx<20 is False)
    assert _regime(flat, 20.0, 50.0, 50.0, atr_v) == "RANGING"


# ── Lag-reversal regression (the forensic root cause) ───────────────────────

def test_no_stale_bear_trend_during_upside_reversal():
    """REGRESSION: sharp upside reversal must NOT be labelled BEAR_TREND.

    Forensic case: price fell, then reversed sharply upward. The trailing DI/ADX
    still reflected the prior downtrend (di_m high) for several ticks. Without the
    slope guard, _regime() emitted BEAR_TREND while price was rising, driving the
    6 losing SELL trades. The fast-EMA slope guard must block that.
    """
    downleg = [100.0 - 0.5 * i for i in range(45)]        # falling
    upleg = [downleg[-1] + 1.2 * (i + 1) for i in range(15)]  # sharp reversal up
    series = downleg + upleg
    assert _classify(series) != "BEAR_TREND"


def test_no_stale_bull_trend_during_downside_reversal():
    """REGRESSION (mirror): sharp downside reversal must NOT stay BULL_TREND."""
    upleg = [100.0 + 0.5 * i for i in range(45)]          # rising
    downleg = [upleg[-1] - 1.2 * (i + 1) for i in range(15)]  # sharp reversal down
    series = upleg + downleg
    assert _classify(series) != "BULL_TREND"


def test_slope_guard_preserves_clean_trends():
    """The slope guard must NOT break correctly-trending markets."""
    assert _classify(_linear(100.0, 0.5)) == "BULL_TREND"
    assert _classify(_linear(200.0, -0.5)) == "BEAR_TREND"


# ── Indicator-level sanity (data source not inverted) ───────────────────────

def test_adx_returns_neutral_on_short_series():
    """Short series returns the documented neutral defaults (20.0, 50, 50)."""
    adx, di_p, di_m = _adx([100.0, 100.1, 100.2])
    assert (adx, di_p, di_m) == (20.0, 50.0, 50.0)


def test_atr_positive_on_moving_series():
    """ATR is strictly positive when price moves."""
    assert _atr(_linear(100.0, 0.5)) > 0
