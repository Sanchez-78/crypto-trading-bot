"""
Real-time learning quality, convergence, and model health monitor.

Tracks per (sym, reg) pair:
  EV trend       — risk_ev sampled on every trade close
  WR trend       — rolling empirical win rate
  PnL history    — raw closed-trade pnl
  Bandit score   — UCB1 focus per pair
  Feature WR     — per-feature win rate (requires ≥10 samples)

Convergence:
  lm_convergence = 1 - (std of last 10 EVs) / (std of all EVs)
  → 1.0 = fully stable, 0.0 = still noisy

Health score:
  mean over all pairs with ≥20 trades of:
    convergence × (0.5 + 0.5 × max(EV, -1.0))
  Range: 0.0 (no data) … ~0.5 (fully converged positive edge)
  Losing systems (EV<0) now score >0 so BAD/WEAK alerts fire correctly.

Alerts:
  health < 0.10 → BAD   (no learning detected)
  health < 0.30 → WEAK  (edge is thin)
  else          → GOOD
"""

import logging
import numpy as np
import time

from src.services.execution import bandit_score

log = logging.getLogger(__name__)

# ── V10.13u+6: Economic log throttling ──────────────────────────────────────────
_last_econ_log_ts = 0.0          # Timestamp of last econ log
_last_econ_log_signature = None  # Signature of last logged values (for change detection)
_last_econ_safety_log_ts = 0.0   # Timestamp of last econ safety warning

ECON_LOG_THROTTLE_SECONDS = 60   # Emit econ log once per 60 seconds


def _compute_econ_signature(pf: float, status: str, source: str, closed_trades: int, wins: int, losses: int) -> str:
    """Compute a signature of economic health key values for change detection."""
    return f"{pf:.3f}|{status}|{source}|{closed_trades}|{wins}|{losses}"


# ── Per-(sym, reg) state ───────────────────────────────────────────────────────

lm_ev_hist:      dict = {}   # (sym, reg) → [ev_t, ...]       (last 200)
lm_wr_hist:      dict = {}   # (sym, reg) → [rolling_wr, ...] (last 200)
lm_pnl_hist:     dict = {}   # (sym, reg) → [pnl, ...]        (last 200)
lm_count:        dict = {}   # (sym, reg) → int
lm_bandit_hist:  dict = {}   # (sym, reg) → [ucb_score, ...]  (last 200)
lm_feature_stats: dict = {}  # feature_name → [wins, total]
sym_recent_pnl:  dict = {}   # sym → [last 8 pnl across all regimes] (loss_cluster guard)


# ── Redis hydration on boot (zero-loss cold start) ────────────────────────────

def _hydrate_from_redis() -> None:
    try:
        from src.services.state_manager import hydrate_lm
        data = hydrate_lm()
        if not data:
            return
        lm_pnl_hist.update(data.get("lm_pnl_hist", {}))
        lm_wr_hist.update(data.get("lm_wr_hist", {}))
        lm_ev_hist.update(data.get("lm_ev_hist", {}))
        lm_bandit_hist.update(data.get("lm_bandit_hist", {}))
        lm_count.update(data.get("lm_count", {}))
        sym_recent_pnl.update(data.get("sym_recent_pnl", {}))
        lm_feature_stats.update(data.get("lm_feature_stats", {}))
        n_pairs = len(lm_count)
        n_features = len(lm_feature_stats)
        if n_pairs:
            print(f"[LM_HYDRATE] loaded pairs={n_pairs} features={n_features} "
                  f"trades={sum(lm_count.values())} source=redis")
        else:
            print(f"[LM_HYDRATE] WARNING: no pairs loaded from Redis (empty state)")
    except Exception as exc:
        print(f"⚠️  LM Redis hydration skipped: {exc}")


# V10.13b: Defer hydration until explicit call from bootstrap sequence
# _hydrate_from_redis()  # REMOVED — now called explicitly from bot2/main.py

async def explicit_hydrate_from_redis(redis_client=None):
    """
    V10.13b: Explicit hydration point called from bootstrap sequence, not at module import.
    This ensures we load Redis state AFTER Firebase is ready and BEFORE replaying trades.

    Returns: dict with hydration source and count of pairs loaded
    """
    global _hydration_source

    if redis_client is None:
        try:
            from src.services.state_manager import get_redis_client
            redis_client = await get_redis_client()
        except Exception:
            redis_client = None

    if redis_client is None:
        _hydration_source = "empty"
        return {"source": "empty", "pairs": 0}

    try:
        data = _hydrate_from_redis_impl(redis_client)
        if data and any(data.values()):
            n_pairs = len(lm_count)
            _hydration_source = "redis"
            return {"source": "redis", "pairs": n_pairs}
        else:
            _hydration_source = "empty"
            return {"source": "empty", "pairs": 0}
    except Exception as exc:
        import logging
        logging.error(f"[LM] Explicit hydration failed: {exc}")
        _hydration_source = "error"
        return {"source": "error", "pairs": 0}


def _hydrate_from_redis_impl(redis_client_unused=None):
    """Internal: do the actual hydration (sync version)."""
    try:
        from src.services.state_manager import hydrate_lm
        data = hydrate_lm()
        if not data:
            return {}
        lm_pnl_hist.update(data.get("lm_pnl_hist", {}))
        lm_wr_hist.update(data.get("lm_wr_hist", {}))
        lm_ev_hist.update(data.get("lm_ev_hist", {}))
        lm_bandit_hist.update(data.get("lm_bandit_hist", {}))
        lm_count.update(data.get("lm_count", {}))
        sym_recent_pnl.update(data.get("sym_recent_pnl", {}))
        lm_feature_stats.update(data.get("lm_feature_stats", {}))
        n_pairs = len(lm_count)
        if n_pairs:
            import logging
            logging.info(f"[LM] Hydrated {n_pairs} pairs from Redis, "
                        f"{sum(lm_count.values())} total trades")
        return data
    except Exception as exc:
        import logging
        logging.error(f"[LM] Hydration impl failed: {exc}")
        return {}


_HIST_CAP = 200
_hydration_source = "pending"  # Track source for diagnostics


