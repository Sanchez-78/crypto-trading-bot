"""Pure stop rule for evidence collection, never an execution permission.

Trades are not independent: these normal-approximation bounds are descriptive
budget limits, not confidence in a proven economic edge.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
import statistics
from typing import Sequence


@dataclass(frozen=True)
class EvidenceBudgetDecision:
    allowed: bool
    code: str
    n: int
    mean_net_bps: float | None
    upper_bound_bps: float | None
    lower_bound_bps: float | None


def decide_evidence_budget(
    net_pnl_bps: Sequence[float], *, min_n: int = 40, max_n: int = 150,
    z: float = 1.645,
) -> EvidenceBudgetDecision:
    """Apply the ordered stop rules to finite post-cost bps, without I/O.

    Sample SD uses n-1; a singleton has no estimated bounds. Correlated trades
    make the bounds indicative only. Invalid history or policy fails closed.
    """
    n = len(net_pnl_bps)
    invalid = EvidenceBudgetDecision(False, "INVALID_HISTORY", n, None, None, None)
    if (type(min_n) is not int or type(max_n) is not int
            or not 2 <= min_n <= max_n or isinstance(z, bool)
            or not isinstance(z, Real)):
        return invalid
    try:
        z = float(z)
    except (ValueError, OverflowError, TypeError):
        return invalid
    if not math.isfinite(z) or z <= 0:
        return invalid
    values = []
    for value in net_pnl_bps:
        if isinstance(value, bool) or not isinstance(value, Real):
            return invalid
        try:
            value = float(value)
        except (ValueError, OverflowError, TypeError):
            return invalid
        if not math.isfinite(value):
            return invalid
        values.append(value)
    mean = upper = lower = None
    try:
        if n:
            mean = statistics.mean(values)
        if n >= 2:
            margin = float(z) * (statistics.stdev(values) / math.sqrt(n))
            upper, lower = mean + margin, mean - margin
        if any(value is not None and not math.isfinite(value) for value in (mean, upper, lower)):
            return invalid
    except (OverflowError, ValueError):
        return invalid
    if n < min_n:
        code = "CONTINUE"
    elif upper < 0:
        code = "STOP_NO_EDGE"
    elif n >= max_n and lower <= 0:
        code = "STOP_BUDGET_EXHAUSTED"
    else:
        code = "CONTINUE"
    return EvidenceBudgetDecision(code == "CONTINUE", code, n, mean, upper, lower)
