"""
Trade executor with ATR-based TP/SL and trailing stop.

Risk management:
  TP    = 1.2× ATR   minimum 0.30% of entry price
  SL    = 1.0× ATR   minimum 0.25% of entry price
  Trail = 0.5× SL    trailing offset once in profit
  Timeout = 60 ticks (~6 min at 2s/tick × 3 symbols)

Position sizing:
  size = base × clamp(ev×6, 0.5, 3.0) × auditor_factor (floor 0.7)
  Strong edge: ev > threshold×1.5 → size ×1.5
  ≥ 20 trades: base 5%;  < 20 trades: base 2.5%

Calibration feedback:
  After every close → calibrator.update(confidence, WIN/LOSS)
  Enables empirical WR mapping per confidence bucket.

Firebase batch flush: every 20 trades OR every 5 minutes.
"""

from src.core.event_bus_v2        import get_event_bus
from src.core.event_bus           import subscribe_once
from src.services.learning_event  import update_metrics
from src.services.firebase_client import save_batch
from src.services.execution       import (
    exec_order, valid, ob_adjust, cost_guard, pre_cost,
    ev_adjust, fill_rate, final_size, entry_filter,
    rotate_capital, update_returns, update_equity, record_trade_close,
    bayes_update, bandit_update, OrderBook,
    bootstrap_mode, ws_threshold, cost_guard_bootstrap, size_floor,
    failure_control, epsilon, final_size_meta,
    is_bootstrap, net_edge, returns_hist)
import math
import os
import logging
import random
import time
import threading
from src.core.guard import guard, FailureLevel
from src.services.exit_attribution import (
    build_exit_ctx, update_exit_attribution,
    render_exit_attribution_summary, EXIT_TYPES
)
from src.services.exit_pnl import canonical_close_pnl

# V10.13u+20: Paper trading mode integration
try:
    from src.core.runtime_mode import is_paper_mode, live_trading_allowed
except ImportError:
    def is_paper_mode():
        return False
    def live_trading_allowed():
        return False

try:
    from src.services.paper_trade_executor import (
        open_paper_position, update_paper_positions, close_paper_position
    )
except ImportError:
    def open_paper_position(*args, **kwargs):
        return {"status": "error", "reason": "paper_trade_executor not available"}
    def update_paper_positions(*args, **kwargs):
        return []
    def close_paper_position(*args, **kwargs):
        return None

try:
    from src.services.learning_instrumentation import (
        increment_trades_closed, increment_lm_update_called, increment_lm_update_success
    )
except (ImportError, Exception) as e:
    # Log the actual error for debugging
    import traceback
    print(f"[IMPORT_ERROR] Failed to import learning_instrumentation: {type(e).__name__}: {e}")
    print(f"[TRACEBACK]\n{traceback.format_exc()}")
    # Fallback if instrumentation module not available
    increment_trades_closed = lambda: None
    increment_lm_update_called = lambda: None
    increment_lm_update_success = lambda: None

log = logging.getLogger(__name__)

BATCH             = []
_positions        = {}
_positions_lock   = threading.RLock()   # guards _positions and _regime_exposure
_last_flush       = [0.0]
_regime_exposure  = {}   # regime -> count of open positions
_pending_open     = []   # signals queued after replace_if_better triggers

MAX_POSITIONS     = 3    # max concurrent open positions (raised for bootstrap learning speed)
MAX_SAME_DIR      = 2    # max positions in same direction — 1→2: in BULL_TREND all symbols
                          # generate BUY, old limit=1 blocked 2/3 signals every tick, cutting
                          # learning rate by 67%; raise to 2 for faster data accumulation
MAX_REGIME_PCT    = 0.70 # block if one regime holds > 70% of open positions
_TOTAL_CAPITAL    = 1.0  # normalised capital (position sizes are fractions)
_MAX_CAP_USED     = 0.70 # don't deploy more than 70% of capital
_TARGET_VOL       = 0.02 # 2% target realised volatility for vol-adjusted sizing
_REPLACE_MARGIN   = 1.10 # new signal must be 10% better to replace weakest
_REPLACE_COOLDOWN = 300  # seconds between replacements of the same symbol
_MAX_TOTAL_RISK   = 0.05 # total portfolio risk cap (sum of size*sl_pct)
_SPREAD_PCT       = 0.001 # estimated bid-ask spread (0.10%)
_last_replaced    = {}   # symbol -> timestamp of last replacement
_last_replace_ts  = 0.0  # V10.4b: global cooldown — no replacement within 15 s of the last one
_pf_tick_counter  = [0]  # V10.13: global tick counter for portfolio_pnl sampling rate
_meta_ema   = {"lm_health": None, "sharpe": None, "drawdown": None}  # V10.6b: smoothed inputs
_meta_state = {                                                        # V10.6b: adaptive control
    "mode":              "neutral",
    "last_update":       0.0,
    "replace_threshold": 0.05,   # default; updated by update_meta_mode()
    "pyramid_trigger":   0.004,  # default; updated by update_meta_mode()
    "reduce_threshold":  -0.003, # default; updated by update_meta_mode()
}

# V10.12d: Unblock mode rate limiting
_UNBLOCK_TRADES_MAX_HOUR = 6    # max 6 unblock trades per hour
_UNBLOCK_POSITIONS_MAX   = 2    # max 2 concurrent unblock positions
_unblock_trades_hour = []       # list of timestamps of unblock trades in last 60 min

FEE_RT      = 0.0015    # 0.15% round-trip (Binance taker 0.075%×2)
MIN_TP_PCT  = 0.008     # 0.80% — giving trades room to hit higher RRs
MIN_SL_PCT  = 0.004     # 0.40% min SL — double the old size to survive spread + fee + noise
FLUSH_EVERY              = 15   # lowered 60→15s: with 60s window up to 14 trades
                                 # were lost on Railway restart (BATCH not flushed
                                 # before process kill). 15s → max ~3-4 trades lost.
MIN_TRADES_PER_100_TICKS = 5     # force-trade threshold: if fewer → bypass sigmoid gate
MIN_EDGE_PCT             = 0.0003 # 0.03% min TP/SL distance (log: avg ATR-based TP=0.038%,
                                  # old 0.20% blocked 336/346 signals — 97% kill rate)
_tick_counter   = [0]            # global price-tick counter (incremented in on_price)
_trades_at_tick = []             # tick values when positions were opened (rate tracking)

# V10.13u+11: Close lock + TTL recovery — prevent stuck locks and duplicate closes
_CLOSING_POSITIONS: dict = {}    # key -> {"ts": float, "symbol": str, "reason": str, "attempts": int, "last_log": float}
_RECENTLY_CLOSED: dict = {}      # key -> close timestamp (prevents immediate re-close)
_STALE_CLOSE_COUNTS: dict = {}   # key -> count of stale releases (recovery tracking)
CLOSE_LOCK_TTL_S = 20.0          # lock must complete within 20s or be auto-released
RECENTLY_CLOSED_TTL_S = 60.0     # recently closed blocks re-entry for 60s
_CLOSE_LOCK_HEALTH_LAST_LOG = [0.0]  # timestamp of last CLOSE_LOCK_HEALTH log

# V10.13u+13: Force reconciliation constants for stuck close loops
CLOSE_LOCK_FORCE_RECONCILE_AFTER = 3   # force reconcile after 3+ stale releases
CLOSE_LOCK_MAX_ATTEMPTS = 250          # force reconcile if attempts > 250
CLOSE_DUP_LOG_INTERVAL_S = 10.0        # throttle duplicate close logs to every 10s/key

# V10.13u+14: Distinguish full vs. partial close operations
FULL_CLOSE_TYPES = {
    "TP", "SL", "MICRO_TP", "TRAIL_PROFIT", "SCRATCH_EXIT", "STAGNATION_EXIT",
    "TIMEOUT_PROFIT", "TIMEOUT_LOSS", "TIMEOUT_FLAT", "EARLY_STOP",
    "REPLACED_EXIT", "WALL_EXIT", "EMERGENCY_EXIT"
}
PARTIAL_CLOSE_TYPES = {"PARTIAL_TP_25", "PARTIAL_TP_50", "PARTIAL_TP_75"}
FORCE_RECONCILE_RECORDS = []  # emergency close records for stuck positions
_CLOSE_STAGE_LAST_LOG = [0.0]  # throttle stage logs to max 1/second


def _close_key(sym: str, pos: dict) -> str:
    """V10.13u+9: Generate stable close key from position attributes.

    Uses entry time, action, and entry price to uniquely identify a close operation.
    Prevents duplicate closes on the same position across different price ticks.
    """
    opened = pos.get("opened_at") or pos.get("entry_time") or pos.get("ts") or ""
    action = pos.get("action") or pos.get("side") or ""
    entry = pos.get("entry") or pos.get("entry_price") or ""
    return f"{sym}:{action}:{entry}:{opened}"


def _close_stage(sym: str, key: str, stage: str, **meta) -> None:
    """V10.13u+14: Log close stages for diagnostics, throttled to 1/second."""
    now = time.time()
    # Throttle to prevent log spam - max 1 message per second across all stages
    if now - _CLOSE_STAGE_LAST_LOG[0] >= 1.0:
        _CLOSE_STAGE_LAST_LOG[0] = now
        meta_str = " ".join(f"{k}={v}" for k, v in meta.items()) if meta else ""
        log.warning(f"[CLOSE_STAGE] symbol={sym} key={key} stage={stage} {meta_str}")


def _cleanup_close_locks(now: float = None) -> None:
    """V10.13u+11: Remove stale locks and expired recently-closed entries.

    V10.13u+13: Use _release_stale_close_lock to handle force_reconcile triggers.

    Prevents indefinite lock hold-up and allows position re-entry after TTL.
    Logs stale releases for observability and triggers recovery if repeated.
    """
    now = now or time.time()

    stale = [
        key for key, meta in _CLOSING_POSITIONS.items()
        if now - meta.get("ts", now) > CLOSE_LOCK_TTL_S
    ]
    for key in stale:
        meta = _CLOSING_POSITIONS.get(key, {})
        # V10.13u+13: Call _release_stale_close_lock to trigger force_reconcile if needed
        _release_stale_close_lock(key, meta, now)
        # Log stuck position warning (after release, so we have updated stale count)
        count = _STALE_CLOSE_COUNTS.get(key, 0)
        if count >= 2:
            log.error(
                "[POSITION_CLOSE_STUCK] key=%s symbol=%s count=%s action=reconcile_required",
                key, meta.get("symbol"), count
            )

    old_closed = [
        key for key, ts in _RECENTLY_CLOSED.items()
        if now - ts > RECENTLY_CLOSED_TTL_S
    ]
    for key in old_closed:
        _RECENTLY_CLOSED.pop(key, None)
        _STALE_CLOSE_COUNTS.pop(key, None)


def _release_stale_close_lock(key: str, meta: dict, now: float = None) -> None:
    """V10.13u+12: Release a stale close lock that exceeded TTL.

    V10.13u+13: Trigger force reconcile if stale_count >= CLOSE_LOCK_FORCE_RECONCILE_AFTER
    or attempts >= CLOSE_LOCK_MAX_ATTEMPTS to stop infinite close loops.

    Increments stale count and logs recovery event.
    Allows next close attempt to proceed (fresh lock acquisition).
    """
    now = now or time.time()
    age = now - meta.get("ts", now)
    _CLOSING_POSITIONS.pop(key, None)
    _STALE_CLOSE_COUNTS[key] = _STALE_CLOSE_COUNTS.get(key, 0) + 1
    stale_count = _STALE_CLOSE_COUNTS[key]
    attempts = int((meta or {}).get("attempts", 0))

    log.error(
        "[CLOSE_LOCK_STALE_RELEASE] key=%s symbol=%s reason=%s age=%.1fs count=%s",
        key, meta.get("symbol"), meta.get("reason"), age, stale_count
    )

    # V10.13u+13: Force reconcile if stuck in infinite loop
    if stale_count >= CLOSE_LOCK_FORCE_RECONCILE_AFTER or attempts >= CLOSE_LOCK_MAX_ATTEMPTS:
        _force_reconcile_stuck_close(key, meta, reason="stale_lock_threshold")


def _force_reconcile_stuck_close(key: str, meta: dict = None, reason: str = "stale_close_loop") -> bool:
    """V10.13u+13: Last-resort recovery for positions stuck in close loops.

    Removes the position from _positions and marks it as force_reconciled in
    _RECENTLY_CLOSED to prevent immediate reacquire. Returns True if position was changed.
    """
    import time
    meta = meta or {}
    symbol = meta.get("symbol") or key.split(":")[0]
    changed = False

    try:
        with _positions_lock:
            if symbol in _positions:
                _positions.pop(symbol, None)
                changed = True
                _sync_regime_exposure()
    except Exception as e:
        log.exception(f"[CLOSE_FORCE_RECONCILE_FAIL] key={key} symbol={symbol} err={e}")

    _CLOSING_POSITIONS.pop(key, None)
    # Store timestamp in _RECENTLY_CLOSED to block immediate reacquire (consistent with existing API)
    _RECENTLY_CLOSED[key] = time.time()

    log.error(
        "[CLOSE_FORCE_RECONCILE] key=%s symbol=%s reason=%s stale_count=%s attempts=%s changed=%s",
        key, symbol, reason, _STALE_CLOSE_COUNTS.get(key, 0), meta.get("attempts", 0), changed
    )
    return changed


def _try_acquire_close_lock(sym: str, pos: dict, reason: str, now: float = None) -> tuple:
    """V10.13u+12: Attempt to acquire close lock with hard stale recovery.

    Returns: (acquired: bool, close_key: str, status: str)
    Status is one of: "acquired", "recently_closed", "already_closing"

    V10.13u+12: Cleanup runs BEFORE duplicate check to enable hard stale recovery.
    If a lock is stale (age > CLOSE_LOCK_TTL_S), it's released immediately,
    allowing the next close attempt to proceed with a fresh lock.

    V10.13u+14 Phase 2: Defensive guard - partial TP never acquires full lock.
    """
    # V10.13u+14 Phase 2: Reject partial reasons defensively (belt and suspenders)
    if reason in PARTIAL_CLOSE_TYPES:
        log.error(f"[PARTIAL_TP_LOCK_BLOCKED] symbol={sym} reason={reason}")
        return False, None, "partial_tp_not_allowed"

    now = now or time.time()
    _cleanup_close_locks(now)

    key = _close_key(sym, pos)

    if key in _RECENTLY_CLOSED:
        return False, key, "recently_closed"

    meta = _CLOSING_POSITIONS.get(key)
    if meta:
        age = now - meta.get("ts", now)

        # V10.13u+12: Hard recovery — stale lock is released immediately
        if age > CLOSE_LOCK_TTL_S:
            _release_stale_close_lock(key, meta, now)
            # Continue and acquire fresh lock below
        else:
            # V10.13u+13: Duplicate log throttled by key, max once per CLOSE_DUP_LOG_INTERVAL_S (10s)
            meta["attempts"] = meta.get("attempts", 0) + 1
            last_log = meta.get("last_log", 0)
            if now - last_log >= CLOSE_DUP_LOG_INTERVAL_S:
                meta["last_log"] = now
                log.warning(
                    "[CLOSE_SKIP_DUPLICATE] %s reason=%s key=%s status=already_closing age=%.1fs attempts=%s",
                    sym,
                    reason,
                    key,
                    age,
                    meta.get("attempts", 0),
                )
            return False, key, "already_closing"

    _CLOSING_POSITIONS[key] = {
        "ts": now,
        "symbol": sym,
        "reason": reason,
        "attempts": 1,
        "last_log": now,
    }
    log.warning("[CLOSE_LOCK_ACQUIRED] %s reason=%s key=%s", sym, reason, key)
    return True, key, "acquired"


def _is_recently_closed(key: str) -> bool:
    """V10.13u+10: Check if a close key is in recently-closed TTL tracking."""
    return key in _RECENTLY_CLOSED


def _mark_recently_closed(key: str) -> None:
    """V10.13u+10: Mark a close key as recently closed."""
    _RECENTLY_CLOSED[key] = time.time()


def get_close_lock_health() -> dict:
    """V10.13u+12: Return close lock health metrics for watchdog/self-heal suppression.

    Safe to call frequently. Cleans up stale locks before returning.
    Returns dict with: active, oldest_age, keys (first 5), stale_releases.
    """
    now = time.time()
    _cleanup_close_locks(now)

    oldest_age = 0.0
    if _CLOSING_POSITIONS:
        oldest_age = max(now - m.get("ts", now) for m in _CLOSING_POSITIONS.values())

    return {
        "active": len(_CLOSING_POSITIONS),
        "oldest_age": oldest_age,
        "keys": list(_CLOSING_POSITIONS.keys())[:5],
        "stale_releases": sum(_STALE_CLOSE_COUNTS.values()),
    }