# HOTFIX (2026-04-26): Hydrate LearningMonitor from canonical closed trade history
def hydrate_from_canonical_trades(closed_trades: list) -> dict:
    """
    PATCH 3: Ingest canonical closed trade history into LearningMonitor with real WR/EV.

    Called at startup to sync LM with dashboard's closed trade source.
    Normalizes field names, counts wins/losses/flats, computes decisive WR and EV.
    Prevents state mismatch where dashboard shows 500 trades but LM shows 6.

    Args:
        closed_trades: List of closed trade dicts from Firebase history

    Returns:
        dict with hydration stats: {loaded_trades, hydrated_pairs, decisive, flats, ...}
    """
    global lm_count, lm_pnl_hist, lm_ev_hist, lm_wr_hist, lm_feature_stats, _hydration_source

    if not closed_trades:
        return {"loaded_trades": 0, "hydrated_pairs": 0, "source": "empty"}

    try:
        import logging
        _log = logging.getLogger(__name__)

        # Per-pair accumulators
        pair_stats = {}  # (sym, reg) → {n_total, wins, losses, flats, pnl_sum, ev_sum}
        EPS = 1e-12
        trades_loaded = 0
        decisive_count = 0
        flat_count = 0

        # Ingest each closed trade into per-(sym, reg) history
        for trade in closed_trades:
            # Normalize field names
            sym = trade.get("symbol") or trade.get("sym") or ""
            reg = trade.get("regime") or trade.get("reg") or "UNKNOWN"
            pnl = trade.get("net_pnl") or trade.get("pnl") or trade.get("pnl_pct") or 0.0
            ev = trade.get("realized_ev") or trade.get("ev") or 0.0

            if not sym:
                continue

            key = (sym, reg)

            # Initialize pair stats if needed
            if key not in pair_stats:
                pair_stats[key] = {
                    "n_total": 0, "wins": 0, "losses": 0, "flats": 0,
                    "pnl_sum": 0.0, "ev_sum": 0.0
                }

            # Initialize lm state if needed
            if key not in lm_count:
                lm_count[key] = 0
                lm_pnl_hist[key] = []
                lm_ev_hist[key] = []
                lm_wr_hist[key] = []

            # Classify trade as win/loss/flat
            pnl_f = float(pnl)
            if pnl_f > EPS:
                pair_stats[key]["wins"] += 1
                decisive_count += 1
                win = 1.0
            elif pnl_f < -EPS:
                pair_stats[key]["losses"] += 1
                decisive_count += 1
                win = 0.0
            else:
                pair_stats[key]["flats"] += 1
                flat_count += 1
                win = 0.5

            # Append to LM histor ies
            lm_pnl_hist[key].append(pnl_f)
            lm_ev_hist[key].append(float(ev))
            lm_wr_hist[key].append(win)

            # Cap histories at 200
            _cap(lm_pnl_hist[key])
            _cap(lm_ev_hist[key])
            _cap(lm_wr_hist[key])

            # Accumulate stats
            pair_stats[key]["n_total"] += 1
            pair_stats[key]["pnl_sum"] += pnl_f
            pair_stats[key]["ev_sum"] += float(ev)
            lm_count[key] += 1
            trades_loaded += 1

        # Log pair-level stats for top 5 pairs
        hydrated_pairs = len(lm_count)
        top_pairs = sorted(pair_stats.items(), key=lambda x: x[1]["n_total"], reverse=True)[:5]

        pair_log_lines = []
        for (sym, reg), stats in top_pairs:
            n = stats["n_total"]
            decisive = stats["wins"] + stats["losses"]
            wr_decisive = stats["wins"] / decisive if decisive > 0 else 0.0
            avg_pnl = stats["pnl_sum"] / n if n > 0 else 0.0
            avg_ev = stats["ev_sum"] / n if n > 0 else 0.0
            pair_log_lines.append(
                f"  {sym} {reg} n={n} decisive={decisive} wr={wr_decisive*100:.0f}% "
                f"avg_pnl={avg_pnl:+.6f} ev={avg_ev:+.6f}"
            )

        _hydration_source = "firebase_canonical"

        _log.info(
            f"[LM_HYDRATE_CANONICAL] loaded_closed_trades={trades_loaded} "
            f"hydrated_pairs={hydrated_pairs} decisive={decisive_count} flats={flat_count}"
        )
        for line in pair_log_lines:
            _log.info(f"[LM_HYDRATE_PAIR]{line}")

        return {
            "loaded_trades": trades_loaded,
            "hydrated_pairs": hydrated_pairs,
            "source": "firebase_canonical",
            "decisive": decisive_count,
            "flats": flat_count,
        }

    except Exception as exc:
        import logging
        logging.error(f"[LM_HYDRATE] Failed: {exc}")
        return {"loaded_trades": 0, "hydrated_pairs": 0, "source": "error"}


def check_state_mismatch(canonical_closed_trades: int) -> None:
    """
    Check for state mismatch between canonical metrics and LearningMonitor.

    Logs warning if dashboard shows significant trade history but LM is empty.
    Triggers after hydration to verify consistency.

    Args:
        canonical_closed_trades: Number of closed trades in dashboard/canonical source
    """
    if canonical_closed_trades < 100:
        return  # Not enough trades to warrant concern

    lm_total_trades = sum(lm_count.values())
    if lm_total_trades < 20 and canonical_closed_trades >= 100:
        import logging
        logging.warning(
            f"[STATE_MISMATCH] canonical_trades={canonical_closed_trades} "
            f"but LM_trades={lm_total_trades}; hydration may be incomplete"
        )


def _cap(lst):
    if len(lst) > _HIST_CAP:
        del lst[:-_HIST_CAP]


def true_ev(sym, reg):
    """Bounded Sharpe-EV via tanh: tanh(mean / max(std, 0.002)).
    Output is always in (-1, +1) — eliminates spikes from near-zero std.
    std floor 0.002 prevents division explosion on perfectly consistent
    streaks (e.g. 5 identical small wins → std≈0 → raw ratio → ±∞).
    Returns 0.0 until at least 10 samples are available.
    """
    pnl = list(lm_pnl_hist.get((sym, reg), []))   # snapshot; list is safe against concurrent append
    if len(pnl) < 10:
        return 0.0
    arr  = pnl[-20:]
    std  = max(float(np.std(arr)), 0.002)
    return float(np.tanh(float(np.mean(arr)) / std))


# Bayesian shrinkage prior strength — equivalent to 15 "neutral" trades.
# New pairs borrow the global mean EV rather than returning 0.
# At n=15:  50% local / 50% global.
# At n=50:  77% local / 23% global.
# At n=200: 93% local /  7% global  (→ converges to true_ev).
_SHRINKAGE_K = 15


def _global_ev() -> float:
    """Mean true_ev across all pairs with ≥10 samples; 0.0 if none exist."""
    evs = [true_ev(s, r) for (s, r), n in lm_count.items() if n >= 10]
    return float(np.mean(evs)) if evs else 0.0


def conf_ev(sym, reg):
    """Bayesian shrinkage EV: blends local edge with global prior.

    Replaces the old `true_ev × min(n/50, 1)` linear suppression that forced
    new pairs to report EV=0 for their first 10 trades — triggering spurious
    "NO LEARNING SIGNAL" alerts and blocking the meta-controller from routing
    capital to genuinely promising new pairs.

    Formula:
        ev_shrunk = (n × local_ev + K × global_ev) / (n + K)

    where K = _SHRINKAGE_K (15).  At n=0 the pair inherits the system-wide
    mean; as data accumulates it converges toward its own true_ev.
    """
    n       = lm_count.get((sym, reg), 0)
    local   = true_ev(sym, reg)    # 0.0 for n < 10 (its own bootstrap guard)
    global_ = _global_ev()
    return (n * local + _SHRINKAGE_K * global_) / (n + _SHRINKAGE_K)


