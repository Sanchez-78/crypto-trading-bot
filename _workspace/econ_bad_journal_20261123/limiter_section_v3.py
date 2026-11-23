# ── 2026-11-23: rate-limit the per-reject DETAIL output of REJECT_ECON_BAD_ENTRY (observability only)
# The reject branch printed a line and a [ECON_BAD_ENTRY_RETURN_TRACE] warning for every rejected
# signal (~48k journal lines / ~16 min reported), leaving ~15 min of journal history. This only
# decides whether one reject's detail lines are written; decisions, track_blocked(), near-miss,
# diagnostics and the [ECON_BAD_READY_BUT_REJECTED] invariant are untouched. Off by default: unless
# RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED is true/1/yes/on, every detail is written exactly as before.
# When on, per window: the first reject of each category is written in full, the rest are counted,
# and the first reject after the window writes one summary line. Categories are the leading [a-z_]
# token of the reason, capped at 16 (overflow -> "other"). Kept in this module so a deploy stays
# one file.
#
# Loss contract (review 2026-11-23 R1/R2): a write cannot be confirmed from Python (StreamHandler
# swallows stream errors; journald may rate-limit), so nothing waits for an acknowledgement. Each
# summary carries a sequence number and CUMULATIVE totals since process start next to the window
# counts. A lost summary line is visible as a gap in seq, and its counts are contained in the
# totals of the next line that arrives. A process restart starts again at seq=1.
import os as _ecl_os
import re as _ecl_re
import threading as _ecl_threading

ECON_BAD_REJECT_LOG_LIMIT_FLAG = "RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED"
_ECL_CATEGORY_RE = _ecl_re.compile(r"[a-z_]{1,40}")


def _econ_bad_reject_log_limit_enabled(env=None) -> bool:
    raw = (_ecl_os.environ if env is None else env).get(ECON_BAD_REJECT_LOG_LIMIT_FLAG, "")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _econ_bad_reject_category(reason) -> str:
    match = _ECL_CATEGORY_RE.match(str(reason or "").strip().lower())
    return match.group(0) if match else "unknown"


def _ecl_add(target: dict, cat: str, rejects: int, suppressed: int, cap: int) -> None:
    if cat not in target and len(target) >= cap:
        cat = "other"
    entry = target.setdefault(cat, [0, 0])
    entry[0] += rejects
    entry[1] += suppressed


class EconBadRejectLogLimiter:
    def __init__(self, window_s: float = 60.0, max_categories: int = 16, clock=_time.monotonic):
        self._window_s = float(window_s)
        self._max = int(max_categories)
        self._clock = clock
        self._lock = _ecl_threading.Lock()
        self._started = None
        self._window_start = None
        self._counts = {}  # current window: category -> [rejects, suppressed]
        self._totals = {}  # since process start, same category cap
        self._seq = 0

    def observe(self, reason):
        """Record one reject; returns (emit_detail, summary_line_or_None)."""
        cat = _econ_bad_reject_category(reason)
        with self._lock:
            now = self._clock()
            summary = None
            if self._window_start is None:
                self._started = self._window_start = now
            elif now - self._window_start >= self._window_s:
                for k, (r, s) in self._counts.items():
                    _ecl_add(self._totals, k, r, s, self._max)
                self._seq += 1
                w_rej = sum(v[0] for v in self._counts.values())
                w_sup = sum(v[1] for v in self._counts.values())
                t_rej = sum(v[0] for v in self._totals.values())
                t_sup = sum(v[1] for v in self._totals.values())
                by_cat = ",".join(f"{k}={v[0]}/{v[1]}" for k, v in sorted(self._totals.items()))
                summary = (f"[ECON_BAD_REJECT_LOG_SUMMARY] seq={self._seq} "
                           f"window_s={now - self._window_start:.0f} window_rejects={w_rej} "
                           f"window_suppressed={w_sup} total_rejects={t_rej} total_suppressed={t_sup} "
                           f"since_s={now - self._started:.0f} "
                           f"by_category_total(rejects/suppressed)={by_cat}")
                self._counts = {}
                self._window_start = now
            if cat not in self._counts and len(self._counts) >= self._max:
                cat = "other"
            entry = self._counts.setdefault(cat, [0, 0])
            entry[0] += 1
            emit = entry[0] == 1
            if not emit:
                entry[1] += 1
            return emit, summary

    def snapshot(self) -> dict:
        with self._lock:
            return {k: tuple(v) for k, v in self._counts.items()}

    def totals_snapshot(self) -> dict:
        with self._lock:
            return {k: tuple(v) for k, v in self._totals.items()}


_ECON_BAD_REJECT_LOG_LIMITER = EconBadRejectLogLimiter()


def _econ_bad_should_emit_reject_detail(reason, env=None, limiter=None) -> bool:
    """True = write this reject's detail lines. Never raises; on an internal error it returns True
    (old behaviour: more output rather than lost diagnostics). A failed summary write loses no
    counts: the next summary's cumulative totals contain them (see the loss contract above)."""
    try:
        if not _econ_bad_reject_log_limit_enabled(env):
            return True
        emit, summary = (limiter or _ECON_BAD_REJECT_LOG_LIMITER).observe(reason)
        if summary:
            try:
                log.warning(summary)
            except Exception:
                pass
        return emit
    except Exception:
        return True