def _release_close_lock(close_key: str, sym: str, reason: str, status: str = "closed") -> None:
    """V10.13u+12: Release close lock in a consistent way (for finally/guaranteed cleanup).

    Called to guarantee lock release.
    status: "closed" if close succeeded, "failed" if close aborted.
    """
    if status == "closed":
        _mark_recently_closed(close_key)
        _CLOSING_POSITIONS.pop(close_key, None)
        log.warning(f"[CLOSE_LOCK_RELEASED] {sym} reason={reason} key={close_key} status=closed")
    else:
        _CLOSING_POSITIONS.pop(close_key, None)
        log.error(f"[CLOSE_LOCK_RELEASED] {sym} reason={reason} key={close_key} status=failed")


def _log_close_lock_health() -> None:
    """V10.13u+12: Log close lock health metrics once per 60 seconds."""
    now = time.time()
    if now - _CLOSE_LOCK_HEALTH_LAST_LOG[0] >= 60.0:
        _CLOSE_LOCK_HEALTH_LAST_LOG[0] = now
        health = get_close_lock_health()
        active = health["active"]
        recently = len(_RECENTLY_CLOSED)
        top_lock = "none"
        if _CLOSING_POSITIONS:
            top_key = max(_CLOSING_POSITIONS.keys(), key=lambda k: _CLOSING_POSITIONS[k].get("attempts", 0))
            meta = _CLOSING_POSITIONS[top_key]
            top_lock = f"{meta.get('symbol')}:{meta.get('reason')} age={now - meta.get('ts', now):.1f}s attempts={meta.get('attempts', 0)}"
        log.info(f"[CLOSE_LOCK_HEALTH] active={active} recently_closed={recently} top={top_lock}")


def _adaptive_tp_sl(ev, wr):
    """V8: Continuous TP/SL multipliers from EV and win rate.

    Replaces discrete 3-tier EV lookup with smooth scaling.
    At ev=0, wr=0.5: tp_k=1.1, sl_k=0.9  (near-current baseline).
    At ev=0.5, wr=0.6: tp_k=1.55, sl_k=0.75  (proven winner).
    At ev=-0.5, wr=0.4: tp_k=0.75, sl_k=1.05  (clipped to 1.0/0.6).
    Clamps: tp_k ∈ [1.0, 2.0], sl_k ∈ [0.6, 1.0].

    V10.13s: Widen TP targets during cold-start to reduce timeout-driven exits.
    During bootstrap with sparse data, EV/WR estimates are unreliable. Widening
    TP targets makes them more reachable within extended hold windows, reducing
    forced timeouts and improving learning signal (more TP/SL, fewer timeouts).
    """
    tp_k = 1.1 + (ev * 0.8) + ((wr - 0.5) * 0.5)
    sl_k = 0.9 - (ev * 0.3)

    # V10.13s: Boost TP multiplier during cold-start
    try:
        from src.services.realtime_decision_engine import is_cold_start as _is_cs
        if _is_cs():
            tp_k *= 1.3  # widen TP by 30% during bootstrap to improve reachability
    except Exception:
        pass

    return min(max(tp_k, 1.0), 2.0), min(max(sl_k, 0.6), 1.0)


def regime_tp_sl_adjust(tp_k, sl_k, regime):
    """V10.2: Regime-specific TP/SL multipliers applied after EV/WR scaling.

    Trend regimes (BULL/BEAR): wider TP (let winners run), tighter SL
      (confirmed direction — stop doesn't need to be as wide).
    HIGH_VOL: narrower TP (take profit sooner before reversal), wider SL
      (noise is larger, SL needs room to breathe).
    QUIET_RANGE: narrower TP (low ATR, don't wait for large moves), tight SL.
    RANGING: unchanged (EV/WR scaling is sufficient for mean-reversion).

    Applied after both QUIET_RANGE override and _adaptive_tp_sl so regime
    context adds a final layer on top of the EV-based baseline.
    """
    if regime in ("BULL_TREND", "BEAR_TREND"):
        tp_k *= 1.2   # let trend run further
        sl_k *= 0.9   # confirmed direction → tighter SL
    elif regime == "HIGH_VOL":
        tp_k *= 0.9   # take profit before volatile reversal
        sl_k *= 1.1   # wider SL to survive noise spikes
    elif regime == "QUIET_RANGE":
        tp_k *= 0.8   # low ATR — target small move, exit fast
        sl_k *= 0.9
    # RANGING: EV/WR scaling is the sole driver — no regime override
    return tp_k, sl_k


def adaptive_sl_tightening(entry, current_price, sl, direction, atr):
    """V10.2: Gradually tighten SL as trade moves into profit.

    Activates only after 0.3% move (well above fee + spread noise floor).
    tighten factor scales with move depth: 0.3%→0.15, 1%→0.5 (cap).
    For BUY: new_sl = max(old_sl, entry + move × tighten × entry)
    For SELL: new_sl = min(old_sl, entry - move × tighten × entry)
    The max/min ensures SL only ever moves in the favorable direction.

    Operates in the 0.3%–0.6% pre-trail window (trailing activates at 0.6%
    and Chandelier takes over — pos["sl"] is not read after that point).
    After partial TP (SL→breakeven), pushes SL slightly above entry to
    capture additional profit if price reverses before trail activates.

    atr parameter reserved for future ATR-normalized version.
    """
    move = ((current_price - entry) / entry if direction == "BUY"
            else (entry - current_price) / entry)
    if move < 0.003:   # below activation threshold — don't touch SL
        return sl
    tighten = min(0.5, move * 50)   # 0.3%→0.15, 0.6%→0.30, 1%→0.50 (cap)
    if direction == "BUY":
        return max(sl, entry + move * tighten * entry)
    else:
        return min(sl, entry - move * tighten * entry)


# ── V10.3 helpers ───────────────────────────────────────────────────────────────

def _winsorize(x, p=0.1):
    """V10.3c: Clamp extreme values before std computation.

    Removes the top and bottom p-fraction of values so that a single outlier
    trade (e.g. a flash-crash tick or an abnormally large fill) cannot spike
    the realized-vol estimate and cause a sudden size reduction.
    Falls back to identity when k==0 (fewer than 10 samples at p=0.1).
    """
    if not x:
        return x
    xs = sorted(x)
    n  = len(xs)
    k  = int(n * p)
    if k == 0:
        return x
    low  = xs[k]
    high = xs[-k - 1]
    return [min(max(v, low), high) for v in x]


def volatility_adjustment(sym):
    """V10.3c: Winsorized + smoothed realized-vol sizing refinement.

    Applies _winsorize(p=0.1) inside _std before computing variance, so
    extreme outlier returns don't distort the vol estimate.  Otherwise
    identical to V10.3b: 70/30 blend of recent/older windows, normalised
    around 1% typical crypto vol, clamped [0.7, 1.3], bootstrap-safe (<30→1.0).
    """
    ret = returns_hist.get(sym, [])
    if len(ret) < 30:
        return 1.0

    def _std(x):
        xw = _winsorize(x, p=0.1)
        m  = sum(xw) / len(xw)
        return (sum((i - m) ** 2 for i in xw) / len(xw)) ** 0.5

    recent     = ret[-20:]
    older      = ret[-40:-20] if len(ret) >= 40 else recent
    std        = 0.7 * _std(recent) + 0.3 * _std(older)
    vol_factor = 0.01 / (std + 1e-6)
    return max(0.7, min(1.3, vol_factor))


# ════════════════════════════════════════════════════════════════════════════════
# V10.12d: Unblock Mode Rate Limiting
# ════════════════════════════════════════════════════════════════════════════════

def is_unblock_mode_trade() -> bool:
    """Check if current system state indicates unblock mode."""
    try:
        from src.services.realtime_decision_engine import is_unblock_mode
        return is_unblock_mode()
    except:
        return False


def can_open_unblock_trade() -> tuple[bool, str]:
    """
    V10.12d: Check unblock rate limits before opening new position.
    
    Limits:
    - Max 6 unblock trades per hour
    - Max 2 concurrent unblock positions
    
    Returns: (allowed: bool, reason: str)
    """
    global _unblock_trades_hour
    
    if not is_unblock_mode_trade():
        return True, "normal_mode"
    
    now = time.time()
    
    # Clean up trades older than 1 hour
    _unblock_trades_hour = [t for t in _unblock_trades_hour if now - t < 3600.0]
    
    # Check hourly rate limit
    if len(_unblock_trades_hour) >= _UNBLOCK_TRADES_MAX_HOUR:
        return False, f"UNBLOCK_RATE_LIMIT: {len(_unblock_trades_hour)}/{_UNBLOCK_TRADES_MAX_HOUR} trades in last hour"
    
    # Check concurrent position limit
    unblock_open = sum(1 for pos in _positions.values() 
                       if pos.get("unblock_mode", False))
    if unblock_open >= _UNBLOCK_POSITIONS_MAX:
        return False, f"UNBLOCK_POS_LIMIT: {unblock_open}/{_UNBLOCK_POSITIONS_MAX} unblock positions open"
    
    return True, "unblock_allowed"


def record_unblock_trade():
    """Record that an unblock-mode trade was opened (for rate limiting)."""
    global _unblock_trades_hour
    _unblock_trades_hour.append(time.time())


def dynamic_hold_extension(base_hold, ev, atr, entry):
    """V10.3c: EV + ATR-volatility aware hold-time scaling.

    Two independent scale factors multiplied together:

    EV component (unchanged from V10.3b):
      scale_ev = 1.0 + clamp(ev × 1.5, -0.3, +0.3)
      ev=-0.2 → 0.70×   ev=0 → 1.0×   ev=+0.2 → 1.30×

    ATR/volatility component (new):
      atr_pct  = atr / entry
      vol_scale = clamp(0.01 / atr_pct, 0.85, 1.15)
      Low-vol (tight ATR) → up to 1.15× (trade has room to develop quietly)
      High-vol (wide ATR) → down to 0.85× (don't overstay in choppy markets)
      Normalised around 1% move; tighter band than EV component to stay subtle.

    Combined: scale = scale_ev × vol_scale
    Bounded result: [5, 22] ticks — identical to V10.3b.
    """
    scale_ev   = 1.0 + max(-0.3, min(0.3, ev * 1.5))
    # V11.0: Volatility-Weighted Adaptive Timeout
    # vol_factor maps ATR deviation from 1% baseline to hold multiplier.
    # baseline ATR 1.0% → vol_factor=1.0 (no change)
    # ATR 0.5% (quiet)    → vol_factor=0.5 (shorter – market too quiet to develop)
    # ATR 2.0% (volatile) → vol_factor=1.5 (longer – more room needed, capped)
    atr_pct    = atr / max(entry, 1e-9)
    vol_factor = max(0.7, min(1.5, 1.0 + (atr_pct - 0.01) / 0.01))
    timeout    = int(base_hold * scale_ev * vol_factor)
    return max(120, min(600, timeout))  # [2m, 10m] range in seconds


def compute_timeout(base: float = 180, atr_ratio: float = 0.0) -> float:
    """V10.14.b: Adaptive timeout with ATR-ratio volatility scaling.

    Standalone function required by V10.14.b spec (name: compute_timeout).
    Complements dynamic_hold_extension which operates on live ATR + EV signals.

    Parameters
    ----------
    base      : float — base hold time in seconds (default 180 s = 3 min)
    atr_ratio : float — atr / entry_price  (0.0 = no ATR adjustment)

    Vol scaling
    -----------
      vol_scale = clamp(0.01 / atr_ratio, 0.7, 1.3)
      Tight market (low ATR)  → up to 1.3× (trade needs more time to develop)
      Volatile market (hi ATR)→ down to 0.7× (exit earlier in choppy regime)
      Normalised around 1% ATR baseline.

    Returns
    -------
    float — timeout in seconds, bounded [60, 600].
    """
    if atr_ratio > 0:
        vol_scale = max(0.7, min(1.3, 0.01 / (atr_ratio + 1e-9)))
    else:
        vol_scale = 1.0
    return max(60.0, min(600.0, base * vol_scale))


# ── V10.4 helpers — portfolio intelligence ────────────────────────────────────

def signal_score(signal, ev):
    """V10.4: Composite quality score for incoming signals.

    Weights EV (proven statistical edge) at 70% and signal confidence
    (indicator agreement) at 30%.  Used to rank candidates against open
    positions before committing capital.

    Returns a float; higher = better opportunity.
    """
    conf = signal.get("confidence", 0.5) or 0.5
    return 0.7 * ev + 0.3 * conf


def position_score(pos, now_ts=None):
    """V10.4b: Time-decayed composite quality score for an open position.

    Base score mirrors signal_score (0.7×risk_ev + 0.3×conf) so they are
    directly comparable.  A linear decay kicks in after the first 30 ticks
    of age (≈60 s at 2 s/tick), bottoming at 0.70× at age≥150 s.

    Effect: stale positions that have not hit TP/SL/trail lose priority
    naturally, making them rotation candidates without any forced-exit logic.
    Bootstrap-safe: positions without open_ts are treated as brand-new (no decay).
    """
    if now_ts is None:
        now_ts = time.time()
    ev   = pos.get("risk_ev", 0.0)
    conf = pos.get("signal", {}).get("confidence", 0.5) or 0.5
    base = 0.7 * ev + 0.3 * conf

    open_ts = pos.get("open_ts")
    if open_ts is None:
        return base   # legacy position — no decay

    age   = now_ts - open_ts
    if age <= 30:
        return base
    decay = max(0.70, 1.0 - (age - 30) / 120)
    return base * decay


def can_replace(now_ts=None):
    """V10.4b: Global 15-second cooldown between any two replacements.

    Prevents back-to-back churn loops where the same (or another) signal
    triggers a second replacement immediately after the first one fires.
    Updates _last_replace_ts on success.
    """
    global _last_replace_ts
    if now_ts is None:
        now_ts = time.time()
    if now_ts - _last_replace_ts < 15:
        return False
    _last_replace_ts = now_ts
    return True


def should_replace(new_score, positions, now_ts=None):
    """V10.4b: Find the weakest open position that the incoming signal beats.

    Profit protection: positions with live_pnl > 0.3% or trailing stop active
    are never replaced — they are working and should be allowed to reach TP.

    Churn guard: requires new_score > worst_score + 0.05 (≈7pp EV gap).

    Returns the symbol of the replacement candidate, or None.
    """
    if not positions:
        return None
    if now_ts is None:
        now_ts = time.time()

    worst_sym   = min(positions, key=lambda s: position_score(positions[s], now_ts))
    worst_pos   = positions[worst_sym]

    # Profit protection — do not kill winning trades
    if worst_pos.get("is_trailing", False):
        return None
    if worst_pos.get("live_pnl", 0.0) > 0.003:
        return None

    worst_score = position_score(worst_pos, now_ts)
    if new_score > worst_score + _meta_state["replace_threshold"]:
        return worst_sym
    return None


def rotate_position(sym):
    """V10.4: Flag an open position for immediate close so capital is freed."""
    with _positions_lock:
        if sym in _positions:
            _positions[sym]["force_close"] = True


# ── V10.5 helpers — position scaling & pyramiding ─────────────────────────────

def should_add_to_position(pos, curr, prev):
    """V10.5b: True when a winning position qualifies for a momentum-confirmed pyramid add.

    All V10.5 conditions plus two new guards:
      momentum  — price must still be moving in trade direction (curr tick vs prev tick)
                  prevents late adds at the top/bottom of a move
      near-trail — block adds when move > 0.55% (trailing activates at 0.60%)
                  adding just before trail would increase size right at peak exposure
    """
    if pos.get("is_trailing", False):
        return False
    if pos.get("partial_taken", False):
        return False
    if pos.get("adds", 0) >= 2:
        return False
    reg = pos.get("signal", {}).get("regime", "")
    if reg == "HIGH_VOL":
        return False

    entry = pos["entry"]
    move  = (curr - entry) / entry if pos["action"] == "BUY" \
            else (entry - curr) / entry
    if move < _meta_state["pyramid_trigger"]:
        return False
    if pos.get("risk_ev", 0.0) < 0.1:
        return False

    # V10.5b: momentum confirmation — price must continue moving in trade direction
    if pos["action"] == "BUY"  and curr <= prev:
        return False
    if pos["action"] == "SELL" and curr >= prev:
        return False

    # V10.5b: near-trail guard — avoid adding within 0.05% of trailing activation
    if move > 0.0055:
        return False

    # Cap: size + add must not exceed 2× original
    orig     = pos.get("original_size", pos["size"])
    max_add  = orig * 2.0 - pos["size"]
    if max_add <= 0:
        return False

    # Capital headroom: adding half current size must not breach _MAX_CAP_USED
    size_add = min(pos["size"] * 0.5, max_add)
    if (capital_usage() + size_add / _TOTAL_CAPITAL) >= _MAX_CAP_USED:
        return False

    return True