def ev_decay(sym, reg):
    """V10.1: Detect edge degradation or improvement vs recent history.

    Compares mean PnL of last 5 non-zero trades (recent) against the 15
    non-zero trades before that (older). Returns a multiplier in [0.5, 1.2]
    applied to risk_ev — propagates automatically to TP/SL, hold, RR, and
    early_exit decisions without touching those callers.

    Sign-aware ratio handles all four quadrants correctly:
      both positive  → r / o           (improving>1, weakening<1)
      both negative  → |o| / |r|       (smaller recent loss = improvement)
      neg → pos      → 1.2             (was losing, now winning: full boost)
      pos → neg      → 0.5             (was winning, now losing: full penalty)

    Original spec bug: simple r/o returns 0.5 for neg→pos (incorrectly
    penalises a pair that improved). Fixed here with explicit sign checks.

    Bootstrap-safe: returns 1.0 when < 20 samples, all-zero periods (micro-PnL
    map zeroes noise trades), or insufficient non-zero data. No premature
    penalty during early data collection.
    """
    pnl = list(lm_pnl_hist.get((sym, reg), []))   # snapshot
    if len(pnl) < 20:
        return 1.0
    recent = [p for p in pnl[-5:]    if p != 0.0]
    older  = [p for p in pnl[-20:-5] if p != 0.0]
    if len(recent) < 2 or len(older) < 3:
        return 1.0          # insufficient non-zero trades — stay neutral
    r = sum(recent) / len(recent)
    o = sum(older)  / len(older)
    if abs(o) < 1e-6:
        return 1.0
    if r >= 0 and o > 0:
        ratio = r / o                           # both profitable: simple ratio
    elif r < 0 and o < 0:
        ratio = abs(o) / max(abs(r), 1e-8)     # both losing: smaller loss = good
    elif r > 0 and o < 0:
        return 1.2                              # was losing, now winning: boost
    else:
        return 0.5                              # was winning, now losing: penalise
    return max(0.5, min(1.2, ratio))


def ev_stability(sym, reg):
    """V10.1c: Edge consistency multiplier — rewards low-variance edges.

    Computes |mean| / (std + ε) over the last 15 PnL samples — a signal-to-
    noise ratio. High mean relative to std → stable edge → boost allocation.
    High std relative to mean → noisy edge → reduce allocation.

    V10.1c micro-edge filter:
      Threshold 0.0005 matches the micro-PnL mapping boundary exactly
      (trade_executor: pnl < 0.0005 → learning_pnl = 0.0). Any mean below
      this is composed of zeroed noise trades mixed with tiny mapped values
      (±0.0003) — not a real edge. Without the filter, mean=0.0001 with
      std=0.00001 → stability=10 → clamped to 1.2 (false boost). With it,
      the pair returns 1.0 (neutral) until real edge accumulates.

    Works correctly for negative EV:
      stable loser  (mean=-0.001, std=0.0002) → stability=4.99 → 1.2×
        risk_ev more negative → tighter TP, shorter hold, stricter RR ✓
      noisy loser   (mean=-0.001, std=0.005)  → stability=0.20 → 0.6×
        risk_ev dampened toward 0 → treated as exploratory ✓
      micro loser   (mean=-0.0002, std=anything) → 1.0 (neutral — too small) ✓

    Bootstrap-safe:
      returns 1.0 for < 15 samples.
      returns 1.0 when |mean| < 0.0005 (micro-noise threshold).

    Manual variance — no numpy call needed for 15-element window.
    Range: [0.6, 1.2].
    """
    pnl = list(lm_pnl_hist.get((sym, reg), []))   # snapshot
    if len(pnl) < 15:
        return 1.0
    recent = pnl[-15:]
    mean   = sum(recent) / len(recent)
    if abs(mean) < 0.0005:          # V10.1c: micro-edge filter
        return 1.0
    var       = sum((x - mean) ** 2 for x in recent) / len(recent)
    std       = var ** 0.5
    stability = abs(mean) / (std + 1e-6)
    return max(0.6, min(1.2, stability))


def record_features(features, pnl):
    """Fractional feature attribution: each active feature receives 1/N credit
    instead of a full binary win. With N features per signal, each gets equal
    share — prevents high-frequency features from dominating WR stats simply
    because they co-occur with many others.
    win/t remains in [0, 1] so lm_feature_quality() percentages are unchanged.
    """
    if not features:
        return
    credit = 1.0 / len(features)
    win = 1 if pnl > 0 else 0
    for f in features:
        w, t = lm_feature_stats.get(f, (0.0, 0.0))
        lm_feature_stats[f] = (w + win * credit, t + credit)


# ── Update hook — call on every trade close ────────────────────────────────────

def _pnl_weighted_label(pnl: float) -> float:
    """
    Phase 4 Task 2: PnL-weighted LSTM training label.

    Converts a raw PnL float into a weighted label for online LSTM fine-tuning.
    Formula: sign(pnl) × clamp(|pnl| × 100, 0.5, 5.0)

    Examples:
      pnl = +0.02  →  +2.0   (solid 2% win — strong positive gradient)
      pnl = +0.001 →  +0.5   (floor: tiny win still gets minimum signal)
      pnl = +0.10  →  +5.0   (fat winner — maximum gradient, 5× noisy edge)
      pnl = -0.015 →  -1.5   (1.5% loss — proportional negative signal)
      pnl = 0.0    →   0.0   (neutral timeout — no gradient update)

    The floor of 0.5 prevents tiny wins/losses from being silenced entirely.
    The cap of 5.0 prevents a single outlier from dominating the weights.
    """
    if pnl == 0.0:
        return 0.0
    sign      = 1.0 if pnl > 0 else -1.0
    magnitude = min(max(abs(pnl) * 100.0, 0.5), 5.0)
    return sign * magnitude


