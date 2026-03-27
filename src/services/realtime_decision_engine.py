"""
Historical pattern filter.

Compares incoming signal features against last 100 trades
(same symbol, same action direction).
Rejects if weighted winrate of similar past trades < block_thr.
Time-decays older trades (half-life = 1 hour).

Modes:
  normal:      block_thr = 0.45
  poor symbol: block_thr = 0.55  (sym WR < 40% over ≥ 10 trades)
  exploration: block_thr = 0.35  (no trades in last 15 min)
  fallback:    block_thr = 0.30  (filter_pass_rate < 1%)
"""

from src.services.firebase_client  import load_history
from src.services.learning_event   import track_blocked, track_regime
import math, time


def _auditor():
    from bot2.auditor import get_min_confidence, is_in_cooldown
    return get_min_confidence, is_in_cooldown


def _decay(ts):
    return math.exp(-(time.time() - ts) / 3600)


def _sim(f1, f2):
    keys = ["ema_diff", "rsi", "volatility", "macd"]
    sc, n = 0, 0
    for k in keys:
        if k in f1 and k in f2:
            diff = abs(f1[k] - f2[k])
            norm = abs(f2[k]) or 1
            sc += max(0, 1 - diff / norm)
            n  += 1
    return sc / n if n else 0


def evaluate_signal(signal):
    # ── Drawdown halt ─────────────────────────────────────────────────────────
    try:
        from bot2.auditor import is_halted
        if is_halted():
            track_blocked()
            return None
    except Exception:
        pass

    # ── Auditor: confidence gate only (no hard cooldown block) ───────────────
    try:
        get_min_conf, _ = _auditor()
        min_conf = get_min_conf()
    except Exception:
        min_conf = 0.55

    # Per-signal: if filter collapsed (<5% pass rate), lower effective threshold
    from src.services.learning_event import get_metrics as _gm2
    _m0 = _gm2()
    _gen0 = _m0.get("signals_generated", 0)
    dyn_conf = min_conf
    if _gen0 > 50:
        _passed0 = max(0, _gen0 - _m0.get("signals_filtered", 0) - _m0.get("blocked", 0))
        if _passed0 / _gen0 < 0.05:
            dyn_conf = max(0.48, min_conf - 0.03)

    if signal.get("confidence", 0) < dyn_conf:
        track_blocked()
        return None

    history = load_history()
    f       = signal["features"]
    reg     = signal.get("regime", "RANGING")

    track_regime(reg)

    if not history:
        return signal

    similar = []
    for t in history:
        if t["symbol"] != signal["symbol"]:
            continue
        if t.get("action") != signal["action"]:
            continue
        sim = _sim(f, t.get("features", {}))
        if sim > 0.6:
            similar.append((t, sim * _decay(t["timestamp"])))

    if len(similar) < 5:
        return signal  # not enough history → pass through

    w    = sum(x[1] for x in similar) or 1e-9
    wins = sum(x[1] for x in similar if x[0]["result"] == "WIN")
    wr   = wins / w

    # ── Adaptive block threshold ──────────────────────────────────────────────
    from src.services.learning_event import get_metrics as _gm
    _m  = _gm()
    _ss = _m.get("sym_stats", {}).get(signal["symbol"], {})

    # Exploration mode: no trades for 15 min → very lenient
    since = _m.get("since_last")
    if since and since > 900:
        block_thr = 0.35

    # Fallback: filter rate near zero → lower threshold
    elif _m.get("signals_generated", 0) > 50:
        gen     = _m["signals_generated"]
        passed  = max(0, gen - _m.get("signals_filtered", 0) - _m.get("blocked", 0))
        pass_rt = passed / gen
        if pass_rt < 0.05:
            block_thr = 0.30
        elif _ss.get("trades", 0) >= 10 and _ss.get("winrate", 0.5) < 0.40:
            block_thr = 0.55
        else:
            block_thr = 0.45
    elif _ss.get("trades", 0) >= 10 and _ss.get("winrate", 0.5) < 0.40:
        block_thr = 0.55
    else:
        block_thr = 0.45

    verdict = "✅" if wr >= block_thr else "🚫"
    print(f"    🧠 {len(similar)} vzorů  WR:{wr:.0%}  {reg}  {verdict}  thr:{block_thr:.0%}")

    if wr < block_thr:
        track_blocked()
        return None

    signal["confidence"] = min(signal["confidence"] * (0.5 + wr), 1.0)

    # ── Confidence calibration: bucket historical WR by confidence ────────────
    # Anti-overfit: only active once ≥ 50 trades
    # Threshold is relative to global WR to avoid deadlock when model is learning
    from src.services.learning_event import get_metrics as _gm5
    _m5 = _gm5()
    if _m5.get("trades", 0) >= 50:
        conf_key   = round(signal["confidence"] * 10) / 10
        global_wr  = _m5.get("winrate", 0.5)
        cal_floor  = max(0.35, global_wr - 0.12)   # 12pp below global WR, min 35%
        bucket     = [t for t in history
                      if abs(t.get("confidence", 0) - conf_key) < 0.06
                      and t.get("result") in ("WIN", "LOSS")]
        if len(bucket) >= 5:
            cal_wr = sum(1 for t in bucket if t["result"] == "WIN") / len(bucket)
            if cal_wr < cal_floor:
                print(f"    📉 CALIB block: bucket={conf_key:.1f}  WR={cal_wr:.0%}<{cal_floor:.0%}  n={len(bucket)}")
                track_blocked()
                return None

    return signal