def add_to_position(pos, curr):
    """V10.5: Scale into a winning position (VWAP entry, capped at 2×original).

    size_add = min(current_size × 0.5, remaining room to 2× cap)
    New entry = VWAP of old position and add — accurate blended cost basis.
    _risk_guard() is called after to ensure _MAX_TOTAL_RISK is respected.
    """
    orig     = pos.get("original_size", pos["size"])
    max_add  = orig * 2.0 - pos["size"]
    size_add = min(pos["size"] * 0.5, max_add)

    old_size  = pos["size"]
    old_entry = pos["entry"]
    new_size  = old_size + size_add

    # VWAP blended entry — correct for unequal lot sizes
    pos["entry"] = (old_entry * old_size + curr * size_add) / new_size
    pos["size"]  = new_size
    pos["adds"]  = pos.get("adds", 0) + 1
    _risk_guard()


def should_reduce_position(pos, curr):
    """V10.5: True when a losing position with negative edge should be halved.

    Conditions (all must pass):
      move < -0.3%     — position is losing (below noise floor)
      risk_ev < 0.0    — edge is confirmed negative (not just unlucky)
      not reduced      — only one reduction allowed per position
      not partial_taken — partial TP already handled sizing; don't double-cut
    """
    if pos.get("reduced", False):
        return False
    if pos.get("partial_taken", False):
        return False

    entry = pos["entry"]
    move  = (curr - entry) / entry if pos["action"] == "BUY" \
            else (entry - curr) / entry
    if move > -0.003:
        return False
    if pos.get("risk_ev", 0.0) >= 0.0:
        return False

    return True


def reduce_position(pos, curr):
    """V10.5b: Adaptively cut a losing position — severity scales with loss depth.

    move < -0.6%  → keep 30% (heavy loss, cut hard)
    move < -0.4%  → keep 50% (moderate loss, standard halve)
    move < -0.3%  → keep 70% (mild loss, light trim)

    Smoother than the fixed 50% cut: shallow losses get a light trim that
    preserves more upside if price reverses; deep losses get cut hard to
    protect remaining capital.
    """
    entry = pos["entry"]
    move  = (curr - entry) / entry if pos["action"] == "BUY" \
            else (entry - curr) / entry

    if   move < -0.006:  factor = 0.3
    elif move < -0.004:  factor = 0.5
    else:                factor = 0.7

    pos["size"]    *= factor
    pos["reduced"]  = True
    _risk_guard()


# ── V10.6b helpers — robust meta-adaptive control ─────────────────────────────

def _ema_update(prev, x, alpha=0.2):
    """Single-step EMA.  Returns x on first call (prev is None)."""
    return x if prev is None else (alpha * x + (1.0 - alpha) * prev)


def _update_meta_inputs(lm_h, sr, dd):
    """Smooth raw metrics with alpha=0.2 EMA before mode decisions.

    Prevents single noisy readings from triggering mode switches.
    Stored in module-level _meta_ema dict.
    """
    _meta_ema["lm_health"] = _ema_update(_meta_ema["lm_health"], lm_h)
    _meta_ema["sharpe"]    = _ema_update(_meta_ema["sharpe"],    sr)
    _meta_ema["drawdown"]  = _ema_update(_meta_ema["drawdown"],  dd)
    return _meta_ema["lm_health"], _meta_ema["sharpe"], _meta_ema["drawdown"]


def _replacement_threshold(mode, lm_h):
    """Continuous replacement gap: base 0.05 adjusted by lm_health and mode.

    Higher lm_h → easier replacement (better signals justify lower bar).
    Defensive mode adds +0.02 (harder to replace — protect stability).
    Aggressive mode subtracts -0.01 (slightly easier rotation).
    Clamped [0.03, 0.08].
    """
    adj = (lm_h - 0.3) * 0.05
    if   mode == "defensive":  adj += 0.02
    elif mode == "aggressive": adj -= 0.01
    return max(0.03, min(0.08, 0.05 + adj))


def _pyramiding_trigger(mode, sr):
    """Continuous pyramid entry move threshold.

    Higher Sharpe → can add earlier (edge is confirmed).
    Defensive adds +0.001 (wait for more move before scaling).
    Aggressive subtracts -0.001 (scale sooner).
    Clamped [0.003, 0.006].
    """
    adj = (sr - 1.0) * 0.001
    if   mode == "defensive":  adj += 0.001
    elif mode == "aggressive": adj -= 0.001
    return max(0.003, min(0.006, 0.004 + adj))


def _reduce_threshold(mode, dd):
    """Continuous loss-reduction trigger (negative move %).

    Larger drawdown → tighter threshold (reduce earlier).
    Aggressive mode gives +0.001 of slack (tolerates slightly more loss).
    Clamped [-0.005, -0.002].
    """
    adj = dd * 0.02
    if mode == "aggressive": adj -= 0.001
    return max(-0.005, min(-0.002, -0.003 + adj))


def update_meta_mode(now_ts=None):
    """V10.6b: Hysteresis mode switcher with EMA-smoothed inputs and 10s cooldown.

    Reads lm_health / sharpe / max_drawdown from their canonical sources,
    smooths them, then applies hysteresis band logic to avoid oscillation:

      neutral  → defensive  when dd_smooth > 0.12
      neutral  → aggressive when lm_h_smooth > 0.45 AND sharpe_smooth > 1.3
      aggressive → neutral  when lm_h_smooth < 0.35 OR sharpe_smooth < 1.0
      defensive  → neutral  when dd_smooth < 0.08

    Safety: aggressive is blocked when raw dd > 0.10 (hard override).
    Updates _meta_state thresholds on every non-cooldown call.
    Returns current mode string.
    """
    if now_ts is None:
        now_ts = time.time()
    if now_ts - _meta_state["last_update"] < 10:
        return _meta_state["mode"]

    # Fetch raw metrics (safe fallbacks)
    lm_h = 0.0
    sr   = 0.0
    dd   = 0.0
    try:
        from src.services.learning_monitor import lm_health as _lmh
        lm_h = float(_lmh() or 0.0)
    except Exception:
        pass
    try:
        from src.services.diagnostics import sharpe as _sr, max_drawdown as _dd
        sr = float(_sr() or 0.0)
        dd = float(_dd() or 0.0)
    except Exception:
        pass

    # EMA-smooth before any decision
    lm_h_s, sr_s, dd_s = _update_meta_inputs(lm_h, sr, dd)

    mode = _meta_state["mode"]

    if mode == "neutral":
        if dd_s > 0.12:
            mode = "defensive"
        elif lm_h_s > 0.45 and sr_s > 1.3 and dd < 0.10:   # raw dd safety
            mode = "aggressive"
    elif mode == "aggressive":
        if dd >= 0.10 or lm_h_s < 0.35 or sr_s < 1.0:      # raw dd hard override
            mode = "neutral"
    elif mode == "defensive":
        if dd_s < 0.08:
            mode = "neutral"

    _meta_state["mode"]              = mode
    _meta_state["last_update"]       = now_ts
    _meta_state["replace_threshold"] = _replacement_threshold(mode, lm_h_s)
    _meta_state["pyramid_trigger"]   = _pyramiding_trigger(mode, sr_s)
    _meta_state["reduce_threshold"]  = _reduce_threshold(mode, dd_s)

    return mode


def compute_tp_sl(entry, direction, atr=0.003, sym=None, reg=None):
    """Absolute TP/SL prices.

    QUIET_RANGE: quick-exit targets (tp_k=0.7, sl_k=0.5, RR=1.4).

    Other regimes — V8 adaptive_tp_sl: continuous EV+WR scaling.
    risk_ev = tanh(mean/std) × min(n/50, 1) → near 0 during bootstrap,
    so tp_k ≈ 1.1 until statistically confirmed (EV must earn scaling).
    WR from global metrics (converges toward pair-specific as trades accumulate).

    V10.2: regime_tp_sl_adjust applied after EV/WR scaling — trend gets
    wider TP, high-vol gets wider SL, quiet gets tighter TP.
    """
    if reg == "QUIET_RANGE":
        tp_k, sl_k = 0.7, 0.5
    else:
        _ev = 0.0
        if sym and reg:
            try:
                from src.services.execution import risk_ev as _rev
                _ev = _rev(sym, reg)
            except Exception:
                pass
        try:
            from src.services.learning_event import get_metrics as _lgm
            _wr = _lgm().get("winrate", 0.5) or 0.5
        except Exception:
            _wr = 0.5
        tp_k, sl_k = _adaptive_tp_sl(_ev, _wr)

    tp_k, sl_k = regime_tp_sl_adjust(tp_k, sl_k, reg or "RANGING")

    # Hard floor: TP must be ≥ MIN_TP_PCT from entry, SL ≥ MIN_SL_PCT.
    # Prevents degenerate SL=TP=entry when atr collapses to near-zero
    # (observed: ETH RANGING with ATR≈0 → SL=$2183.43 = entry exactly).
    tp_dist = max(tp_k * atr, MIN_TP_PCT)
    sl_dist = max(sl_k * atr, MIN_SL_PCT)

    if direction == "BUY":
        return entry * (1 + tp_dist), entry * (1 - sl_dist)
    else:
        return entry * (1 - tp_dist), entry * (1 + sl_dist)

_TP_MULT = {"BULL_TREND": 1.0, "BEAR_TREND": 1.0,
            "RANGING":    1.0, "QUIET_RANGE": 1.0}
_SL_MULT = {"BULL_TREND": 0.8, "BEAR_TREND": 0.8,
            "RANGING":    0.8, "QUIET_RANGE": 0.8}


def net_ws(ws, spread_pct, fee_rt):
    """WS after spread and round-trip fees. Negative = edge eaten by costs."""
    return ws - (spread_pct + fee_rt)


# ── V3 helpers ─────────────────────────────────────────────────────────────────

def _decision_score(ev, ws):
    """EV-dominant blend: 75% EV + 25% WS."""
    return 0.75 * ev + 0.25 * ws


def _allow_trade_sigmoid(ev, ws):
    """Sigmoid probability gate — replaces hard should_trade() threshold.
    Center at 0.1: score=0.1→50% pass, score=0.4→87% pass, score=-0.2→13% pass.
    Weak-positive EV still gets through probabilistically instead of being blocked.
    """
    import math
    s = _decision_score(ev, ws)
    p = 1.0 / (1.0 + math.exp(-6.0 * (s - 0.1)))
    return random.random() < p


def _has_min_edge(entry, tp, sl):
    """Reject if TP or SL distance < MIN_EDGE_PCT — prevents micro-PnL noise trades."""
    tp_dist = abs(tp - entry) / max(entry, 1e-9)
    sl_dist = abs(sl - entry) / max(entry, 1e-9)
    return tp_dist >= MIN_EDGE_PCT and sl_dist >= MIN_EDGE_PCT


def _dynamic_rr_threshold(ev, atr_pct, wr):
    """V8: WR+EV+volatility-aware RR threshold.

    Base from EV tier:  ev>0.2→0.95,  ev>0→1.05,  ev≤0→1.2.
    WR adjustment: high WR (0.7) lowers required RR by 10% (can afford lower RR).
    Vol adjustment: high-ATR markets clamp at 1.2 (wider TP needed); low-ATR at 0.85.
    Hard floor 0.95 — never accept RR below this regardless of WR.
    """
    base    = 0.95 if ev > 0.2 else 1.05 if ev > 0 else 1.2
    wr_adj  = 1.0 - (wr - 0.5) * 0.5          # wr=0.7→0.9×, wr=0.3→1.1×
    vol_adj = min(max(atr_pct / 0.01, 0.85), 1.2)
    return max(0.95, base * wr_adj * vol_adj)


def _reject_bad_rr(entry, tp, sl, ev=None, atr_pct=None):
    """True (= reject) when reward/risk < V8 dynamic threshold.

    V8: threshold driven by EV, WR, and current ATR volatility — no static 1.0/1.2 split.
    WR from global metrics (most reliable proxy available in bootstrap phase).
    """
    risk = abs(sl - entry)
    if risk == 0:
        return True
    rr = abs(tp - entry) / risk
    _ev  = ev if ev is not None else 0.0
    _atr = atr_pct if atr_pct is not None else 0.01
    try:
        from src.services.learning_event import get_metrics as _lgm
        _wr = _lgm().get("winrate", 0.5) or 0.5
    except Exception:
        _wr = 0.5
    threshold = _dynamic_rr_threshold(_ev, _atr, _wr)
    return rr < threshold


def _dynamic_hold(atr_abs, entry, sym=None, reg=None, adx=0.0):
    """Timeout ticks scaled continuously by EV, then fine-tuned by ATR + trend.

    V8: EV-continuous base (replaces V7 discrete tiers 7/10/12):
      ev_factor = clamp((ev + 1) / 2, 0, 1)   — maps [-1..1] EV to [0..1]
      base = 6 + int(ev_factor × 6)             — continuous 6–12 ticks
      ev=-1 → 6,  ev=0 → 9,  ev=0.5 → 10,  ev=1 → 12

    Preserves V7 base-as-floor guarantee: EV base is never reduced by ATR.
    ATR tunes up to base+4 (was +3 in V7 — slight expansion for patience).
    ADX trend bonus (+2): confirmed trend needs more room to develop.
    Hard ceiling 17 prevents runaway holds.

    V10.13s: Extended hold during cold-start to reduce timeout dominance.
    During bootstrap (sparse data), EV estimates are unreliable and TP targets
    tight. Extending hold time gives trades more opportunity to reach targets
    instead of timing out prematurely.
    """
    atr_pct     = atr_abs / max(entry, 1e-9)
    trend_bonus = 2 if adx > 25 else 0

    _ev = 0.0
    if sym and reg:
        try:
            from src.services.execution import risk_ev as _rev
            _ev = _rev(sym, reg)
        except Exception:
            pass

    # V8 → V10.14: continuous EV → base mapping (seconds).
    # atr_adj removed — dead code after seconds conversion.
    ev_factor = min(max((_ev + 1) / 2, 0.0), 1.0)
    base      = 120 + int(ev_factor * 90)    # base [120s, 210s] (2–3.5 min)

    # Adaptive ATR adjustment (seconds-scale).
    atr_adj_s = int(100 * max(0.002, 0.01 / max(atr_pct, 1e-9)))
    hold      = max(base, min(base + 90, atr_adj_s + trend_bonus * 30))

    # V10.13s: Extend hold time during cold-start to reduce timeout exits.
    # Bootstrap trades have weaker EV estimates; TP targets are tighter relative
    # to expected move. Longer hold windows reduce forced timeouts while entries
    # are still learning signal quality.
    try:
        from src.services.realtime_decision_engine import is_cold_start as _is_cs
        if _is_cs():
            hold = int(hold * 1.5)  # extend by 50% during bootstrap
    except Exception:
        pass

    return max(120, min(hold, 450))   # V10.13s: ceiling raised 300s → 450s (7.5 min) during bootstrap


def _force_trade_guard():
    """True when fewer than MIN_TRADES_PER_100_TICKS opened in the last 100 ticks.
    Bypasses sigmoid gate to guarantee minimum learning data flow.
    """
    n = _tick_counter[0]
    recent = sum(1 for t in _trades_at_tick if n - t <= 100)
    return recent < MIN_TRADES_PER_100_TICKS


# ── V9 helpers ─────────────────────────────────────────────────────────────────

def policy_score(ev, wr, momentum, vol, regime_score):
    """V9: Policy-based continuous entry score (replaces binary ev>thr*1.5→*1.5).

    Weights (sum = 1.0):
      0.40 × ev           — dominant: proven edge drives sizing most
      0.20 × (wr - 0.5)  — WR contribution; 0 at 50%, +0.1 at 60%
      0.15 × momentum     — directional confirmation (ws proxy, normalized)
      0.15 × regime_score — trending (1.0) vs ranging (0.5)
      0.10 × (1 - vol)    — penalise high-vol entries (wider spread risk)

    Typical ranges at neutral state (ev=0, wr=0.5, momentum=0, regime=0.5, vol=0.01):
      score ≈ 0.17  → size *= 1.17  (slight boost — system is exploring)
    At strong state (ev=0.5, wr=0.65, momentum=0.4, regime=1.0, vol=0.008):
      score ≈ 0.46  → size *= 1.46  (near-cap boost — confident edge)
    At weak state  (ev=-0.3, wr=0.35, momentum=-0.3, regime=0.5, vol=0.025):
      score ≈ -0.14 → size *= 0.86  (trimmed — poor conditions)
    """
    score = (
        0.40 * ev +
        0.20 * (wr - 0.5) +
        0.15 * momentum +
        0.15 * regime_score +
        0.10 * (1.0 - vol)
    )
    return score