def lm_update(sym, reg, pnl, ws, features, window=None):
    """
    PATCH 3.5: Record one closed trade with incremental averaging.

    sym:      symbol string ("BTCUSDT")
    reg:      regime string ("RANGING")
    pnl:      realised profit/loss (float)
    ws:       win-score at entry (float)
    features: dict of signal features (may be empty)
    window:   np.ndarray shape (SEQ_LEN, INPUT_SIZE) — LSTM training window
              Optional; if provided, triggers a PnL-weighted online update.

    Key change: Use incremental averaging instead of list append for EV/PnL
    to prevent stale data from dominating convergence metrics.
    """
    key = (sym, reg)
    # V10.13s Phase 3B: Log lm_update invocation for diagnostics
    log.debug(f"[LM_UPDATE_CALLED] {sym}/{reg} pnl={pnl:.6f} ws={ws:.4f} features={len(features)}")
    log.debug(f"[LM_STATE_BEFORE] key={key} count_keys={list(lm_count.keys())}")

    # Trade count
    lm_count[key] = lm_count.get(key, 0) + 1
    n = lm_count[key]

    # PnL history
    pnl_lst = lm_pnl_hist.setdefault(key, [])
    pnl_lst.append(float(pnl))
    _cap(pnl_lst)

    # ────────────────────────────────────────────────────────────────────────
    # PATCH 3.5: Incremental EV averaging — convergence acceleration
    # ────────────────────────────────────────────────────────────────────────
    # Instead of storing all EV values and recomputing stats, use 
    # incremental mean: ev_n = ev_{n-1} + (new_ev - ev_{n-1}) / n
    ev_current = true_ev(sym, reg)
    ev_mean = lm_ev_hist.get(key, [0.0])[-1] if lm_ev_hist.get(key) else 0.0
    
    # Incremental update: new_ev = old_ev + (current_ev - old_ev) / count
    ev_new = ev_mean + (ev_current - ev_mean) / max(n, 1)
    ev_lst = lm_ev_hist.setdefault(key, [])
    ev_lst.append(ev_new)
    _cap(ev_lst)

    # Per-symbol recent PnL (across all regimes) — used by loss_cluster guard
    s_lst = sym_recent_pnl.setdefault(sym, [])
    s_lst.append(float(pnl))
    if len(s_lst) > 8:
        del s_lst[:-8]

    # Rolling win rate — snapshot before iteration; trade-close thread may append concurrently
    pnl_snap = list(pnl_lst)
    wins  = sum(1 for x in pnl_snap if x > 0)
    total = len(pnl_snap)
    wr    = wins / total
    wr_lst = lm_wr_hist.setdefault(key, [])
    wr_lst.append(wr)
    _cap(wr_lst)

    # Bandit UCB snapshot
    b = bandit_score(sym, reg)
    b_lst = lm_bandit_hist.setdefault(key, [])
    b_lst.append(b)
    _cap(b_lst)

    # Feature win rates — direct update, no soft sampling
    record_features(features, pnl)

    # ── Phase 4 Task 2: PnL-weighted LSTM online fine-tuning ─────────────────
    # Only update when a feature window is provided (caller must build it).
    # Neutral timeouts (pnl ≈ 0) produce label 0.0 → no gradient update.
    if window is not None:
        try:
            from src.services.lstm_model import model as _lstm
            _label = _pnl_weighted_label(pnl)
            if _label != 0.0:            # skip neutral timeouts
                _lstm.update(window, _label)
                log.debug(
                    "LSTM update %s/%s pnl=%.4f → label=%.2f updates=%d",
                    sym, reg, pnl, _label, _lstm._updates,
                )
        except Exception as _exc:
            log.debug("LSTM update skipped: %s", _exc)

    # Persist to Redis (zero-loss cold start)
    try:
        from src.services.state_manager import flush_lm_update_async
        log.debug(f"[LM_PRE_PERSIST] {sym}/{reg} count={lm_count.get(key, 0)} "
                  f"pnl_len={len(lm_pnl_hist.get(key, []))} "
                  f"ev_len={len(lm_ev_hist.get(key, []))} "
                  f"wr_len={len(lm_wr_hist.get(key, []))}")
        flush_lm_update_async(
            sym, reg,
            pnl_lst,
            lm_wr_hist[key],
            lm_ev_hist[key],
            lm_bandit_hist.get(key, []),
            lm_count[key],
            sym_recent_pnl.get(sym, []),
            lm_feature_stats,
        )
        # V10.13s Phase 3B: Log successful persistence
        _n = lm_count.get(key, 0)
        _ev = lm_ev_hist.get(key, [None])[-1] if lm_ev_hist.get(key) else None
        log.debug(f"[LM_PERSIST_OK] {sym}/{reg} n={_n} ev={_ev:.6f}" if _ev else f"[LM_PERSIST_OK] {sym}/{reg} n={_n}")
    except Exception as _persist_err:
        log.debug(f"[LM_PERSIST_ERROR] {sym}/{reg}: {_persist_err}")


def update_from_paper_trade(trade: dict) -> bool:
    """
    P1.1R: Safe canonical paper-training learning update with explicit type handling.
    Never raises. Safely processes closed paper trades with guaranteed type safety.

    Args:
        trade: Closed paper trade dict with symbol, regime, pnl_decimal, ws, features

    Returns:
        True on success, False on validation failure or internal error
    """
    try:
        # Explicit field extraction and type-safe conversion
        symbol = str(trade.get("symbol") or "UNKNOWN")
        regime = str(trade.get("regime") or "UNKNOWN")
        pnl = float(trade.get("pnl_decimal") or trade.get("net_pnl_pct", 0.0) / 100.0)
        ws = float(trade.get("ws") or trade.get("score_at_entry") or 0.0)

        # Most critical: ensure features is always a dict, never a scalar
        features_raw = trade.get("features")
        if isinstance(features_raw, dict):
            features = features_raw
        elif features_raw is None:
            features = {}
        else:
            # Scalar or unexpected type: safety default to empty dict
            features = {}
            log.debug(f"[UPDATE_FROM_PAPER_TRADE] features type mismatch: {type(features_raw).__name__}, defaulting to empty dict")

        # Validation: skip if missing core fields
        if symbol == "UNKNOWN" or regime == "UNKNOWN":
            log.debug(f"[UPDATE_FROM_PAPER_TRADE] skip: symbol={symbol} regime={regime}")
            return False

        # Call lm_update with guaranteed types
        lm_update(sym=symbol, reg=regime, pnl=pnl, ws=ws, features=features)
        return True

    except Exception as exc:
        log.exception(f"[UPDATE_FROM_PAPER_TRADE_ERROR] unexpected error: {exc}")
        return False


# ── Convergence & edge metrics ─────────────────────────────────────────────────

def lm_convergence(sym, reg):
    """
    Variance-collapse convergence score ∈ [0, 1].
    Compares std of last 10 EV samples vs std of all samples.
    Returns 0 when fewer than 20 samples available.
    """
    evs = lm_ev_hist.get((sym, reg), [])
    if len(evs) < 10:
        return 0.0
    recent = float(np.std(evs[-10:]))
    long   = float(np.std(evs))
    return max(0.0, 1.0 - recent / (long + 1e-6))


def lm_edge_strength(sym, reg):
    """Current PnL-based EV for this (sym, reg) pair."""
    return true_ev(sym, reg)


def lm_bandit_focus(sym, reg):
    """Mean UCB score over last 10 bandit observations. 0 if insufficient data."""
    b = lm_bandit_hist.get((sym, reg), [])
    if len(b) < 10:
        return 0.0
    return float(np.mean(b[-10:]))


