"""
V10.13s.4: Scratch Exit Forensics — Detailed Tracking and Classification
"""

import logging
import time as _time
from collections import deque
from dataclasses import dataclass

log = logging.getLogger(__name__)

_scratch_events = deque(maxlen=500)

@dataclass
class ScratchEvent:
    symbol: str
    hold_time_s: int
    mfe_pct: float
    exit_pnl_pct: float
    is_near_partial25: bool
    is_near_micro_tp: bool
    classification: str
    timestamp: float


def classify_scratch_exit(mfe_pct: float, exit_pnl_pct: float,
                         is_near_partial: bool, is_near_micro: bool) -> str:
    had_profit = mfe_pct >= 0.005
    lost_at_exit = exit_pnl_pct < -0.0010
    near_threshold = is_near_partial or is_near_micro

    if had_profit and not lost_at_exit:
        return "GOOD_DEFENSIVE"
    elif had_profit and lost_at_exit and near_threshold:
        return "LOSSY_PREMATURE"
    elif had_profit and lost_at_exit:
        return "NEUTRAL"
    else:
        return "NEUTRAL"


def instrument_scratch_exit(
    symbol: str,
    hold_time_s: int,
    max_favorable_pnl_pct: float,
    current_pnl_pct: float,
    is_near_partial25: bool = False,
    is_near_micro_tp: bool = False,
) -> None:
    try:
        classification = classify_scratch_exit(
            max_favorable_pnl_pct,
            current_pnl_pct,
            is_near_partial25,
            is_near_micro_tp
        )

        event = ScratchEvent(
            symbol=symbol,
            hold_time_s=hold_time_s,
            mfe_pct=max_favorable_pnl_pct,
            exit_pnl_pct=current_pnl_pct,
            is_near_partial25=is_near_partial25,
            is_near_micro_tp=is_near_micro_tp,
            classification=classification,
            timestamp=_time.time(),
        )

        _scratch_events.append(event)

        if classification == "LOSSY_PREMATURE":
            log.warning(
                f"[SCRATCH_FORENSICS] LOSSY_PREMATURE: {symbol} "
                f"hold={hold_time_s}s mfe={max_favorable_pnl_pct*100:.2f}% "
                f"exit_pnl={current_pnl_pct*100:.3f}%"
            )
    except Exception as e:
        log.debug(f"[SCRATCH_FORENSICS] Error: {e}")


def get_scratch_diagnostics() -> dict:
    if not _scratch_events:
        return {
            "total": 0, "good_defensive": 0, "neutral": 0, "lossy_premature": 0,
            "avg_mfe": 0.0, "avg_exit_pnl": 0.0, "avg_hold_time": 0, "near_miss_rate": 0.0,
        }

    events = list(_scratch_events)
    total = len(events)
    good = sum(1 for e in events if e.classification == "GOOD_DEFENSIVE")
    neutral = sum(1 for e in events if e.classification == "NEUTRAL")
    lossy = sum(1 for e in events if e.classification == "LOSSY_PREMATURE")
    avg_mfe = sum(e.mfe_pct for e in events) / total if total > 0 else 0.0
    avg_exit_pnl = sum(e.exit_pnl_pct for e in events) / total if total > 0 else 0.0
    avg_hold = sum(e.hold_time_s for e in events) / total if total > 0 else 0
    near_misses = sum(1 for e in events if e.is_near_partial25 or e.is_near_micro_tp)
    near_miss_rate = near_misses / total if total > 0 else 0.0

    return {
        "total": total, "good_defensive": good, "neutral": neutral, "lossy_premature": lossy,
        "avg_mfe": round(avg_mfe, 4), "avg_exit_pnl": round(avg_exit_pnl, 4),
        "avg_hold_time": int(avg_hold), "near_miss_rate": round(near_miss_rate, 2),
    }


def scratch_pressure_alert() -> dict:
    try:
        diag = get_scratch_diagnostics()
        total = diag["total"]
        if total < 10:
            return {"alert_level": "OK", "scratch_impact": "", "lossy_rate": 0.0}
        lossy = diag["lossy_premature"]
        lossy_rate = lossy / total if total > 0 else 0.0
        if lossy_rate >= 0.30:
            alert_level = "CRITICAL"
            impact = f"Scratch exits killing {lossy_rate*100:.0f}% (LOSSY_PREMATURE)"
        elif lossy_rate >= 0.15:
            alert_level = "WARNING"
            impact = f"{lossy_rate*100:.0f}% of scratches premature"
        else:
            alert_level = "OK"
            impact = ""
        return {"alert_level": alert_level, "scratch_impact": impact, "lossy_rate": round(lossy_rate, 3)}
    except Exception as e:
        log.debug(f"[SCRATCH_PRESSURE_ALERT] Error: {e}")
        return {"alert_level": "OK", "scratch_impact": "", "lossy_rate": 0.0}


def health_decomposition_v2() -> dict:
    try:
        from src.services.learning_monitor import _lm_health_components_legacy
        base = _lm_health_components_legacy()
        scratch_alert = scratch_pressure_alert()
        scratch_penalty = -0.15 if scratch_alert["alert_level"] == "CRITICAL" else (-0.08 if scratch_alert["alert_level"] == "WARNING" else 0.0)
        overall = base.get("final", 0.0) + scratch_penalty
        overall = max(0.0, min(1.0, overall))
        status = "BAD" if overall < 0.10 else ("WEAK" if overall < 0.30 else "GOOD")
        components = base.get("components", {})
        components["scratch_penalty"] = scratch_penalty
        return {"final": round(overall, 3), "overall": round(overall, 3), "status": status, "components": components, "warnings": base.get("warnings", []), "scratch_alert": scratch_alert}
    except Exception as e:
        log.debug(f"[HEALTH_V2] Error: {e}")
        return {"final": 0.0, "overall": 0.0, "status": "ERROR", "components": {}, "warnings": [str(e)], "scratch_alert": {"alert_level": "OK", "scratch_impact": ""}}