def meta_controller(sharpe, drawdown, winrate, trade_freq, volatility=0.0):
    """V9→V10: System-health aggression multiplier with hard kill-switch.

    Conditions evaluated top-to-bottom (first match wins):
      DD > 20%            → 0.0×  V10: hard stop — approaching catastrophic loss,
                                   halt all new positions (defense-in-depth before
                                   failure_control fires at its own threshold)
      DD > 12%            → 0.5×  V9: strong risk-off
      volatility > 3%     → 0.7×  V10: HIGH_VOL regime — wider spreads, execution
                                   risk; signal_generator also penalises but this
                                   adds a position-sizing layer
      Sharpe < 0.5        → 0.7×  underperforming system — reduce size
      trade_freq < 0.1    → 1.1×  activity pressure (< 10 trades/100 ticks)
      default             → 1.0×  healthy system

    Risk-on 1.2× (sharpe>1.5 AND wr>0.6) intentionally omitted:
    win-streak anti-martingale in auditor.py already covers this path (1.2-1.4×),
    stacking would compound to 1.68× which approaches unsafe concentration.
    """
    if drawdown > 0.20:
        return 0.0   # hard stop: catastrophic drawdown — no new positions
    if drawdown > 0.12:
        return 0.5
    if volatility > 0.03:
        return 0.7   # HIGH_VOL: wider spreads amplify execution risk
    if sharpe < 0.5:
        return 0.7
    if trade_freq < 0.1:
        return 1.1
    return 1.0


def _replace_allowed(symbol):
    """True if no replacement happened for this symbol in the last 300 s."""
    last = _last_replaced.get(symbol, 0.0)
    return (time.time() - last) > _REPLACE_COOLDOWN


def _total_risk():
    """Sum of (size × sl_fraction) across all open positions.
    sl_fraction = |sl - entry| / entry — derived from absolute sl price."""
    return sum(
        p["size"] * abs(p["sl"] - p["entry"]) / max(p["entry"], 1e-9)
        for p in _positions.values()
    )


def _risk_guard():
    """If total portfolio risk exceeds cap, scale all position sizes down."""
    if _total_risk() > _MAX_TOTAL_RISK:
        for p in _positions.values():
            p["size"] *= 0.7


def _sync_regime_exposure():
    """Rebuild _regime_exposure from current _positions to eliminate counter drift.
    Must be called under _positions_lock.
    """
    _regime_exposure.clear()
    for pos in _positions.values():
        r = pos.get("open_regime", pos.get("signal", {}).get("regime", "RANGING"))
        _regime_exposure[r] = _regime_exposure.get(r, 0) + 1


def get_open_positions():
    with _positions_lock:
        return dict(_positions)


def capital_usage():
    """Fraction of normalised capital currently deployed."""
    with _positions_lock:
        return sum(p["size"] for p in _positions.values()) / _TOTAL_CAPITAL


def _effective_ws(signal):
    """
    Risk-adjusted + regime-penalised WS for portfolio ranking.
    risk_adjust: normalise by avg WS of open positions.
    regime_penalty: reduce score proportionally to regime concentration.
    """
    ws     = signal.get("ws", 0.5)
    regime = signal.get("regime", "RANGING")
    # Risk-adjust: ws / avg_ws_of_open_positions
    if _positions:
        avg_ws = sum(p["signal"].get("ws", 0.5)
                     for p in _positions.values()) / len(_positions)
        ws = ws / max(avg_ws, 0.01)
    # Regime penalty: ws * (1 - exposure_fraction)
    n = len(_positions)
    if n > 0:
        exposure = _regime_exposure.get(regime, 0) / n
        ws *= (1.0 - exposure)
    return ws


def _vol_adjust(size, signal):
    """
    Scale size to target 2% realised volatility.
    Clamps ratio 0.5× – 2.0× to prevent extreme adjustments.
    """
    realised_vol = signal.get("features", {}).get("volatility", _TARGET_VOL)
    ratio = _TARGET_VOL / max(realised_vol, 1e-6)
    return size * max(0.5, min(2.0, ratio))


def _replace_if_better(signal):
    """
    V10.13: Global portfolio_score comparison replaces local effective_ws logic.

    Instead of comparing new signal vs weakest position in isolation, we
    SIMULATE the portfolio after each candidate replacement and score the
    resulting portfolio globally. Replace only when the simulated portfolio
    improves on the current global score.

    Global score = sum(efficiency_live) + momentum_bonus − risk_penalty
    (see risk_engine.portfolio_score for full definition).

    Process:
    1. Score the current portfolio baseline.
    2. For each candidate replacement (worst efficiency_live, worst ws):
       a. Build a simulated positions dict: remove candidate, add proxy for
          incoming signal using its policy_ev / estimated_hold.
       b. Score the simulated portfolio.
       c. If simulated_score > current_score + GLOBAL_REPLACE_MARGIN: replace.
    3. Fall back to V10.12 ws/ev rotation if global score doesn't improve.

    GLOBAL_REPLACE_MARGIN = 0.05: requires the portfolio to genuinely improve
    by at least 5% of a typical single-position efficiency contribution, not
    just a marginal improvement that could be noise.

    Returns True if replacement was queued, False otherwise.
    """
    if len(_positions) < MAX_POSITIONS:
        return False

    GLOBAL_REPLACE_MARGIN = 0.05

    try:
        from src.services.risk_engine import portfolio_score as _pf_score

        current_score = _pf_score(_positions)

        # Build a proxy position for the incoming signal (used in simulation)
        _ev_sig = signal.get("ev", 0.0) or 0.0
        _atr_s  = max(signal.get("atr", 0) or 0, signal["price"] * 0.003)
        _adx_s  = signal.get("features", {}).get("adx", 0.0)
        _hold_s = _dynamic_hold(_atr_s, signal["price"],
                                signal["symbol"], signal.get("regime","RANGING"),
                                adx=_adx_s)
        _hold_s = dynamic_hold_extension(_hold_s, _ev_sig, _atr_s, signal["price"])
        _eff_s  = _ev_sig / max(_hold_s, 1e-6)

        # Proxy position has same structure as a real position but simplified
        _now_sim = time.time()
        _proxy   = {
            "action":          signal.get("action", "BUY"),
            "size":            0.025,   # conservative estimate — real size unknown
            "entry":           signal["price"],
            "sl":              signal["price"] * 0.996,   # 0.4% proxy SL
            "sl_move":         0.004,                     # 0.4% proxy SL distance
            "signal":          signal,
            "efficiency":      _eff_s,
            "efficiency_live": _eff_s,
            "expected_hold":   _hold_s,
            "live_pnl":        0.0,
            "open_ts":         _now_sim,
        }

        best_candidate = None
        best_sim_score = current_score + GLOBAL_REPLACE_MARGIN   # must beat this

        for candidate_sym in _positions:
            if not _replace_allowed(candidate_sym):
                continue
            wp = _positions[candidate_sym]
            # Safety guards: never replace trailing/partial-taken/strong winners
            if wp.get("is_trailing", False):
                continue
            if wp.get("partial_taken", False):
                continue
            if wp.get("live_pnl", 0.0) >= 0.003:
                continue

            # Simulate: remove candidate, add proxy
            simulated = {s: p for s, p in _positions.items() if s != candidate_sym}
            simulated[signal["symbol"]] = _proxy
            sim_score = _pf_score(simulated)

            if sim_score > best_sim_score:
                best_sim_score = sim_score
                best_candidate = candidate_sym

        if best_candidate is not None:
            _positions[best_candidate]["force_close"] = True
            _pending_open.append(signal)
            _last_replaced[best_candidate] = _now_sim
            _gain = best_sim_score - current_score
            log.info(f"    replace[v10.13/global]: {best_candidate} "
                  f"← {signal['symbol']}  "
                  f"score {current_score:.4f}→{best_sim_score:.4f} "
                  f"(+{_gain:.4f})")
            return True

    except Exception:
        pass

    # ── Fallback: ws-margin and EV rotation (V10.12 logic preserved) ──────────
    weakest_sym = min(_positions,
                      key=lambda s: _effective_ws(_positions[s]["signal"]))
    new_eff  = _effective_ws(signal)
    weak_eff = _effective_ws(_positions[weakest_sym]["signal"])
    if new_eff > weak_eff * _REPLACE_MARGIN and _replace_allowed(weakest_sym):
        _positions[weakest_sym]["force_close"] = True
        _pending_open.append(signal)
        _last_replaced[weakest_sym] = time.time()
        log.info(f"    replace[ws]: {weakest_sym} (eff_ws={weak_eff:.3f}) "
              f"← {signal['symbol']} (eff_ws={new_eff:.3f})")
        return True

    should_rotate, worst_sym = rotate_capital(signal, _positions, MAX_POSITIONS)
    if should_rotate and worst_sym and _replace_allowed(worst_sym):
        _positions[worst_sym]["force_close"] = True
        _pending_open.append(signal)
        _last_replaced[worst_sym] = time.time()
        log.info(f"    replace[ev]: {worst_sym} "
              f"← {signal['symbol']} (regime={signal.get('regime','?')})")
        return True
    return False


def _allow_trade(symbol, direction, regime):
    """
    Portfolio-level gates before accepting a new position.
    Returns (allowed: bool, reason: str).
    """
    if symbol in _positions:
        return False, "already_open"
    # Bootstrap: bypass portfolio gates until 50 closed trades — fills lm_pnl_hist fast
    try:
        from src.services.learning_event import get_metrics as _lgm
        if _lgm().get("trades", 0) < 50:
            return True, "bootstrap_open"
    except Exception:
        pass
    if capital_usage() >= _MAX_CAP_USED:
        return False, "capital_limit"
    if len(_positions) >= MAX_POSITIONS:
        return False, "max_positions"
    from src.services.macro_guard import is_safe
    if not is_safe():
        return False, "macro_guard_halt"
        
    from src.services.squeeze_guard import is_safe_long, is_safe_short
    if direction == "BUY" and not is_safe_long(symbol):
        return False, "squeeze_guard_long"
    if direction == "SELL" and not is_safe_short(symbol):
        return False, "squeeze_guard_short"
        
    # Correlation shield — only check here when async execution engine is OFF.
    # When EXECUTION_ENGINE_ENABLED=1, the async path checks against its own
    # _positions dict (which may differ). Avoid double-gating with stale state.
    if os.getenv("EXECUTION_ENGINE_ENABLED", "0") != "1":
        from src.services.correlation_shield import is_safe_correlation
        if not is_safe_correlation(symbol, direction, _positions, 0.85):
            return False, "correlation_shield"
        
    same_dir = sum(1 for p in _positions.values() if p["action"] == direction)
    if same_dir >= MAX_SAME_DIR:
        return False, "same_dir"
    # Regime concentration: block if one regime dominates (>70%)
    n = len(_positions)
    if n > 0:
        regime_count = _regime_exposure.get(regime, 0)
        if regime_count / n >= MAX_REGIME_PCT:
            return False, "regime_concentration"
    return True, "ok"


def _flush():
    if BATCH:
        save_batch(BATCH)
        BATCH.clear()
    _last_flush[0] = time.time()


def _save_paper_trade_closed(closed_trade: dict) -> None:
    """V10.13u+20: Save closed paper trade to Firebase for learning.

    Paper trades use real prices and produce canonical metrics for learning.
    Writes to trades_paper collection and updates metrics with paper outcomes.

    Args:
        closed_trade: Closed paper trade dict from paper_trade_executor
    """
    try:
        # Prepare paper trade record for Firebase
        paper_record = {
            **closed_trade,
            "timestamp": time.time(),
            "mode": "paper_live",  # mark as paper for filtering
        }

        # Save to Firebase (paper trades in separate collection)
        try:
            from src.services.firebase_client import db, col
            if db:
                # Write to trades_paper collection (separate from live trades)
                db.collection(col("trades_paper")).add(paper_record)
                log.warning(
                    f"[LEARNING_UPDATE] source=paper_closed_trade symbol={closed_trade.get('symbol')} "
                    f"bucket={closed_trade.get('explore_bucket', 'A_STRICT_TAKE')} "
                    f"outcome={closed_trade.get('outcome')} net_pnl_pct={closed_trade.get('net_pnl_pct', 0):.4f}"
                )
        except Exception as e:
            log.warning(f"[LEARNING_WRITE_FAILED] source=paper {e}")

        # Update learning metrics
        try:
            from src.services.learning_event import update_metrics
            update_metrics(closed_trade)
        except Exception as e:
            log.debug(f"[METRICS_UPDATE_FAILED] {e}")

        # Update bucket-level metrics for exploration analysis
        try:
            from src.services.bucket_metrics import update_bucket_metrics
            update_bucket_metrics(closed_trade)
        except Exception as e:
            log.debug(f"[BUCKET_METRICS_FAILED] {e}")

    except Exception as e:
        log.warning(f"[PAPER_SAVE_ERROR] {e}")