def lm_feature_quality():
    """
    Per-feature empirical win rate.
    Only returns features with ≥10 trades.
    Returns dict: {feature_name: win_rate}.
    """
    out = {}
    for fname, (w, t) in lm_feature_stats.items():
        if t < 10:
            continue
        out[fname] = w / t
    return out


# ── Force-mode and toxic-reset ────────────────────────────────────────────────


def reset_if_toxic():
    """Disabled — reset loop was blocking data flow. No-op."""
    return


# ── Global health score ────────────────────────────────────────────────────────

def lm_health_components():
    """
    V10.13x.2: Return health with granular component breakdown.
    Uses new health_decomposition_v2 from scratch_forensics module.

    Returns dict with 8 components + final score + warnings.
    """
    try:
        from src.services.scratch_forensics import health_decomposition_v2
        return health_decomposition_v2()
    except Exception as e:
        log.warning(f"[LM_HEALTH] Could not use health_v2: {e}, falling back to legacy")
        # Fallback to legacy if import fails
        return _lm_health_components_legacy()


def _lm_health_components_legacy():
    """Legacy health calculation for fallback."""
    scores = []
    evs = []
    convs = []

    for (sym, reg), n in lm_count.items():
        if n < 5:
            continue
        conv = lm_convergence(sym, reg)
        ev   = lm_edge_strength(sym, reg)
        convs.append(conv)
        evs.append(ev)
        scores.append(conv * (0.5 + 0.5 * max(ev, -1.0)))

    if not scores:
        return {
            'final': 0.0,
            'status': 'NO_DATA',
            'components': {
                'edge': 0.0,
                'convergence': 0.0,
                'calibration': 0.0,
                'stability': 0.0,
                'penalty': 0.0,
            }
        }

    positive_evs = [e for e in evs if e > 0]
    edge_component = float(np.mean(positive_evs)) if positive_evs else 0.0
    converged = sum(1 for c in convs if c > 0.5)
    convergence_component = converged / len(convs) if convs else 0.0
    total_trades = sum(lm_count.values())
    bootstrap_penalty = 0.0 if total_trades >= 50 else -0.3
    final_health = float(np.mean(scores))

    return {
        'final': final_health,
        'status': 'GOOD' if final_health >= 0.3 else ('WEAK' if final_health >= 0.1 else 'BAD'),
        'components': {
            'edge': edge_component,
            'convergence': convergence_component,
            'calibration': 0.0,
            'stability': 0.0,
            'penalty': bootstrap_penalty,
        }
    }


def lm_health():
    """
    Backward-compatible scalar health score.
    For component breakdown, use lm_health_components().
    """
    h_dict = lm_health_components()
    return h_dict.get('overall', h_dict.get('final', 0.0))


def lm_economic_health() -> dict:
    """
    V10.13u+4: Calculate economic health using dashboard's canonical trades.

    Uses the exact same 500-trade snapshot as the dashboard to ensure PF consistency.
    Never falls back to stale METRICS or model-state sources.

    Returns dict with:
      - profit_factor: gross_wins / gross_losses ratio (from canonical source)
      - scratch_rate: fraction of exits via SCRATCH_EXIT
      - recent_trend: "IMPROVING" | "DECLINING" | "NEUTRAL"
      - overall_score: 0.0-1.0 based on these components
      - status: "GOOD" | "CAUTION" | "FRAGILE" | "DEGRADED" | "BAD"
    """
    try:
        from src.services.learning_event import METRICS, _close_reasons, _recent_results
        from src.services.firebase_client import load_history
        from src.services.canonical_metrics import canonical_profit_factor_with_meta

        # V10.13u+4: Load same 500-trade snapshot as dashboard (authoritative source)
        canonical_closed_trades = load_history(limit=500)
        if not canonical_closed_trades or len(canonical_closed_trades) < 5:
            return {
                "profit_factor": 0.0,
                "scratch_rate": 0.0,
                "recent_trend": "INSUFFICIENT_DATA",
                "overall_score": 0.0,
                "status": "INSUFFICIENT_DATA",
                "warnings": ["Need at least 5 canonical closed trades"]
            }

        # V10.13u+4: Get PF with metadata from dashboard's exact source
        pf_meta = canonical_profit_factor_with_meta(canonical_closed_trades)
        profit_factor = pf_meta["pf"]
        net_pnl = pf_meta["net_pnl"]

        # Normalize inf to 99.0 for display
        if profit_factor == float("inf"):
            profit_factor = 99.0

        trades = len(canonical_closed_trades)
        wins = pf_meta["wins"]
        losses = pf_meta["losses"]

        # Scratch rate: SCRATCH_EXIT / total trades
        scratch_exits = _close_reasons.get("SCRATCH_EXIT", 0)
        scratch_rate = scratch_exits / trades if trades > 0 else 0.0

        # Recent trend (PATCH 2: Only compute if sufficient sample size)
        wins = METRICS.get("wins", 0)
        losses = METRICS.get("losses", 0)
        decisive = wins + losses
        overall_wr = wins / decisive if decisive > 0 else 0.0

        rr = list(_recent_results)
        recent_wins = sum(1 for r in rr if r == "WIN")
        recent_sample_size = len(rr)

        # PATCH 2: Don't treat empty/small sample as degradation
        if recent_sample_size < 8:
            # Insufficient recent data: don't judge trend yet
            recent_trend = "INSUFFICIENT_RECENT_DATA"
            trend_score = 0.5  # Neutral, not degraded
        else:
            recent_wr = recent_wins / recent_sample_size
            trend_delta = recent_wr - overall_wr
            if trend_delta > 0.05:
                recent_trend = "IMPROVING"
                trend_score = 0.8
            elif trend_delta < -0.05:
                recent_trend = "DECLINING"
                trend_score = 0.2
            else:
                recent_trend = "NEUTRAL"
                trend_score = 0.5

        # Overall score components (each 0.0-1.0)
        # V10.13u+3: PF score corrected for unprofitable systems
        net_pnl = METRICS.get("net_pnl_total", 0.0)

        if profit_factor < 1.0:
            pf_score = max(0.0, min(0.35, profit_factor / 3.0))
        elif profit_factor < 1.5:
            pf_score = 0.35 + (profit_factor - 1.0) * 0.5
        else:
            pf_score = min(1.0, 0.60 + min(profit_factor, 3.0) / 7.5)

        scratch_score = max(0.0, 1.0 - (scratch_rate / 0.80))
        overall_score = pf_score * 0.4 + scratch_score * 0.35 + trend_score * 0.25

        # Status label
        warnings = []
        if profit_factor < 1.0:
            warnings.append(f"Negative or break-even PF: {profit_factor:.2f}")
        if scratch_rate > 0.70:
            warnings.append(f"High scratch rate: {scratch_rate*100:.1f}%")
        if recent_trend == "DECLINING" and recent_sample_size >= 8:
            recent_wr_pct = recent_wins / recent_sample_size
            warnings.append(f"Recent performance degrading ({recent_wr_pct*100:.1f}% vs {overall_wr*100:.1f}%)")

        # V10.13u+5: Parser failure clamp — 100+ trades with zero wins/losses is fatal
        if trades >= 100 and pf_meta["wins"] == 0 and pf_meta["losses"] == 0:
            overall_score = 0.0
            status = "BAD"
        # V10.13u+4: Hard safety clamp — PF < 1.0 = never GOOD
        elif profit_factor < 1.0 and net_pnl <= 0:
            overall_score = min(overall_score, 0.34)
            status = "BAD"
        elif profit_factor < 1.0:
            overall_score = min(overall_score, 0.49)
            status = "CAUTION"
        elif overall_score >= 0.7:
            status = "GOOD"
        elif overall_score >= 0.5:
            status = "CAUTION"
        elif overall_score >= 0.3:
            status = "FRAGILE"
        else:
            status = "DEGRADED"

        # V10.13u+6: Throttled diagnostic log with change detection
        global _last_econ_log_ts, _last_econ_log_signature, _last_econ_safety_log_ts

        current_sig = _compute_econ_signature(
            profit_factor, status, pf_meta['source'],
            pf_meta['closed_trades'], pf_meta['wins'], pf_meta['losses']
        )
        current_time = time.time()
        should_emit = (
            (current_time - _last_econ_log_ts >= ECON_LOG_THROTTLE_SECONDS) or
            (current_sig != _last_econ_log_signature)
        )

        if should_emit:
            log.info(
                f"[ECON_CANONICAL_ACTIVE] pf={profit_factor:.2f} source={pf_meta['source']} "
                f"closed_trades={pf_meta['closed_trades']} wins={pf_meta['wins']} losses={pf_meta['losses']} "
                f"gross_win={pf_meta['gross_win']:.8f} gross_loss={pf_meta['gross_loss']:.8f} "
                f"net_pnl={pf_meta['net_pnl']:.8f} economic_score={overall_score:.3f} status={status}"
            )
            _last_econ_log_ts = current_time
            _last_econ_log_signature = current_sig

        # V10.13u+6: Safety warning for BAD status (also throttled)
        if status == "BAD":
            should_emit_safety = (current_time - _last_econ_safety_log_ts >= ECON_LOG_THROTTLE_SECONDS)
            if should_emit_safety:
                log.warning(
                    f"[ECON_SAFETY_BAD] pf={profit_factor:.2f} net_pnl={pf_meta['net_pnl']:.8f} "
                    f"score={overall_score:.3f} action=conservative_mode"
                )
                _last_econ_safety_log_ts = current_time

        return {
            "profit_factor": round(profit_factor, 3),
            "scratch_rate": round(scratch_rate, 3),
            "recent_trend": recent_trend,
            "overall_score": round(overall_score, 3),
            "status": status,
            "warnings": warnings,
            "components": {
                "pf_score": round(pf_score, 3),
                "scratch_score": round(scratch_score, 3),
                "trend_score": round(trend_score, 3),
            }
        }
    except Exception as e:
        log.warning(f"[ECONOMIC_HEALTH] Calculation failed: {e}")
        return {
            "profit_factor": 0.0,
            "scratch_rate": 0.0,
            "recent_trend": "ERROR",
            "overall_score": 0.0,
            "status": "ERROR",
            "warnings": [str(e)]
        }