def handle_signal(signal):
    global _last_replace_ts   # V10.10: written directly in efficiency replacement path
    sym     = signal["symbol"]
    regime  = signal.get("regime", "RANGING")

    # EMERGENCY (2026-04-25): Entry gate — block new positions when Firebase degraded
    # Prevents unsafe trading when authoritative state unavailable
    try:
        from src.services.runtime_flags import (
            should_skip_entry,
            get_db_degraded_reason,
            log_suppressed_decision,
        )
        should_skip, reason = should_skip_entry(sym)
        if should_skip:
            log.debug(f"[SAFE_MODE] ENTRY_BLOCKED: {sym} ({reason})")
            # STEP 5: Log decision suppression (throttled to once per 60s)
            # Note: Pass only decision code, not reason — log_suppressed_decision() adds reason prefix
            log_suppressed_decision("TAKE_BLOCKED_SAFE_MODE")
            return
    except Exception:
        pass  # Graceful degrade if flags service unavailable

    # V10.13L: Fail-closed gate — no new trades if runtime fault detected
    try:
        from src.services.runtime_fault_registry import is_trading_allowed
        if not is_trading_allowed():
            log.debug(f"[V10.13L] OPEN_BLOCKED: runtime fault active for {sym}")
            return
    except Exception:
        pass  # Graceful degrade if registry unavailable

    # ── V10.14: CORRECTNESS GUARD — Candidate Deduplication ──────────────────
    # Prevent repeated identical setups during cold start.
    # This is a high-priority correctness fix, not a tuning knob.
    try:
        from src.services.candidate_dedup import (
            check_duplicate, check_symbol_side_cooldown, check_bootstrap_frequency
        )

        # Check 1: Exact duplicate fingerprint in last 20 seconds
        allowed, reason = check_duplicate(signal)
        if not allowed:
            log.info(f"    candidate_gate: {reason}  sym={sym}")
            return

        # Check 2: Same symbol + same side in last 30 seconds
        allowed, reason = check_symbol_side_cooldown(signal)
        if not allowed:
            log.info(f"    candidate_gate: {reason}  sym={sym}")
            return

        # Check 3: Bootstrap frequency cap (max 6 opens per 60s during cold start)
        allowed, reason = check_bootstrap_frequency(signal)
        if not allowed:
            log.info(f"    candidate_gate: {reason}  sym={sym}")
            return
    except Exception as e:
        log.warning(f"[DEDUP_GUARD_FAIL] {e} — proceeding without dedup checks")

    allowed, reason = _allow_trade(sym, signal["action"], regime)
    if not allowed:
        if reason == "max_positions":
            # Global 15 s cooldown — covers both V10.10 and V10.4b paths
            _now = time.time()
            if not can_replace(_now):
                return

            # ── Shared: risk_ev for incoming signal ───────────────────────────
            _ev_r = 0.0
            try:
                from src.services.execution import risk_ev as _rev_r
                _ev_r = _rev_r(sym, regime)
            except Exception:
                pass

            # ── V10.10: Efficiency-based replacement (primary path) ────────────
            # Compute expected hold time for the incoming signal using same
            # logic as the open path — dynamic_hold then hold_extension.
            _sig_atr_r = max(signal.get("atr", 0) or 0, signal["price"] * 0.003)
            _sig_adx_r = signal.get("features", {}).get("adx", 0.0)
            _hold_r    = _dynamic_hold(_sig_atr_r, signal["price"], sym, regime,
                                       adx=_sig_adx_r)
            _hold_r    = dynamic_hold_extension(_hold_r, _ev_r, _sig_atr_r,
                                                signal["price"])
            _new_eff   = _ev_r / max(_hold_r, 1e-6)

            # Gate D: fw_score ≥ MIN and policy_ev > 0
            _fw_bools_r = {k: v for k, v in signal.get("features", {}).items()
                           if isinstance(v, bool)}
            _fw_r = 0.0
            try:
                from src.services.feature_weights import compute_weighted_score as _cws_r
                _fw_r = _cws_r(_fw_bools_r, sym, regime)
            except Exception:
                pass
            from src.services.feature_weights import MIN_SCORE as _FW_MIN_R

            _use_v1010 = (_fw_r >= _FW_MIN_R and _ev_r > 0 and _positions)

            if _use_v1010:
                # Find weakest by efficiency_live (falls back to efficiency at open)
                _worst10 = min(
                    _positions,
                    key=lambda s: _positions[s].get(
                        "efficiency_live", _positions[s].get("efficiency", 0.0)))
                _wp10     = _positions[_worst10]
                _worst_eff = _wp10.get("efficiency_live",
                                       _wp10.get("efficiency", 0.0))

                # Threshold: meta-adaptive (spec §4B) + V10.12 correlation adj
                # Replacing worst_sym with a diversifying position → lower bar
                # Replacing with a concentrating position → higher bar
                _mode10  = _meta_state["mode"]
                _eff_thr = 0.01 if _mode10 == "aggressive" else \
                           0.04 if _mode10 == "defensive"  else 0.02
                try:
                    from src.services.risk_engine import (
                        replacement_correlation_adj as _rca)
                    _corr_adj = _rca(signal.get("action", ""), regime,
                                     _positions, _worst10)
                    _eff_thr *= _corr_adj
                except Exception:
                    _corr_adj = 1.0

                # All replacement conditions
                _cond_A = _new_eff > _worst_eff + _eff_thr
                _cond_C = (_wp10.get("live_pnl", 0.0) < 0.003
                           and not _wp10.get("is_trailing", False)
                           and not _wp10.get("partial_taken", False))

                if _cond_A and _cond_C and _replace_allowed(_worst10):
                    # Tag the signal so handle_signal records it + applies recycling
                    signal["_is_replacement"] = True
                    rotate_position(_worst10)
                    _pending_open.append(signal)
                    _last_replaced[_worst10] = _now
                    log.info(f"    replace[v10.10/v10.12]: {_worst10} "
                          f"(eff={_worst_eff:.4f}) ← {sym} "
                          f"(eff={_new_eff:.4f})  "
                          f"thr={_eff_thr:.4f}  corr_adj×{_corr_adj:.2f}  "
                          f"mode={_mode10}")
                    return

            # ── V10.4b fallback: score-based replacement ───────────────────────
            _new_score = signal_score(signal, _ev_r)
            _worst_sym = should_replace(_new_score, _positions, _now)
            if _worst_sym and _replace_allowed(_worst_sym):
                rotate_position(_worst_sym)
                _pending_open.append(signal)
                _last_replaced[_worst_sym] = _now
                _ws = position_score(_positions[_worst_sym], _now)
                log.info(f"    replace[v10.4b]: {_worst_sym} (score={_ws:.3f}) "
                      f"← {sym} (score={_new_score:.3f})")
            else:
                _replace_if_better(signal)   # fall back to ws/EV rotation
        else:
            # V10.13u+20 P1.1: Paper exploration from rejected signals
            _explored = False
            try:
                from src.core.runtime_mode import is_paper_mode, paper_exploration_enabled
                from src.services.paper_exploration import paper_exploration_override

                if is_paper_mode() and paper_exploration_enabled():
                    # Try to explore this rejection
                    explore_ctx = {
                        "reject_reason": reason,
                        "recovery_ready": False,
                        "probe_ready": False,
                    }
                    ov = paper_exploration_override(signal, explore_ctx)
                    if ov.get("allowed"):
                        entry_price = signal.get("price")
                        if entry_price is None or not isinstance(entry_price, (int, float)):
                            log.warning(
                                "[PAPER_EXPLORE_SKIP] symbol=%s reason=no_real_price reject_reason=%s",
                                sym, reason
                            )
                        else:
                            _explored = True
                            open_paper_position(
                                signal,
                                price=entry_price,
                                ts=time.time(),
                                reason="PAPER_EXPLORE",
                                extra={
                                    "paper_source": "exploration_reject",
                                    "explore_bucket": ov["bucket"],
                                    "original_decision": "REJECT",
                                    "reject_reason": reason,
                                    "size_mult": ov["size_mult"],
                                    "max_hold_s": ov["max_hold_s"],
                                    "tags": ov["tags"],
                                },
                            )
                            log.warning(
                                "[PAPER_EXPLORE_ENTRY] bucket=%s symbol=%s side=%s original_decision=REJECT "
                                "ev=%.4f score=%.3f price=%.8f reason=%s",
                                ov["bucket"], sym, signal.get("action", "BUY"),
                                signal.get("ev", 0.0), signal.get("score", 0.0),
                                entry_price, ov["reason"]
                            )
            except ImportError:
                pass  # Paper exploration not available
            except Exception as e:
                log.debug(f"[PAPER_EXPLORE_ERROR] {e}")

            if not _explored:
                log.info(f"    portfolio gate: {reason}  sym={sym}")
        return

    entry = signal["price"]
    # ATR floor: micro-price coins (NOM $0.0027, KAT $0.012) can have ATR≈0
    # in absolute terms → TP=SL=entry → trade can only close on timeout.
    # Floor at 0.3% of entry ensures minimum meaningful TP/SL distance.
    atr   = max(signal.get("atr", 0) or 0, entry * 0.003)

    # ── V3: quality pre-filter on estimated TP/SL ─────────────────────────────
    atr_pct = atr / max(entry, 1e-9)
    tp_est, sl_est = compute_tp_sl(entry, signal["action"], atr_pct, sym, signal.get("regime", "RANGING"))
    if not _has_min_edge(entry, tp_est, sl_est):
        log.info(f"    portfolio gate: min_edge  sym={sym}  "
              f"tp={abs(tp_est-entry)/entry:.4f}  sl={abs(sl_est-entry)/entry:.4f}")
        return
    _sig_ev = signal.get("ev", 0.0)   # set by RDE evaluate_signal; 0.0 = conservative
    if _reject_bad_rr(entry, tp_est, sl_est, ev=_sig_ev, atr_pct=atr_pct):
        rr  = abs(tp_est - entry) / max(abs(sl_est - entry), 1e-9)
        log.info(f"    portfolio gate: bad_rr  sym={sym}  rr={rr:.2f}")
        return

    # QUIET_RANGE: skip when ATR < 2.5× round-trip fee.
    # With FEE_RT=0.15%, ATR must exceed 0.375% or the fee alone eats the edge.
    # Not bootstrapped — this is a structural market condition, not a learning gate.
    if regime == "QUIET_RANGE":
        _atr_pct = atr / max(entry, 1e-9)
        if _atr_pct < 2.5 * FEE_RT:
            log.info(f"    portfolio gate: quiet_atr_fee  sym={sym}  "
                  f"atr={_atr_pct:.4f}<{2.5*FEE_RT:.4f}")
            return

    # Bootstrap open: bypass staleness/cost gates until 30 closed trades
    try:
        from src.services.learning_event import get_metrics as _lgm
        bootstrap_open = _lgm().get("trades", 0) < 30
    except Exception:
        bootstrap_open = False

    ob = OrderBook.from_price(entry, spread_pct=_SPREAD_PCT)

    sig_ts  = signal.get("timestamp", time.time())
    vol_f   = signal.get("features", {}).get("vol", 0.0)
    tick_ms = max(100, min(500, int(atr / max(entry, 1e-9) * 100_000)))
    if not bootstrap_open and not valid(sig_ts, tick_ms, vol_f):
        log.info(f"    portfolio gate: stale_signal  sym={sym}")
        return

    # ── Mammon-inspired: dual staleness guards ───────────────────────────────
    # Guard A — hard floor: if price moved ≥ 30 bps from signal, always skip.
    #           Catches obvious stale signals regardless of volatility.
    # Guard B — z-score cancel: ATR-normalised drift vs signal distribution.
    #           Regime-adaptive: high-ATR pairs tolerate more absolute movement
    #           before being considered stale; low-ATR pairs are tighter.
    #           z = |cur - sig| / (atr × 0.30); cancel if z ≥ 2.0.
    #           Equivalent to Mammon's brain_stem_mean_dev_cancel_sigma gate
    #           (Brain_Stem/trigger/service.py lines 251-277).
    if not bootstrap_open:
        _STALE_DRIFT    = 0.0030   # 30 bps hard floor (Guard A)
        _CANCEL_Z_SIGMA = 2.0      # z-score cancel threshold (Guard B)
        _MC_NOISE       = 0.30     # ATR fraction = 1-sigma (matches monte_council)
        try:
            from src.services.learning_event import get_metrics as _drift_gm
            _lp  = _drift_gm().get("last_prices", {})
            _cur = _lp.get(sym, 0.0)
            if _cur > 0:
                _drift = abs(_cur - entry) / entry

                # Guard A — fixed bps floor
                if _drift > _STALE_DRIFT:
                    log.info(
                        "    portfolio gate: price_drift  sym=%s  "
                        "sig=%.6f  cur=%.6f  drift=%.2f%%",
                        sym, entry, _cur, _drift * 100,
                    )
                    return

                # Guard B — ATR-normalised z-score cancel
                _sig = atr * _MC_NOISE
                if _sig > 0:
                    _z = abs(_cur - entry) / _sig
                    if _z >= _CANCEL_Z_SIGMA:
                        log.info(
                            "    portfolio gate: mean_dev_cancel  sym=%s  "
                            "sig=%.6f  cur=%.6f  z=%.2f>=%.1f",
                            sym, entry, _cur, _z, _CANCEL_Z_SIGMA,
                        )
                        return
        except Exception:
            pass

    ws_raw = signal.get("ws", 0.5)
    if not bootstrap_open and not pre_cost(ws_raw, FEE_RT):
        log.info(f"    portfolio gate: pre_cost  sym={sym}  ws={ws_raw:.3f}")
        return

    reg    = signal.get("regime", "RANGING")

    # ── V10.9: Feature-weighted quality gate ──────────────────────────────────
    # Blocks trades with insufficient feature confirmation after bootstrap.
    # Score = Σ feature_value × adaptive_weight over 7 boolean features.
    # Gate fires only post-bootstrap (≥30 trades) to avoid deadlock during cold start.
    # MIN_SCORE=3.0: requires at least 3 confirmed features at baseline weight.
    _fw_bools = {k: v for k, v in signal.get("features", {}).items()
                 if isinstance(v, bool)}
    _fw_score = 0.0
    try:
        from src.services.feature_weights import compute_weighted_score as _cws
        _fw_score = _cws(_fw_bools, sym, reg)
    except Exception:
        pass
    from src.services.feature_weights import MIN_SCORE as _FW_MIN
    if not bootstrap_open and _fw_score < _FW_MIN:
        log.info(f"    portfolio gate: fw_score  sym={sym}  "
              f"score={_fw_score:.2f}<{_FW_MIN}  regime={reg}")
        return
    ws_adj = ob_adjust(ws_raw, ob)
    ws_adj = ev_adjust(ws_adj, sym, reg)
    ev     = signal.get("ev", 0.05)

    # RDE already applied sigmoid gate — track force flag for logging only.
    # Force trades suppressed in QUIET_RANGE: market is dead (low ATR, no momentum)
    # so force-trading just produces timeout losses with no edge. The force guard
    # exists to maintain learning data flow — but QUIET_RANGE trades produce only
    # noise (53% timeout rate observed). Better to wait for real conditions.
    force = _force_trade_guard()
    if force and reg == "QUIET_RANGE":
        log.info(f"    portfolio gate: force_quiet  sym={sym}  regime=QUIET_RANGE")
        return

    import math
    from src.services.learning_event           import get_metrics as _gm
    from src.services.realtime_decision_engine import get_ev_threshold, get_ws_threshold
    _t       = _gm().get("trades", 0)
    explore  = signal.get("explore", False) or (random.random() < epsilon())
    af       = min(1.0, max(0.7, signal.get("auditor_factor", 1.0)))

    # ── V10.13: Pre-sizing inputs (coherence, portfolio_pressure) ─────────────
    _coh_v1013 = signal.get("coherence", 1.0)   # set by evaluate_signal V10.12
    _pp_v1013  = 0.0
    _mom_v1013 = 0.0
    _econ_mult_v1013 = signal.get("_economic_size_mult", 1.0)  # PATCH 2: economic gate scaling
    try:
        from src.services.risk_engine import (
            portfolio_pressure as _ppfn,
            portfolio_momentum as _pmfn,
        )
        _pp_v1013  = _ppfn(_positions)
        _mom_v1013 = _pmfn(_positions)
    except Exception:
        pass

    base     = final_size(sym, reg, 0.05 if _t >= 20 else 0.025, _positions, ob,
                          coherence=_coh_v1013,
                          portfolio_pressure=_pp_v1013,
                          economic_size_mult=_econ_mult_v1013)
    if base == 0.0:
        log.info(f"    portfolio gate: exposure_full  sym={sym}")
        return
    thr      = get_ev_threshold()
    ws_thr   = ws_threshold()
    ws_ratio = (ws_adj / ws_thr) if ws_thr > 0 else 1.0
    size     = base * math.sqrt(min(ws_ratio, 2.25)) * af

    # Half-Kelly sizing after 30 trades
    if _t >= 30:
        pf = _gm().get("profit_factor", 1.0)
        wr = _gm().get("winrate", 0.0)
        if 0 < wr < 1.0 and pf > 0:
            rrr = pf * (1.0 - wr) / wr
            if rrr > 0:
                kelly_pct = wr - ((1.0 - wr) / rrr)
                if kelly_pct > 0:
                    half_kelly = max(0.01, min(0.20, kelly_pct / 2.0))
                    size = half_kelly * af

    # ── V10.13: Portfolio momentum sizing multiplier ───────────────────────────
    # Portfolio-level trajectory (not per-signal momentum) modulates size.
    # Positive portfolio momentum → allow slight expansion; negative → trim.
    # Range: momentum=+1 → ×1.20; momentum=-1 → ×0.70 (floor).
    # Applied AFTER Kelly so the trajectory multiplier scales the Kelly fraction,
    # not base — keeps Kelly math intact.
    _pf_mom_mult = max(0.70, 1.0 + 0.20 * _mom_v1013)
    size *= _pf_mom_mult

    # V9: policy_score — continuous size modulation replacing binary ev>thr*1.5→*1.5.
    # momentum proxy: ws_raw normalized to [-1, 1] via (ws-0.5)*2 — ws already
    # aggregates MACD/RSI/EMA signals from signal_generator, so it's the best
    # available momentum estimate without recomputing indicators.
    _wr_ps     = _gm().get("winrate", 0.5) or 0.5
    _momentum  = (ws_raw - 0.5) * 2.0
    _feat_adx  = signal.get("features", {}).get("adx", 0.0)
    _reg_score = 1.0 if _feat_adx > 25 else 0.5

    # ── V10.7: Policy Layer — meta-adaptive EV multiplier ─────────────────────
    # policy_ev = risk_ev × policy_multiplier(meta_mode, alignment, confidence, wr)
    # Replaces raw ev in policy_score so sizing reflects system health context.
    _meta_mode_pol = _meta_state["mode"]
    _conf_pol      = signal.get("confidence", 0.5) or 0.5
    _act_pol       = signal.get("action", "")
    _reg_align     = 0.5   # neutral (RANGING / HIGH_VOL / QUIET_RANGE)
    if (_act_pol == "BUY"  and reg == "BULL_TREND") or \
       (_act_pol == "SELL" and reg == "BEAR_TREND"):
        _reg_align = 1.0   # signal aligned with regime
    elif (_act_pol == "BUY"  and reg == "BEAR_TREND") or \
         (_act_pol == "SELL" and reg == "BULL_TREND"):
        _reg_align = 0.0   # counter-regime signal
    _raw_ev_pol = 0.0
    try:
        from src.services.execution import risk_ev as _rev_pol
        _raw_ev_pol = _rev_pol(sym, reg)
    except Exception:
        pass
    _policy_ev, _pm = _raw_ev_pol, 1.0
    try:
        from src.services.policy_layer import compute_policy_ev as _cev
        _policy_ev, _pm = _cev(_raw_ev_pol, _meta_mode_pol, _reg_align, _conf_pol, _wr_ps)
    except Exception:
        pass

    _pol  = policy_score(_policy_ev, _wr_ps, _momentum, atr_pct, _reg_score)
    size *= max(0.5, min(1.5, 1.0 + _pol))   # clamp: never below 50% or above 150%

    # V10: meta_controller — system-health aggression multiplier.
    # V10 adds volatility param (atr_pct already computed above) and hard 0.0 stop.
    # Applied after Kelly/base sizing; trade_freq from tick-rate window.
    _dd_mc    = _gm().get("drawdown", 0.0)  # BUG FIX: key is "drawdown" not "max_drawdown"
    _sharpe   = _gm().get("sharpe", 0.5)   # BUG FIX: sharpe not in METRICS, use reasonable default
    _recent_n = sum(1 for t in _trades_at_tick if _tick_counter[0] - t <= 100)
    _meta     = meta_controller(_sharpe, _dd_mc, _wr_ps, _recent_n / 100.0,
                                volatility=atr_pct)
    if _meta == 0.0:
        log.info(f"    portfolio gate: meta_hard_stop  DD={_dd_mc:.1%}  sym={sym}")
        return
    size *= _meta

    # ── V10.8: Regime Transition Prediction ───────────────────────────────────
    # Scale new position down if a regime switch is predicted; exit open weak
    # positions already in the transitioning regime (risk_ev < 0.05).
    _pred_reg = reg
    try:
        from src.services.regime_predictor import predicted_regime as _pred_fn
        _pred_reg = _pred_fn(signal, reg, _meta_mode_pol)
    except Exception:
        pass
    if _pred_reg != reg:
        size *= 0.85
        log.info(f"    regime_pred[v10.8]: {reg}→{_pred_reg}  size×0.85")
        for _psym, _ppos in list(_positions.items()):
            if (_ppos.get("signal", {}).get("regime", "") == reg
                    and _ppos.get("risk_ev", 0.0) < 0.05):
                rotate_position(_psym)
                log.info(f"    regime_pred[v10.8]: weak exit  sym={_psym}  ev<0.05")

    # ── V10.5: Correlation size penalty ──────────────────────────────────────
    # Spec chain: cluster_penalty → max_pos cap → …
    # Applied BEFORE max_pos so the cap sees already-penalised size.
    # Soft multiplier [0.70, 1.0] — complements correlation_shield hard block.
    _corr_penalty = 1.0
    try:
        from src.services.execution import correlation_size_penalty as _csp
        _corr_penalty = _csp(sym, signal.get("action", ""), _positions)
    except Exception:
        pass
    if _corr_penalty < 1.0:
        size *= _corr_penalty
        log.info(f"    corr_penalty[v10.5]: ×{_corr_penalty:.2f}  sym={sym}")

    # ── V10.8: Adaptive max position cap ──────────────────────────────────────
    # Spec chain: cluster_penalty → max_pos cap (this block).
    # defensive / HIGH_VOL → 0.70×base; aggressive + trend → 1.30×base.
    _max_pos = base
    try:
        from src.services.policy_layer import adaptive_max_pos as _amp
        _max_pos = _amp(base, _meta_mode_pol, _pred_reg)
    except Exception:
        pass
    if size > _max_pos:
        log.info(f"    max_pos[v10.8]: {size:.4f}→{_max_pos:.4f}  "
              f"mode={_meta_mode_pol}  pred={_pred_reg}")
        size = _max_pos

    # ── V10.12: Portfolio risk budget constraint ───────────────────────────────
    # Correlation-aware marginal VaR ensures the new position fits within the
    # remaining risk budget without breaching the per-regime allocation.
    # Uses estimated SL (tp_est/sl_est computed earlier from atr_pct) so no
    # additional computation is needed — sl_pct is already available here.
    # corr_size_factor() replaces the count-based correlation_size_penalty()
    # with a regime-aware version that includes a hedge bonus (opposite dir →
    # 1.10×) and a heavier same-regime penalty (same dir + same reg → 0.60×).
    _sl_pct_rb = abs(sl_est - entry) / max(entry, 1e-9)
    try:
        from src.services.risk_engine import (
            apply_risk_budget as _arb,
            corr_size_factor  as _csf,
            risk_report       as _rrpt,
        )
        # Regime-aware correlation factor (supplement to existing corr_penalty)
        _csf_mult  = _csf(signal.get("action", ""), reg, _positions)
        _size_pre  = size
        size      *= _csf_mult
        # Budget constraint — quadratic solve for max size within var cap
        size       = _arb(size, _sl_pct_rb, signal.get("action", ""), reg, _positions)
        if size < _size_pre * 0.95:   # log only when meaningfully constrained
            _rb  = _rrpt(_positions)
            log.info(f"    risk_engine[v10.12]: {_size_pre:.4f}→{size:.4f}  "
                  f"csf×{_csf_mult:.2f}  "
                  f"budget_used={_rb.get('budget_used_pct', 0):.1%}  "
                  f"regime={reg}")
    except Exception:
        pass

    # ── V10.8: Policy-scaled partial TP multiplier ────────────────────────────
    # healthy system (pm>1) → fires later (let winners run);
    # defensive (pm<1) → fires earlier (lock gains sooner). Stored in position.
    _partial_tp_mult = 1.5
    try:
        from src.services.policy_layer import scaled_partial_tp as _stp
        _partial_tp_mult = _stp(1.5, _pm)
    except Exception:
        pass

    _repl_flag  = signal.get("_is_replacement", False)
    _coh_log    = signal.get("coherence", 1.0)
    _efficiency = 0.0   # computed post-exec at line ~1507; pre-log placeholder
    log.info(f"    policy[v10.7/10.8/v10.9/v10.10/v10.12/v10.13]: "
          f"mode={_meta_mode_pol}  pm={_pm:.3f}  "
          f"policy_ev={_policy_ev:.4f}  risk_ev={_raw_ev_pol:.4f}\n"
          f"     fw={_fw_score:.2f}  pred={_pred_reg}  max_pos={_max_pos:.4f}  "
          f"ptp×={_partial_tp_mult:.2f}  corr×={_corr_penalty:.2f}  sxd=False\n"
          f"     eff={_efficiency:.4f}  eff_live={_efficiency:.4f}  "
          f"repl={_repl_flag}  coh={_coh_log:.3f}\n"
          f"     pp={_pp_v1013:.3f}  mom={_mom_v1013:.3f}  "
          f"mom_mult×{_pf_mom_mult:.2f}")

    # V10.1: confidence → size coupling.
    # signal.confidence is from signal_generator (penalised by HIGH_VOL×0.5,
    # counter-trend×0.6, weak-EMA×0.7, session-quality×0.85-1.0).
    # Normalize to 0.5 baseline so average-quality signal = 1.0× (no change):
    #   confidence=0.5 → 1.0×   neutral
    #   confidence=0.3 → 0.6×   weak signal: trim exposure
    #   confidence=0.7 → 1.2×   strong signal: slight boost (capped)
    #   confidence=0.25 → 0.5×  floor
    # Bootstrap-safe: most early signals have confidence≈0.5 → multiplier≈1.0×.
    # Spec formula (confidence×size) NOT used — it halves every typical signal
    # since confidence<1 for all practical inputs. Normalized version preserves
    # expected sizing behaviour while enabling differentiation.
    _conf = signal.get("confidence", 0.5) or 0.5
    size *= max(0.5, min(1.2, _conf / 0.5))

    if explore:
        size *= 0.3
    size = _vol_adjust(size, signal)
    size = size_floor(size)
    size = final_size_meta(size)
    # V10.3: realized-vol refinement — stable symbols get slightly more capital,
    # high-vol symbols get slightly less; bounded [0.7×, 1.3×], bootstrap-safe
    size *= volatility_adjustment(sym)

    # V10.12e: Apply unblock size multiplier from decision engine
    # Reduce position size during unblock mode to bound risk: 0.25x critical, 0.35x lighter
    _ub_mult = signal.get("unblock_size_mult", 1.0)
    if _ub_mult < 1.0:
        size *= _ub_mult
        log.info(f"    unblock_size[v10.12e]: ×{_ub_mult:.2f}  fallback={signal.get('unblock_fallback', False)}")

    # Regime WR penalty: if a regime has <40% WR after 20+ trades, halve size.
    # Hard block if WR < 35% after 25+ trades — bootstrap safety: fresh DB
    # needs enough data before regime blocks fire.
    # Self-adaptive — no hardcoded regime names.
    # Penalty/block lifts automatically if WR improves above threshold.
    try:
        _reg_stats = _gm().get("regime_stats", {}).get(reg, {})
        _reg_n  = _reg_stats.get("trades", 0)
        _reg_wr = _reg_stats.get("winrate", 1.0)
        if _reg_n >= 25 and _reg_wr < 0.35:
            log.info(f"    regime BLOCK  regime={reg}  wr={_reg_wr:.1%}  n={_reg_n}")
            return  # BUG FIX: return (not return None) for clarity
        elif _reg_n >= 20 and _reg_wr < 0.40:
            size *= 0.5
            log.info(f"    regime penalty x0.5  regime={reg}  wr={_reg_wr:.1%}  n={_reg_n}")
    except Exception:
        pass

    # Micro-cap penalty: coins priced below $0.01 (NOM $0.0027, etc.) have
    # near-zero absolute ATR → exits dominated by timeouts → all PnL is noise.
    # Cap position size at 25% of normal to limit per-trade damage while the
    # system still collects learning data from these pairs.
    _price = signal.get("price", 1.0) or 1.0
    if _price < 0.01:
        size *= 0.25
        log.info(f"    micro-cap penalty x0.25  price={_price:.6f}  sym={sym}")

    ctrl = failure_control(_positions)
    if ctrl == 0.0:
        log.info(f"    portfolio gate: failure_halt  sym={sym}  mode={bootstrap_mode()}")
        return
    size *= ctrl

    # ── V10.11: Execution Quality Layer ──────────────────────────────────────
    # Applied last in sizing chain — after all EV/policy/risk multipliers.
    # Only hard block: extreme spread (> 0.15%). Everything else is a penalty.
    try:
        from src.services.execution_quality import exec_quality_score as _eqs
        _eq = _eqs(sym, signal.get("action", "BUY"), entry, atr_pct, ob)
        if _eq["skip"]:
            log.info(f"    exec_quality[v10.11]: SKIP_SPREAD  "
                  f"spread={_eq['spread']:.4f}>{0.0015:.4f}  sym={sym}")
            return
        _eq_mult = _eq["exec_quality"]
        if _eq_mult < 1.0:
            size *= _eq_mult
        log.info(f"    exec_quality[v10.11]: "
              f"exec_q={_eq_mult:.2f} spread={_eq['spread']:.4f} "
              f"slip={_eq['slip']:.4f} fill={_eq['fill']:.2f} "
              f"lat={_eq['lat']:.2f}")
    except Exception as _eq_exc:
        log.info(f"    exec_quality[v10.11]: skipped ({_eq_exc})")

    # ── V11.0: Fail-Safe Guard Checks ─────────────────────────────────────────
    # 1. System Level Check (hard stop blocks all new trades)
    if guard.hard_stop:
        log.warning(f"    [HALT] SystemGuard Hard Stop active — blocking trade {sym}")
        return

    # 2. Hard Invariants (NaN, negative size) — checked BEFORE exec_quality
    #    so we never pass a corrupted size into the order book simulation.
    if not guard.check_trade_invariants(sym, size, entry, tp_est, sl_est):
        log.error(f"    [HARD_FAIL] Invariant breach for {sym} — halting system.")
        return

    # 3. Sizing Escalation: DEGRADE mode (0.5×) applied here, before exec_quality,
    #    so exec_quality sees the already-degraded size and doesn't double-penalize.
    size *= guard.get_size_multiplier()

    edge = net_edge(ws_adj, size, ob, FEE_RT, sym)
    if not cost_guard_bootstrap(edge):
        log.info(f"    portfolio gate: cost_guard  sym={sym}  "
              f"edge={edge:.4f}  mode={bootstrap_mode()}")
        return

    # ── V10.12b: Portfolio Risk Budget ────────────────────────────────────────
    # Applied after all sizing multipliers and quality/cost checks.
    # Only block: portfolio heat limit (total notional exposure cap).
    try:
        from src.services.risk_engine import (
            portfolio_risk_budget as _prb,
            heat_limit_ok         as _hlo,
        )
        _rb_res = _prb(_positions)
        _rb     = _rb_res["risk_budget"]

        if not _hlo(_positions, _rb):  # existing positions only; incoming size capped by VaR above
            log.info(f"    risk_budget[v10.12c]: HEAT_LIMIT  sym={sym}  "
                  f"risk={_rb:.2f}")
            return

        if _rb < 1.0:
            size *= _rb
            # _max_pos intentionally NOT scaled: recycling gate has its own dd<12% guard

        log.info(f"    risk_budget[v10.12c]: "
              f"risk={_rb:.2f} dd={_rb_res['dd']:.3f} "
              f"sharpe={_rb_res['sharpe']:.2f} ruin={_rb_res['ruin']:.3f} "
              f"heat={_rb_res['heat']:.4f} max_heat={_rb_res['max_heat']:.4f}")
    except Exception as _rb_exc:
        log.info(f"    risk_budget[v10.12b]: skipped ({_rb_exc})")

    # ── Execution ─────────────────────────────────────────────────────────────
    actual_entry, fill_slip, actual_fee_rt = exec_order(signal, size, ob, sym)
    actual_entry = actual_entry or entry

    actual_atr = max(signal.get("atr", 0) or 0, actual_entry * 0.003) / actual_entry if actual_entry else 0.003
    tp, sl = compute_tp_sl(actual_entry, signal["action"], actual_atr, sym, signal.get("regime", "RANGING"))

    # ────────────────────────────────────────────────────────────────────────
    # PATCH 4 + ZERO BUG V2: Execution Debug — Log TP/SL levels for runtime verification
    # ────────────────────────────────────────────────────────────────────────
    msg = f"[EXEC] regime={regime} TP={tp:.5f} SL={sl:.5f}"
    get_event_bus().emit("LOG_OUTPUT", {"message": msg}, time.time())
    
    log.info(f"[EXEC] regime={regime} entry={actual_entry:.8f} TP={tp:.8f} SL={sl:.8f} "
             f"size={size:.6f} atr={signal.get('atr', 0):.8f}")

    # Record tick for force-trade rate tracking
    _trades_at_tick.append(_tick_counter[0])
    if len(_trades_at_tick) > 200:
        del _trades_at_tick[:-200]

    # V10.4: capture risk_ev at open time for position_score() comparisons
    _ev_open = 0.0
    try:
        from src.services.execution import risk_ev as _rev_open
        _ev_open = _rev_open(sym, signal.get("regime", "RANGING"))
    except Exception:
        pass

    # V10.10: expected hold time + efficiency at open
    # Re-uses dynamic_hold + dynamic_hold_extension (same as on_price timeout logic)
    # so efficiency = policy_ev per expected tick of capital lock-up.
    _adx_open10   = signal.get("features", {}).get("adx", 0.0)
    _hold_base10  = _dynamic_hold(atr, actual_entry, sym, reg, adx=_adx_open10)
    _expected_hold = dynamic_hold_extension(_hold_base10, _ev_open, atr, actual_entry)
    _efficiency    = _policy_ev / max(_expected_hold, 1e-6)

    # V10.10/V10.13: capital recycling bonus — disabled under portfolio stress.
    # Recycling ×1.1 only fires when:
    #   - replaced position closed profitably (move ≥ 0)
    #   - portfolio_pressure < 0.50  (not in stress regime)
    #   - portfolio_momentum ≥ -0.30 (trajectory not actively worsening)
    #   - drawdown < 12%            (not in defensive mode)
    _recycling_pnl = signal.get("_recycling_pnl", None)
    _dd_recycle    = _gm().get("drawdown", 0.0)  # BUG FIX: key is "drawdown" not "max_drawdown"
    _recycle_ok    = (
        _recycling_pnl is not None
        and _recycling_pnl >= 0
        and _pp_v1013 < 0.50
        and _mom_v1013 >= -0.30
        and _dd_recycle < 0.12
    )
    if _recycle_ok:
        size = min(size * 1.1, _max_pos)
        log.info(f"    recycle[v10.10/v10.13]: ×1.1  prev_move={_recycling_pnl*100:.2f}%"
              f"  pp={_pp_v1013:.2f}  mom={_mom_v1013:.2f}  size→{size:.4f}")
    elif _recycling_pnl is not None and _recycling_pnl >= 0:
        log.info(f"    recycle[v10.13/BLOCKED]: pp={_pp_v1013:.2f}  "
              f"mom={_mom_v1013:.2f}  dd={_dd_recycle:.1%}  → no bonus")

    # ────────────────────────────────────────────────────────────────────────
    # V10.12d: Unblock mode rate limiting check
    # ────────────────────────────────────────────────────────────────────────
    _in_unblock = is_unblock_mode_trade()
    if _in_unblock:
        _can_open, _reason = can_open_unblock_trade()
        if not _can_open:
            log.warning(f"[UNBLOCK_LIMIT] {sym} {_reason} — signal skipped")
            return  # BUG FIX: return (not return None) for consistency
        record_unblock_trade()
    
    # ────────────────────────────────────────────────────────────────────────
    # PATCH 6: Track Last Trade Timestamp
    # ────────────────────────────────────────────────────────────────────────
    try:
        import bot2.main as bot2_main
        bot2_main.last_trade_ts[0] = time.time()
    except Exception:
        pass

    # ── V11: Capture learning state and decision context at trade open ──
    learning_at_open = {}
    decision_engine_context = {}
    adaptive_zones_at_open = {}
    try:
        from src.services.learning_monitor import get_learning_state
        learning_at_open = get_learning_state() or {}
    except Exception:
        pass

    try:
        from src.services.realtime_decision_engine import get_last_decision_context
        decision_engine_context = get_last_decision_context(sym) or {}
    except Exception:
        pass

    try:
        from src.optimized.mtf_filter import get_zone_snapshot
        adaptive_zones_at_open = get_zone_snapshot(sym) or {}
    except Exception:
        pass

    # V10.13u+20: Route to paper trading if in paper mode
    if is_paper_mode():
        _paper_result = open_paper_position(signal, actual_entry, time.time(), "RDE_TAKE")
        if _paper_result.get("status") == "opened":
            log.warning(
                f"[PAPER_ROUTED] symbol={sym} side={signal['action']} "
                f"price={actual_entry:.8f} ev={signal.get('ev', 0):.4f}"
            )
        else:
            log.warning(
                f"[PAPER_BLOCKED] symbol={sym} reason={_paper_result.get('reason', 'unknown')}"
            )
        return  # Paper trades managed separately; do not open in live positions dict

    # V10.13u+20: Verify live trading is allowed before opening real orders
    if not live_trading_allowed():
        log.warning(
            f"[LIVE_ORDER_DISABLED] symbol={sym} mode check failed "
            f"(TRADING_MODE required, real orders disabled)"
        )
        return

    with _positions_lock:
        _positions[sym] = {
            "action":        signal["action"],
            "entry":         actual_entry,
            "size":          size,
            "tp":            tp,
            "sl":            sl,
            "tp_move":       abs(tp - actual_entry) / actual_entry,
            "sl_move":       abs(sl - actual_entry) / actual_entry,
            "open_regime":   regime,  # V10.14: Freeze regime at open time
            "signal":        signal,
            "ticks":         0,
            "fill_slippage": fill_slip,
            "fee_rt":        actual_fee_rt,
            "trail_price":   actual_entry,
            "max_price":     actual_entry,
            "min_price":     actual_entry,
            "is_trailing":   False,
            "partial_taken": False,   # True after partial TP exit fires
            "realized_pnl":  0.0,    # accumulated profit from partial exits
            "risk_ev":       _ev_open,  # V10.4: stored for position_score comparisons
            "open_ts":       time.time(),  # V10.4b: for time-decay in position_score
            "live_pnl":      0.0,    # V10.4b: updated each tick for profit protection
            "original_size": size,   # V10.5: pyramid cap — total size ≤ 2× this
            "adds":          0,      # V10.5: number of scale-ins so far (max 2)
            "reduced":       False,  # V10.5: True once de-risk cut has fired
            "policy_mult":      _pm,               # V10.7: policy multiplier at open
            "partial_tp_mult":  _partial_tp_mult,  # V10.8: scaled TP ATR multiplier
            "pred_regime":      _pred_reg,         # V10.8: predicted regime at open
            "soft_exit_done":   False,             # V10.8: one-shot soft preemptive exit
            "fw_score":         _fw_score,         # V10.9: feature-weighted score at open
            "efficiency":       _efficiency,       # V10.10: EV / expected_hold at open
            "efficiency_live":  _efficiency,       # V10.10: decays each tick (exp decay)
            "expected_hold":    _expected_hold,    # V10.10: hold ticks used as decay tau
            "unblock_mode":     _in_unblock,       # V10.12d: True if trade opened in unblock mode

            # V11: Learning and decision context at open
            "learning_at_open": learning_at_open,
            "decision_engine": decision_engine_context,
            "adaptive_zones_at_open": adaptive_zones_at_open,
        }
        _sync_regime_exposure()   # Fix 5: recount from positions to prevent drift
    tag = "[force]" if force else ""
    msg = (f"    exec{tag}: slip={fill_slip:.5f}  fee={actual_fee_rt:.5f}  fr={fill_rate(sym):.2f}  "
           f"ws_adj={ws_adj:.3f}  {size:.4f}@{actual_entry:.4f}  "
           f"tp={tp:.4f}  sl={sl:.4f}")
    get_event_bus().emit("LOG_OUTPUT", {"message": msg}, time.time())
    _risk_guard()

    # ── V10.14: Record the open for deduplication tracking ────────────────────
    try:
        from src.services.candidate_dedup import record_open
        record_open(signal)
    except Exception as e:
        log.debug(f"[DEDUP_RECORD_FAIL] {e}")

    # V10.10: portfolio efficiency snapshot (diagnostic — not persisted)
    if _positions:
        _pf_ev_sum  = sum(p.get("efficiency", 0.0) * max(p.get("expected_hold", 1.0), 1e-6)
                          for p in _positions.values())
        _pf_sz_sum  = sum(p["size"] * max(p.get("expected_hold", 1.0), 1e-6)
                          for p in _positions.values())
        _pf_eff     = _pf_ev_sum / max(_pf_sz_sum, 1e-9)
        log.info(f"    portfolio[v10.10]: positions={len(_positions)}  "
              f"portfolio_efficiency={_pf_eff:.4f}")