# ── Meta state + adaptive control ────────────────────────────────────────────

meta: dict = {
    "ws_mult":    1.0,   # WS threshold multiplier  (< 1 loosens, > 1 tightens)
    "risk_mult":  1.0,   # position size risk scaler
    "alloc_mult": 1.0,   # allocation scaler
}


def meta_update():
    """
    Adjust meta multipliers from live system signals. Call every loop tick.

    Frozen at 1.0 during bootstrap (<100 trades) to prevent meta from
    suppressing early learning before sufficient data exists.

    V10.13w: Also frozen when learning integrity mismatch detected — prevents
    adaptive component from tuning on false state.

    learning quality (lm_health):
      < 0.20 → loosen threshold + shrink allocation (system still learning)
      > 0.40 → tighten threshold + expand allocation (edge confirmed)
      else   → reset to neutral 1.0

    performance (Sharpe from equity curve):
      > 1.5  → raise risk_mult (strong positive drift)
      < 0.5  → lower risk_mult (weak / negative drift)
      else   → reset to 1.0

    drawdown (peak DD from equity curve):
      > 0.10 → risk_mult 0.6 override (takes precedence over Sharpe boost)
    """
    # V10.13w: Freeze adaptive updates if learning integrity compromised
    if is_learning_frozen():
        log.warning("[V10.13w SAFE_MODE] Learning integrity mismatch detected → freezing adaptive updates")
        meta["ws_mult"]    = 1.0    # neutral
        meta["risk_mult"]  = 0.85   # slight de-risk
        meta["alloc_mult"] = 0.90
        return

    try:
        from src.services.execution import is_bootstrap
        if is_bootstrap():
            meta["ws_mult"]    = 1.0
            meta["risk_mult"]  = 1.0
            meta["alloc_mult"] = 1.0
            return
    except Exception:
        pass

    h  = lm_health()
    try:
        from src.services.diagnostics import sharpe as _sharpe, max_drawdown as _dd
        sr = _sharpe()
        dd = _dd()
    except Exception:
        sr = 0.0
        dd = 0.0

    # Learning quality gate
    # ws_mult > 1 → TIGHTEN threshold (fewer signals); < 1 → LOOSEN (more signals)
    # Crisis (h < 0.10): TIGHTEN — system is provably losing; reduce signal flow.
    #   Previous code set ws_mult=0.95 (LOOSEN) for all h<0.20, meaning a bad
    #   system got MORE signals → more losses → deeper crisis. Inverted logic.
    # Learning (0.10 ≤ h < 0.20): neutral — system is still gathering data.
    # Edge confirmed (h > 0.40): slight TIGHTEN — demand only top-quality signals.
    if h < 0.10:
        meta["ws_mult"]    = 1.20   # TIGHTEN — crisis mode
        meta["alloc_mult"] = 0.70
    elif h < 0.20:
        meta["ws_mult"]    = 1.0    # neutral — still learning
        meta["alloc_mult"] = 0.90
    elif h > 0.40:
        meta["ws_mult"]    = 1.05
        meta["alloc_mult"] = 1.05
    else:
        meta["ws_mult"]    = 1.0
        meta["alloc_mult"] = 1.0

    # Performance gate (softened)
    if sr > 1.5:
        meta["risk_mult"] = 1.05
    elif sr < 0.5:
        meta["risk_mult"] = 0.90
    else:
        meta["risk_mult"] = 1.0

    # Drawdown override — takes precedence over Sharpe boost
    if dd > 0.10:
        meta["risk_mult"] = 0.60


# ── Phase 4 Task 3: Defense efficiency ────────────────────────────────────────

def defense_efficiency() -> dict:
    """
    Compute defense metrics from close_reasons + L2 rejection counter.

    Definitions:
      wall_exits   — positions closed early via L2 wall_exit (execution_engine)
      timeouts     — positions that expired without hitting TP/SL
      l2_rejected  — entry signals blocked before a position was even opened
      defended     — wall_exits + l2_rejected  (situations where L2 data helped)
      efficiency   — defended / (defended + timeouts)
                     → 1.0 = every timeout was either avoided or caught early
                     → 0.0 = L2 intelligence contributed nothing

    Returns a dict ready to embed in lm_snapshot() and Firestore metrics.
    """
    try:
        from src.services.learning_event import CLOSE_REASONS  # type: ignore
        wall_exits  = CLOSE_REASONS.get("wall_exit", 0)
        timeouts    = CLOSE_REASONS.get("timeout",   0)
    except Exception:
        wall_exits  = 0
        timeouts    = 0

    try:
        from src.services.state_manager import get_l2_rejected, get_corr_rejected
        l2_rejected   = get_l2_rejected()
        corr_rejected = get_corr_rejected()
    except Exception:
        l2_rejected   = 0
        corr_rejected = 0

    defended   = wall_exits + l2_rejected + corr_rejected
    total      = defended + timeouts
    efficiency = round(defended / total, 4) if total > 0 else 0.0

    return {
        "wall_exits":    wall_exits,
        "timeouts":      timeouts,
        "l2_rejected":   l2_rejected,
        "corr_rejected": corr_rejected,
        "defended":      defended,
        "efficiency":    efficiency,
    }


# ── V10.13w: Reconciliation & Integrity Check ────────────────────────────────

_integrity_frozen = False  # Safe-mode flag: True when mismatch detected

def check_learning_integrity(summary_metrics=None):
    """
    V10.13w: Reconcile Learning Monitor state against summary metrics.

    Returns: (is_mismatch: bool, mismatch_report: dict)

    Checks if:
      - trade counts match
      - winrate within tolerance
      - PnL reasonably consistent

    If mismatch detected, logs WARNING and sets _integrity_frozen flag.
    """
    global _integrity_frozen

    if summary_metrics is None:
        try:
            from src.services.learning_event import get_metrics
            summary_metrics = get_metrics()
        except Exception:
            return False, {"error": "could_not_load_summary"}

    # Extract summary stats
    summary_trades = summary_metrics.get("trades", 0)
    summary_wr = summary_metrics.get("winrate", 0.0)
    summary_pnl = summary_metrics.get("profit", 0.0)
    summary_pf = summary_metrics.get("profit_factor", 1.0)

    # Extract LM stats
    lm_total_trades = sum(lm_count.values())
    lm_wins = 0
    lm_total = 0
    lm_total_pnl = 0.0

    for (sym, reg), n in lm_count.items():
        pnl_list = list(lm_pnl_hist.get((sym, reg), []))   # snapshot
        wr_list = lm_wr_hist.get((sym, reg), [])

        if pnl_list:
            lm_total_pnl += sum(pnl_list)
        if wr_list and wr_list[-1] > 0:
            lm_wins += int(n * wr_list[-1])
        lm_total += n

    lm_wr = (lm_wins / lm_total) if lm_total > 0 else 0.0

    # Tolerance: small differences OK (±5 trades, ±0.05 WR, ±0.0001 PnL)
    _TRADE_TOL = 5
    _WR_TOL = 0.05
    _PNL_TOL = 0.0001

    mismatch = {
        "summary_trades": summary_trades,
        "lm_trades": lm_total_trades,
        "summary_wr": round(summary_wr, 4),
        "lm_wr": round(lm_wr, 4),
        "summary_pnl": round(summary_pnl, 8),
        "lm_pnl": round(lm_total_pnl, 8),
        "summary_pf": round(summary_pf, 2),
        "status": "OK",
    }

    is_mismatch = False

    if abs(summary_trades - lm_total_trades) > _TRADE_TOL:
        mismatch["status"] = "MISMATCH"
        mismatch["trade_delta"] = summary_trades - lm_total_trades
        is_mismatch = True

    if abs(summary_wr - lm_wr) > _WR_TOL and lm_total >= 10:
        mismatch["status"] = "MISMATCH"
        mismatch["wr_delta"] = round(summary_wr - lm_wr, 4)
        is_mismatch = True

    if is_mismatch:
        _integrity_frozen = True
        log.warning(f"[V10.13w RECON] MISMATCH DETECTED: {mismatch}")
    else:
        log.info(f"[V10.13w RECON] {mismatch}")
        _integrity_frozen = False

    return is_mismatch, mismatch


def is_learning_frozen():
    """V10.13w: True if integrity freeze is active (adaptive updates disabled)."""
    return _integrity_frozen


# ── Alerts ────────────────────────────────────────────────────────────────────

def lm_alerts():
    """
    Returns "BAD" / "WEAK" / "GOOD" and prints detailed learning state when degraded.
    BAD:  health < 0.10 — poor convergence or edge strength
    WEAK: health < 0.30 — edge is thin, needs more data
    GOOD: system is converging with positive edge

    V10.13u Fix 4: Replace vague "NO LEARNING SIGNAL" with grounded state showing
    actual learned data, not just health metric.
    """
    h = lm_health()

    # V10.13u: Compute detailed learning state (Fix 4)
    pairs_with_n5 = sum(1 for n in lm_count.values() if n >= 5)
    pairs_with_n10 = sum(1 for n in lm_count.values() if n >= 10)
    pairs_with_positive_conv = sum(1 for (sym, reg) in lm_count.keys()
                                    if lm_convergence(sym, reg) > 0)
    total_trades_in_lm = sum(lm_count.values())

    if h < 0.10:
        # V10.13u: Show grounded learning state instead of vague "NO SIGNAL"
        print(f"  [!] LEARNING: health={h:.4f} [BAD]")
        print(f"       Hydrated pairs: {pairs_with_n5} with n≥5, {pairs_with_n10} with n≥10, "
              f"{pairs_with_positive_conv} with conv>0")
        print(f"       Total trades in LM: {total_trades_in_lm}")
        print(f"       → Edge too weak or low convergence — needs more data or better feature selection")
        return "BAD"
    if h < 0.30:
        print(f"  [!] LEARNING: WEAK EDGE health={h:.4f}")
        print(f"       Pairs: {pairs_with_n10} with n≥10, {pairs_with_positive_conv} conv>0, {total_trades_in_lm} total trades")
        return "WEAK"
    return "GOOD"


# ── Firestore-serialisable snapshot ──────────────────────────────────────────