def on_price(data):
    # V10.13u+20: Update paper positions before live position handling
    if is_paper_mode():
        _symbol_prices = {data["symbol"]: data["price"]}
        _closed_papers = update_paper_positions(_symbol_prices, time.time())
        if _closed_papers:
            # Process closed paper trades for learning
            for _closed_trade in _closed_papers:
                _save_paper_trade_closed(_closed_trade)

    if time.time() - _last_flush[0] >= FLUSH_EVERY and BATCH:
        _flush()

    # BUG FIX: Start latency timer AFTER flush to measure only trade logic, not I/O
    _t_start = time.perf_counter()

    _tick_counter[0] += 1   # global tick — drives force_trade_guard rate

    sym = data["symbol"]
    with _positions_lock:
        if sym not in _positions:
            return
        pos = _positions[sym]
    pos["ticks"] += 1
    curr  = data["price"]
    entry = pos["entry"]

    move = (curr - entry) / entry
    if pos["action"] == "SELL":
        move *= -1

    # V10.4b: keep live_pnl fresh so should_replace profit protection is accurate
    pos["live_pnl"] = move

    # V10.10: live efficiency decay — exp(-t/tau) where tau = expected_hold ticks.
    # As the trade ages past its expected duration its efficiency value drops,
    # making it a natural candidate for replacement by fresher opportunities.
    _t_alive = time.time() - pos.get("open_ts", time.time())
    _tau10   = max(pos.get("expected_hold", 10.0), 1e-6)
    pos["efficiency_live"] = pos.get("efficiency", 0.0) * math.exp(-_t_alive / _tau10)

    # V10.13: record portfolio PnL snapshot every 5 ticks (sampled, not every tick)
    # to keep _pf_pnl_hist dense enough for OLS slope without excessive overhead.
    _pf_tick_counter[0] += 1
    if _pf_tick_counter[0] % 5 == 0 and _positions:
        try:
            from src.services.risk_engine import record_portfolio_pnl as _rpf
            _rpf(_positions)
        except Exception:
            pass

    # MAE / MFE tracking
    if curr > pos["max_price"]: pos["max_price"] = curr
    if curr < pos["min_price"]: pos["min_price"] = curr

    # Trail price tracking
    if pos["action"] == "BUY" and curr > pos["trail_price"]:
        pos["trail_price"] = curr
    elif pos["action"] == "SELL" and curr < pos["trail_price"]:
        pos["trail_price"] = curr

    # Activate trailing stop at +0.60% profit
    if not pos["is_trailing"] and move >= 0.006:
        pos["is_trailing"] = True
        log.info(f"    🚀 {sym} TRAILING STOP ACTIVOVÁN! Zisk: {move*100:.2f}%")

    # ── V10.8: Soft preemptive exit — de-risk on predicted regime transition ──
    # Fires once when the regime is predicted to change AND position gain is
    # small (< 0.15×ATR) — not worth waiting in a transitioning market.
    # Reduces size 50% to lock partial value; guarded by soft_exit_done flag.
    # Skipped when already partial-taken, reduced, or trailing (those handlers
    # manage sizing independently and must not be double-cut).
    if not pos.get("soft_exit_done") and not pos.get("partial_taken") \
            and not pos.get("reduced") and not pos.get("is_trailing"):
        _reg_op   = pos.get("signal", {}).get("regime", "RANGING")
        _pred_soft = _reg_op
        try:
            from src.services.regime_predictor import predicted_regime as _pf
            _pred_soft = _pf(pos["signal"], _reg_op, _meta_state["mode"])
        except Exception:
            pass
        if _pred_soft != _reg_op:
            _atr_soft     = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
            _atr_pct_soft = _atr_soft / max(entry, 1e-9)
            if move < 0.15 * _atr_pct_soft:   # small gain — not worth holding
                pos["size"]          *= 0.5
                pos["soft_exit_done"] = True
                _risk_guard()
                log.info(f"    🔀 {sym.replace('USDT','')} SOFT_EXIT 50%  "
                      f"{_reg_op}→{_pred_soft}  move={move*100:.2f}%")

    # ── Partial TP: exit 50% at scaled×ATR profit, move SL to breakeven ──────
    # V10.8: threshold = partial_tp_mult × ATR (stored at open, driven by pm).
    # Higher pm (healthy/aggressive) → fires later; lower pm (defensive) → sooner.
    # Research (Mind Math Money / Semantic Scholar): partial scale-out at an
    # intermediate target is "the most practical approach" — locks in real gains
    # while preserving upside on the remaining half. Directly reduces timeouts:
    # positions that reach the threshold then reverse now book 50% of that gain
    # instead of timing out at zero. After partial exit, SL moves to entry
    # (breakeven) — remaining half is risk-free. Chandelier trail continues.
    # Apply the same ATR floor as compute_tp_sl (entry×0.003 minimum).
    # Without the floor, raw tick-level ATR (e.g. 0.00006 for ADA at $0.25) makes
    # the threshold ~0.036% — partial TP fires on noise before fees are covered.
    _atr_partial  = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
    _fee_p        = pos.get("fee_rt", FEE_RT)
    _ptp_mult     = pos.get("partial_tp_mult", 1.5)
    if not pos.get("partial_taken") and move >= _ptp_mult * (_atr_partial / max(entry, 1e-9)) and move > _fee_p:
        partial = (move - _fee_p) * pos["size"] * 0.5
        pos["partial_taken"] = True
        pos["realized_pnl"]  = pos.get("realized_pnl", 0.0) + partial
        pos["size"]         *= 0.5
        pos["sl"]            = entry   # breakeven: remaining half is now risk-free
        _short_p = sym.replace("USDT", "")
        log.info(f"    📦 {_short_p} PARTIAL TP 50%  "
              f"pnl={partial:+.6f}  move={move*100:.2f}%  SL→breakeven")

    # V10.5b: position scaling — pyramid winners / de-risk losers
    # Runs after partial TP (which can change size/sl) but before exit checks.
    _prev = pos.get("prev_price", curr)   # price from previous tick (neutral on tick 1)
    if should_add_to_position(pos, curr, _prev):
        add_to_position(pos, curr)
        entry = pos["entry"]   # refresh local var — exit math must use blended entry
        short_p = sym.replace("USDT", "")
        log.info(f"    📈 {short_p} PYRAMID add#{pos['adds']}  "
              f"size={pos['size']:.4f}  avg_entry={entry:.4f}  move={move*100:.2f}%")
    if should_reduce_position(pos, curr):
        reduce_position(pos, curr)
        short_p = sym.replace("USDT", "")
        log.info(f"    ✂️  {short_p} REDUCE  "
              f"size={pos['size']:.4f}  move={move*100:.2f}%  ev={pos.get('risk_ev',0):.3f}")

    # V10.2: adaptive SL tightening — protect profits in pre-trail window (0.3%-0.6%)
    # Not applied during trailing (Chandelier owns the stop; pos["sl"] not read)
    if not pos["is_trailing"]:
        _atr_tighten = max(pos["signal"].get("atr", 0) or 0, entry * 0.003)
        pos["sl"] = adaptive_sl_tightening(
            entry, curr, pos["sl"], pos["action"], _atr_tighten)

    # ── Exit conditions ────────────────────────────────────────────────────────
    reason = None
    atr = pos["signal"].get("atr", entry * 0.003)

    # Chandelier exit: highest_high - 2×ATR (BUY) / lowest_low + 2×ATR (SELL)
    # Research: ATR-based Chandelier exit outperforms fixed TP in volatile regimes
    # (Semantic Scholar peer-reviewed study). It expands in high-vol allowing trades
    # to breathe, and contracts in low-vol locking in gains — superior to a fixed
    # trail_price offset that doesn't adapt to volatility changes during the trade.
    # Uses max_price/min_price already tracked in the position dict.
    # Multiplier 2.0×ATR: tighter than 3× (standard) to suit short 1m timeframes.
    chandelier_atr_mult = 2.0
    if pos["action"] == "BUY":
        chandelier_stop = pos["max_price"] - chandelier_atr_mult * atr
    else:
        chandelier_stop = pos["min_price"] + chandelier_atr_mult * atr

    if pos.get("force_close"):
        reason = "replaced"
    elif pos["is_trailing"]:
        # Chandelier exit: uses highest_high/lowest_low since entry rather than
        # last tick trail_price — gives more room in trending moves, still cuts
        # quickly if price reverses sharply from the peak/trough
        if pos["action"] == "BUY"  and curr <= chandelier_stop:
            reason = "TRAIL_SL"
        elif pos["action"] == "SELL" and curr >= chandelier_stop:
            reason = "TRAIL_SL"
    else:
        # V3 BUG FIX: pos["tp"] was stored but never checked — TP exits never fired.
        # Added explicit TP check before SL and removed the TP_FALLBACK (>10%) crutch.
        if   pos["action"] == "BUY"  and curr >= pos["tp"]: reason = "TP"
        elif pos["action"] == "SELL" and curr <= pos["tp"]: reason = "TP"
        elif pos["action"] == "BUY"  and curr <= pos["sl"]: reason = "SL"
        elif pos["action"] == "SELL" and curr >= pos["sl"]: reason = "SL"

    # ── L2 sell/buy wall exit — proactive exit before order book barrier ─────
    # Fires only when position is already profitable (move ≥ 0.10%) to avoid
    # noise-triggered exits in flat/losing trades.  Detects when a massive
    # opposite-side wall sits within WALL_BAND_PCT (0.3%) of current price:
    #   BUY  position + sell wall above  → exit before wall caps upside
    #   SELL position + buy wall below   → exit before wall caps downside
    # Skipped when trailing stop is already active (Chandelier owns the exit).
    # Skipped post-partial-taken: SL already at breakeven, risk is minimal.
    if reason is None and not pos["is_trailing"] and not pos.get("partial_taken"):
        try:
            from src.services.order_book_depth import (
                is_sell_wall, is_buy_wall, MIN_PROFIT_TO_EXIT)
            if pos["action"] == "BUY" and move >= MIN_PROFIT_TO_EXIT:
                if is_sell_wall(sym, curr):
                    reason = "wall_exit"
                    log.info(f"    🧱 {sym.replace('USDT','')} SELL_WALL detected  "
                          f"move={move*100:.2f}%  → proactive exit")
            elif pos["action"] == "SELL" and move >= MIN_PROFIT_TO_EXIT:
                if is_buy_wall(sym, curr):
                    reason = "wall_exit"
                    log.info(f"    🧱 {sym.replace('USDT','')} BUY_WALL detected  "
                          f"move={move*100:.2f}%  → proactive exit")
        except Exception:
            pass

    # V9 early exit: negative-EV pair that is losing → don't hold to full timeout.
    # V11.0: switched from tick-count (pos["ticks"] >= 5) to time-based (>= 30s)
    # to match V10.14 time-based timeout model. 30s ensures spread + fees are
    # absorbed before early-exit fires — prevents noise exits in first seconds.
    if reason is None and move < -0.002 and (time.time() - pos["open_ts"]) >= 30 \
            and not pos.get("partial_taken"):
        try:
            from src.services.execution import risk_ev as _rev
            if _rev(sym, pos["signal"].get("regime", "RANGING")) < -0.1:
                reason = "early_exit"
        except Exception:
            pass

    # 🚀 V5.1 SMART EXIT ENGINE: Check active profit-taking/loss-cutting FIRST
    # Only fallback to timeout if no smart exit condition met
    if reason is None:
        try:
            from src.services.smart_exit_engine import evaluate_position_exit

            age_seconds = int(time.time() - pos["open_ts"])
            # V10.13f: direction from action (not current move) + pass peak MFE
            _direction = "LONG" if pos["action"] == "BUY" else "SHORT"
            _mfe = ((pos["max_price"] - entry) / entry if pos["action"] == "BUY"
                    else (entry - pos["min_price"]) / entry)
            exit_eval = evaluate_position_exit(
                symbol=sym,
                entry_price=entry,
                tp=pos.get("tp", entry),
                sl=pos.get("sl", entry),
                current_price=curr,
                age_seconds=age_seconds,
                direction=_direction,
                max_favorable_move=max(0.0, _mfe),
                # V10.13k: pass regime so micro-TP threshold is regime-adaptive
                regime=pos["signal"].get("regime"),
            )

            if exit_eval:
                # V10.13k fix: preserve uppercase — learning_event + bot2 counters
                # use uppercase keys (MICRO_TP, SCRATCH_EXIT…). .lower() was silently
                # zeroing all smart-exit counters while trades DID close correctly.
                reason = exit_eval.get("exit_type", "SMART_EXIT")
                log.info(f"    🔥 Smart exit: {reason} | {exit_eval.get('reason')}")
        except Exception as e:
            log.debug(f"Smart exit check failed: {e}")
            # V10.13L: Mark runtime fault for critical module
            try:
                from src.services.runtime_fault_registry import mark_fault
                mark_fault("smart_exit_engine", f"Exception in evaluate_position_exit: {e}")
            except Exception:
                pass

    # Timeout fallback (V10.14): if no smart exit, use time-based timeout
    _adx_sig = pos["signal"].get("features", {}).get("adx", 0.0)
    _reg_hold = pos["signal"].get("regime", "RANGING")
    timeout   = _dynamic_hold(atr, entry, sym, _reg_hold, adx=_adx_sig)
    # V10.3: extend/shorten hold based on live edge quality
    _ev_hold  = 0.0
    try:
        from src.services.execution import risk_ev as _rev_h
        _ev_hold = _rev_h(sym, _reg_hold)
    except Exception:
        pass
    timeout = dynamic_hold_extension(timeout, _ev_hold, atr, entry)
    # V10.14: switched from tick-based to time-based timeout calculation.
    # pos["ticks"] remains for diagnostics; exit uses absolute session time.
    if reason is None and (time.time() - pos["open_ts"]) >= timeout:
        # V10.13f: classify timeout by PnL state for diagnostics
        if move > 0.001:
            reason = "TIMEOUT_PROFIT"
        elif move >= -0.001:
            reason = "TIMEOUT_FLAT"
        else:
            reason = "TIMEOUT_LOSS"

    # V10.5b: store current price as prev for next tick's momentum check
    pos["prev_price"] = curr

    if reason is None:
        return

    # V10.13u+14 Phase 2: Partial TP hard bypass - BEFORE lock acquisition
    # Partial TPs must never enter full close lock path
    if reason in PARTIAL_CLOSE_TYPES:
        log.warning(f"[PARTIAL_TP_BYPASS_FULL_CLOSE] {sym} reason={reason} path=partial_only")
        # Partial TP: reduce size, book pnl, don't remove position or acquire lock
        # TODO Phase 2: Extract partial TP logic into _handle_partial_tp_only()
        return None

    # V10.13u+11: Reentrant close guard with TTL-based recovery
    acquired, close_key, close_lock_status = _try_acquire_close_lock(sym, pos, reason)
    if not acquired:
        return None

    _close_stage(sym, close_key, "lock_acquired")
    get_event_bus().emit("LOG_OUTPUT", {"message": f"[CLOSE_LOGIC_START] {sym} reason={reason} entering close logic"}, time.time())

    fee_used           = pos.get("fee_rt", FEE_RT)
    _realized_pnl_val  = pos.get("realized_pnl", 0.0)
    _pnl_result        = canonical_close_pnl(
        symbol=sym, side=pos["action"],
        entry_price=entry, exit_price=curr,
        size=pos["size"], fee_rate=fee_used,
        slippage_rate=pos.get("fill_slippage", 0.0),
        prior_realized_pnl=_realized_pnl_val,
    )
    profit = _pnl_result["net_pnl"]
    result   = "WIN" if profit > 0 else "LOSS"
    short    = sym.replace("USDT", "")
    icon     = "✅" if result == "WIN" else "❌"

    # V10.13u+7: Apply churn cooldown after stagnation loss
    if reason == "STAGNATION_EXIT" and result == "LOSS":
        try:
            from src.services.realtime_decision_engine import add_churn_cooldown
            direction = "SHORT" if pos["action"] == "SELL" else "LONG"
            add_churn_cooldown(sym, direction)
        except Exception as e:
            log.debug(f"[CHURN_COOLDOWN] Add cooldown failed for {sym}: {e}")

    # BUG FIX: Removed duplicate direct print (was logging trade twice)
    # Keep only event_bus emit for single log entry
    msg = (f"    {icon} {short} {pos['action']} "
           f"${entry:,.4f}→${curr:,.4f}  {profit:+.6f}  [{reason}] (fee: {fee_used:.5f})")
    get_event_bus().emit("LOG_OUTPUT", {"message": msg}, time.time())
    get_event_bus().emit("LOG_OUTPUT", {"message": f"[CLOSE_LOGIC_MSG_SENT] {sym} reason={reason} before notifier"}, time.time())

    mfe = ((pos["max_price"] - entry) / entry if pos["action"] == "BUY"
           else (entry - pos["min_price"]) / entry)
    mae = ((entry - pos["min_price"]) / entry if pos["action"] == "BUY"
           else (pos["max_price"] - entry) / entry)

    try:
        from src.services.notifier import send_trade_notification as _notify
        _n_args = (sym, pos["action"], move - fee_used, reason)
        def _notify_safe(*a):
            try:
                _notify(*a)
            except Exception as _ne:
                log.warning("[NOTIFY_FAIL] send_trade_notification: %s", _ne)
        threading.Thread(target=_notify_safe, args=_n_args, daemon=True).start()
    except Exception as e:
        log.info("    [Warn: Notifikace error] %s", e)

    # ── V11: Extract learning snapshot and decision context at trade close ──
    learning_snapshot = None
    decision_context = None
    adaptive_zones_snapshot = None
    try:
        from src.services.learning_monitor import get_learning_state
        learning_snapshot = get_learning_state()
    except Exception:
        pass

    try:
        from src.services.realtime_decision_engine import get_last_decision_context
        decision_context = get_last_decision_context(sym)
    except Exception:
        pass

    try:
        from src.optimized.mtf_filter import get_zone_snapshot
        adaptive_zones_snapshot = get_zone_snapshot(sym)
    except Exception:
        pass

    # ── V11: Calculate reward scores ──
    signal_quality_score = (1.0 if mfe / max(mae, 1e-6) >= 1.5 else 0.7 if mfe > 0 else 0.3)
    time_efficiency_score = (1.0 if pos.get("ticks", 60) < 30 else 0.7 if pos.get("ticks", 60) < 60 else 0.4)
    risk_management_score = (1.0 if abs(move) >= 0.01 else 0.7 if abs(move) >= 0.005 else 0.4)
    
    trade = {
        **pos["signal"],
        "profit":        profit,
        "pnl":           profit,  # Alias for metrics compatibility
        "net_pnl":       _pnl_result["net_pnl"],
        "gross_pnl":     _pnl_result["gross_pnl"],
        "fee_pnl":       _pnl_result["fee_pnl"],
        "slippage_pnl":  _pnl_result["slippage_pnl"],
        "result":        result,
        "exit_price":    curr,
        "close_reason":  reason,
        "timestamp":     pos["signal"].get("timestamp", time.time()),  # entry time
        "close_time":    time.time(),                                   # actual close time
        "duration_seconds": int(time.time() - pos["open_ts"]),          # V10.13g: hold duration
        "fill_slippage": pos.get("fill_slippage", 0.0),
        "mae":           mae,
        "mfe":           mfe,
        "mfe_pct":       mfe * 100,
        "mae_pct":       mae * 100,
        "stop_loss":     pos.get("stop_loss",   pos["signal"].get("stop_loss")),
        "take_profit":   pos.get("take_profit", pos["signal"].get("take_profit")),
        
        # V11: Learning context at trade open
        "learning_at_open": learning_snapshot or {},
        
        # V11: Decision engine context
        "decision_engine": decision_context or {},
        
        # V11: Adaptive zones at open
        "adaptive_zones_at_open": adaptive_zones_snapshot or {},
        
        # V11: Smart exit trigger analysis
        "smart_exit_trigger": {
            "exit_reason": reason,
            "tp_hit": "TP_HIT" in reason if reason else False,
            "sl_hit": "SL_HIT" in reason or "STOP_LOSS" in reason if reason else False,
            "breakeven_time": int(time.time() - pos["open_ts"]) if move >= 0 else None,
            "risk_adjusted": pos.get("reduced", False),
            "reason": f"{reason} - MFE/MAE ratio: {mfe/max(mae, 1e-6):.2f}",
        },
        
        # V11: Reward scoring
        "rewards": {
            "signal_quality": signal_quality_score,
            "time_efficiency": time_efficiency_score,
            "risk_management": risk_management_score,
            "total": (signal_quality_score + time_efficiency_score + risk_management_score) / 3,
        },
    }

    try:
        update_metrics(pos["signal"], trade)
    except Exception as e:
        log.error(f"[TRADE_CLOSE_ERROR] update_metrics failed: {e}")

    try:
        update_returns(sym, profit)
    except Exception as e:
        log.error(f"[TRADE_CLOSE_ERROR] update_returns failed: {e}")

    try:
        update_equity(profit)
    except Exception as e:
        log.error(f"[TRADE_CLOSE_ERROR] update_equity failed: {e}")

    # V10.14: Use frozen open_regime instead of current regime for consistency
    # BUG FIX: Define reg_sig before try block to prevent NameError in next try block
    reg_sig = pos.get("open_regime", pos["signal"].get("regime", "RANGING"))
    try:
        bayes_update(sym, reg_sig, profit)
        bandit_update(sym, reg_sig, max(-0.05, min(0.05, profit)))
        record_trade_close(sym, reg_sig, profit)
    except Exception as e:
        log.error(f"[TRADE_CLOSE_ERROR] regime/bayes/bandit updates failed: {e}")

    increment_trades_closed()  # V10.13s Phase 2: Track trade close event
    get_event_bus().emit("LOG_OUTPUT", {"message": f"[TRADE_CLOSE_DEBUG] increment_trades_closed called for {sym} (reason={reason})"}, time.time())

    # BUG FIX: Define all learning vars before try block to prevent NameError if import fails
    bool_f = {}  # default empty if try block fails
    _ap = abs(profit)
    if   _ap < 0.0005: learning_pnl = 0.0
    elif _ap < 0.001:  learning_pnl = 0.0003 if profit > 0 else -0.0003
    else:              learning_pnl = profit
    _fee_cost  = -_pnl_result["fee_pnl"]
    _slip_cost = -_pnl_result["slippage_pnl"]
    _gross_pnl = _pnl_result["gross_pnl"]
    _net_pnl   = _pnl_result["net_pnl"]
    try:
        from src.services.learning_monitor import lm_update, lm_count, lm_health
        raw_f  = pos["signal"].get("features", {})
        bool_f = {k: v for k, v in raw_f.items() if isinstance(v, bool)}
        # Timeout = neutral: no TP/SL reached → no directional signal.
        # Penalty removed — in QUIET market 57% timeout rate drove pair EVs
        # negative rapidly → pair_block deadlock after bootstrap wipe.
        print(f"[V10.13w LM_CLOSE] {sym} {reg_sig} {pos['action']} "
              f"close={reason} gross={_gross_pnl:+.8f} fee={-_fee_cost:.8f} "
              f"slip={-_slip_cost:.8f} net={_net_pnl:+.8f} "
              f"outcome={'WIN' if _net_pnl > 0 else 'LOSS' if _net_pnl < 0 else 'FLAT'} "
              f"lm_pair=yes lm_features={len(bool_f)}")

        increment_lm_update_called()  # V10.13s Phase 2: Track lm_update call
        lm_update(sym, reg_sig, learning_pnl,
                  ws=pos["signal"].get("ws", 0.5),
                  features=bool_f)

        # V10.13w Fix A: Log learning signal reception with correct LM state
        increment_lm_update_success()  # V10.13s Phase 2: Track lm_update success
        _lm_key = (sym, reg_sig)
        _lm_n = lm_count.get(_lm_key, 0)
        _lm_h = lm_health()
        print(f"[V10.13w LM_SUCCESS] {sym}/{reg_sig} pnl={learning_pnl:+.8f} "
              f"n={_lm_n} health={_lm_h:.4f}")
    except Exception as e:
        log.error(f"[LM_ERROR] lm_update() failed for {sym}/{reg_sig}: {type(e).__name__}: {e}", exc_info=True)
        log.error(f"[V10.13w LM_SKIP] {sym} close={reason} reason=lm_update_exception")

    # ── V10.9: Adapt feature weights from closed position ─────────────────────
    # EV contribution per active feature = learning_pnl / n_active.
    # Inactive features are omitted — no penalty for absence, only reward/penalty
    # for features that were present and contributed to this outcome.
    try:
        from src.services.feature_weights import update_feature_weights as _ufw
        _active_fw = [k for k, v in bool_f.items() if v]
        if _active_fw and learning_pnl != 0.0:
            _per_f = learning_pnl / len(_active_fw)
            _fevs  = {k: _per_f for k in _active_fw}
            _lmh_fw, _dd_fw = 0.0, 0.0
            try:
                from src.services.learning_monitor import lm_health as _lmhfn
                _lmh_fw = float(_lmhfn() or 0.0)
            except Exception:
                pass
            try:
                from src.services.diagnostics import max_drawdown as _ddfn
                _dd_fw = float(_ddfn() or 0.0)
            except Exception:
                pass
            _new_w = _ufw(sym, reg_sig, _fevs, _lmh_fw, _dd_fw)
            log.info(f"    fw[v10.9]: {sym} {reg_sig}  "
                  f"score_pnl={learning_pnl:+.5f}  "
                  f"w={{{', '.join(f'{k}:{v:.2f}' for k, v in _new_w.items() if k in _active_fw)}}}")
    except Exception:
        pass

    try:
        from src.services.realtime_decision_engine import update_calibrator, update_edge_stats
        outcome  = 1 if result == "WIN" else 0
        p        = float(pos["signal"].get("confidence", 0.5))
        features = pos["signal"].get("features", {})
        regime   = pos["signal"].get("regime", "RANGING")
        update_calibrator(p, outcome)
        update_edge_stats(features, outcome, regime)
    except Exception:
        pass

    from src.services.firebase_client import save_last_trade
    save_last_trade(trade)

    # V10.13u+11 (Fix 7): Exit outcome attribution with audit counter guard
    # Build and record exit context for exit type analysis
    # Only update audit counters on successful lock acquisition, not on duplicates
    try:
        if close_lock_status == "acquired":
            exit_ctx = build_exit_ctx(
                sym=sym,
                regime=regime,
                side=pos["action"],
                entry_price=entry,
                exit_price=curr,
                size=pos["size"],
                hold_seconds=int(time.time() - pos["open_ts"]),
                gross_pnl=_pnl_result["gross_pnl"],
                fee_cost=_fee_cost,
                slippage_cost=_slip_cost,
                net_pnl=_pnl_result["net_pnl"],
                mfe=mfe,
                mae=mae,
                final_exit_type=reason,
                exit_reason_text=reason,
                was_winner=(profit > 0),
                was_forced=False,
            )
            update_exit_attribution(exit_ctx)
        else:
            log.debug(f"[V10.13u11] Skip exit audit for {sym} reason={reason} status={close_lock_status}")
    except Exception as e:
        log.debug(f"[V10.13v] Exit attribution error: {e}")

    BATCH.append(trade)
    log.info(f"[TRADE_BATCH] {sym} profit={profit:+.8f} result={result} batch_size={len(BATCH)}")
    if len(BATCH) >= 5:   # lowered 20→5: flush sooner to minimise data loss on restart
        _flush()

    # V10.13: update dynamic correlation memory before removing the position.
    # Pairs the closing trade's realized move with each peer's current live_pnl
    # so the realized correlation can be learned for future variance estimates.
    try:
        from src.services.risk_engine import update_correlation_memory as _ucm
        _ucm(sym, move, _positions)
    except Exception:
        pass

    # V10.13u+14: Try/finally for guaranteed lock release
    try:
        _close_stage(sym, close_key, "position_remove_start")
        get_event_bus().emit("LOG_OUTPUT", {"message": f"[CLOSE_LOGIC_END] {sym} about to delete position"}, time.time())
        with _positions_lock:
            _positions.pop(sym, None)
            _sync_regime_exposure()   # Fix 5: recount eliminates decrement drift
        get_event_bus().emit("LOG_OUTPUT", {"message": f"[CLOSE_LOGIC_DELETED] {sym} position deleted"}, time.time())
        _close_stage(sym, close_key, "position_remove_done")
    except Exception as e:
        log.exception(f"[CLOSE_POSITION_REMOVE_FAIL] {sym} {e}")
        _close_stage(sym, close_key, "exception", reason=str(type(e).__name__))
    finally:
        # V10.13u+14: Guaranteed lock release even if exception occurs
        _close_stage(sym, close_key, "lock_release_start")
        _mark_recently_closed(close_key)
        _CLOSING_POSITIONS.pop(close_key, None)
        log.warning(f"[CLOSE_LOCK_RELEASED] {sym} reason={reason} key={close_key} status=closed")
        _close_stage(sym, close_key, "lock_release_done")
        _log_close_lock_health()

    if _pending_open:
        pending = _pending_open.pop(0)
        # V10.10: pass closed position's move so handle_signal can apply
        # the capital recycling bonus (×1.1) when the exited trade was profitable.
        pending["_recycling_pnl"] = move
        handle_signal(pending)

    # V11.0: End of decision chain — check Latency SLA (50ms)
    _t_end = time.perf_counter()
    _lat_ms = (_t_end - _t_start) * 1000
    guard.report_latency(_lat_ms)
    if _lat_ms > 50:
        log.warning(f"    [LATENCY_WARN] on_price processing time: {_lat_ms:.2f}ms (SLA: 50ms)")


subscribe_once("signal_created", handle_signal)
subscribe_once("price_tick",     on_price)