def lm_snapshot():
    """
    Return a JSON-serialisable dict suitable for embedding in metrics/latest.
    Called from bot2/main.py alongside execution_data, no extra Firestore writes.
    Shape:
      {
        health:   float,
        alert:    "GOOD"|"WEAK"|"BAD",
        mode:     "COLD"|"WARM"|"LIVE",
        pairs: {
          "BTCUSDT_BULL": {sym, reg, n, ev, wr, conv, bandit}
          ...
        },
        features: {feature_name: win_rate, ...}   (>=10 trades, top 10 by WR)
      }
    """
    try:
        from src.services.execution import bootstrap_mode
        from src.services.learning_event import METRICS
        mode = bootstrap_mode()
        metrics_copy = dict(METRICS)
    except Exception:
        mode = "UNKNOWN"
        metrics_copy = {}

    pairs = {}
    for (sym, reg), n in lm_count.items():
        wr_lst  = lm_wr_hist.get((sym, reg), [])
        ev_lst  = lm_ev_hist.get((sym, reg), [])
        b_lst   = lm_bandit_hist.get((sym, reg), [])
        wr   = round(float(wr_lst[-1]), 4) if wr_lst else 0.0
        ev   = round(float(ev_lst[-1]), 4) if ev_lst else 0.0
        conv = round(lm_convergence(sym, reg), 3)
        band = round(lm_bandit_focus(sym, reg), 3)
        key  = f"{sym}_{reg}"
        pairs[key] = {
            "sym":    sym,
            "reg":    reg,
            "n":      n,
            "ev":     ev,
            "wr":     wr,
            "conv":   conv,
            "bandit": band,
        }

    fq = lm_feature_quality()
    top_features = {
        k: round(v, 4)
        for k, v in sorted(fq.items(), key=lambda x: -x[1])[:10]
    }

    h = lm_health()
    a = lm_alerts()

    # Find strongest edge (min 3 let's say, or just top n)
    best_edge = None
    if pairs:
        valid_edges = [p for p in pairs.values() if p["n"] > 0]
        if valid_edges:
            best_edge = sorted(valid_edges, key=lambda x: (x["wr"], x["ev"]), reverse=True)[0]
            best_edge = f"{best_edge['sym']} ({best_edge['reg']})"

    # Phase 5: Concept Drift
    drift = False
    try:
        from src.services.signal_engine import concept_drift_active
        drift = concept_drift_active()
    except Exception: pass

    return {
        "health":   round(h, 4),
        "alert":    a,
        "mode":     mode,
        "pairs":    pairs,
        "features": top_features,
        "block_reasons": metrics_copy.get("block_reasons", {}),
        "completed_trades": metrics_copy.get("trades", 0),
        "best_edge": best_edge or "Unknown",
        "defense":  defense_efficiency(),
        "concept_drift": drift,
    }


# ── Text monitor ──────────────────────────────────────────────────────────────

def print_learning_monitor():
    """
    Prints a compact learning monitor to stdout.
    Shown automatically in the bot2 main loop alongside print_status().
    V10.13x.2: Includes health decomposition v2 + scratch alerts.
    """
    print("\n=== LEARNING MONITOR ===")

    any_pair = False
    for (sym, reg), n in sorted(lm_count.items()):
        if n < 3:
            continue
        any_pair = True
        conv = lm_convergence(sym, reg)
        ev   = lm_edge_strength(sym, reg)
        band = lm_bandit_focus(sym, reg)
        wr_lst = lm_wr_hist.get((sym, reg), [])
        wr     = wr_lst[-1] if wr_lst else 0.0
        short  = sym.replace("USDT", "")
        conv_tag = (f"conv:{conv:.2f}" if n >= 20
                    else f"conv:-- ({n}/20)")
        print(f"  {short:<4} {reg:<10}  n:{n:<4}  "
              f"EV:{ev:+.3f}  WR:{wr:.0%}  "
              f"{conv_tag}  bandit:{band:.2f}")

    if not any_pair:
        print("  (waiting for 10 closed trades per pair)")

    fq = lm_feature_quality()
    if fq:
        print("\n  Features (WR per signal key):")
        for fname, wr in sorted(fq.items(), key=lambda x: -x[1])[:10]:
            bar_w = 12
            filled = int(bar_w * wr)
            bar = "#" * filled + "-" * (bar_w - filled)
            tag = "+" if wr >= 0.55 else ("~" if wr >= 0.45 else "-")
            print(f"    {fname:<20}  [{bar}]  {wr:.0%}  {tag}")

    # V10.13x.2: Health decomposition v2 with component breakdown
    h_dict = lm_health_components()
    status = h_dict.get('status', 'UNKNOWN')
    overall = h_dict.get('overall', h_dict.get('final', 0.0))
    components = h_dict.get('components', {})
    warnings = h_dict.get('warnings', [])

    pairs_with_n5 = sum(1 for n in lm_count.values() if n >= 5)
    total_trades = sum(lm_count.values())

    print(f"\n  Health: {overall:.3f}  [{status}]")
    print(f"    Edge: {components.get('edge_strength', 0):.3f}  "
          f"Conv: {components.get('convergence', 0):.3f}  "
          f"Stab: {components.get('stability', 0):.3f}  "
          f"Breadth: {components.get('breadth', 0):.3f}")

    if components.get('scratch_penalty', 0) < 0:
        print(f"    ⚠️  Scratch Penalty: {components.get('scratch_penalty', 0):.3f}")

    if warnings:
        print(f"  Warnings:")
        for w in warnings[:3]:
            print(f"    - {w}")

    # V10.13s.4: Economic health display
    print()
    try:
        eh = lm_economic_health()
        eh_status = eh.get("status", "UNKNOWN")
        eh_score = eh.get("overall_score", 0.0)
        pf = eh.get("profit_factor", 0.0)
        sr = eh.get("scratch_rate", 0.0)
        trend = eh.get("recent_trend", "UNKNOWN")

        print(f"  Economic: {eh_score:.3f}  [{eh_status}]")
        print(f"    PF: {pf:.2f}  Scratch: {sr:.0%}  Trend: {trend}")

        eh_warnings = eh.get("warnings", [])
        if eh_warnings and eh_status != "GOOD":
            for w in eh_warnings[:2]:
                print(f"    ⚠️  {w}")
    except Exception as e:
        pass

    # V10.13s.4: Bootstrap reduced-mode indicator
    try:
        from src.services.execution import is_bootstrap_reduced_mode
        if is_bootstrap_reduced_mode():
            print(f"  ⚡ BOOTSTRAP_REDUCED_MODE active (50% position sizing)")
    except Exception:
        pass

    # V10.13x.2: Scratch pressure alert
    try:
        from src.services.scratch_forensics import scratch_pressure_alert
        alert = scratch_pressure_alert()
        if alert.get('alert_level') in ('WARNING', 'CRITICAL'):
            print(f"  {alert.get('scratch_impact', '')}")
    except Exception:
        pass

    print("=" * 24)
