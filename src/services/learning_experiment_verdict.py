"""Pure, predeclared descriptive verdicts; never an execution permission."""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
import statistics
from typing import Sequence


@dataclass(frozen=True)
class ArmStats:
    n: int
    mean_bps: float | None
    sd_bps: float | None
    lower_bps: float | None
    upper_bps: float | None


@dataclass(frozen=True)
class ExperimentVerdict:
    codes: tuple[str, ...]
    adaptive: ArmStats
    control: ArmStats
    diff_bps: float | None
    diff_low_bps: float | None
    diff_high_bps: float | None


def _arm(values: Sequence[float]) -> ArmStats:
    n = len(values)
    mean = statistics.mean(values) if n else None
    sd = statistics.stdev(values) if n >= 2 else None
    margin = 1.645 * (sd / math.sqrt(n)) if sd is not None else None
    return ArmStats(n, mean, sd, mean - margin if margin is not None else None,
                    mean + margin if margin is not None else None)


def evaluate_selection_experiment(
    adaptive_bps: Sequence[float], control_bps: Sequence[float], *,
    min_arm_n: int = 30, min_effect_n: int = 100,
) -> ExperimentVerdict:
    """Evaluate ordered rules using sample SD (n-1), without I/O or policy changes.

    Trades are not independent. CONTROL is a random share of candidates, not a
    concurrent portfolio; selection, market timing and costs differ. Bounds are
    indicative, not a causal claim. Arm bounds use z=1.645; the two-sided Welch
    standard-error interval uses the prescribed normal z=1.96, not Student t.
    Empty/singleton arms have no estimated SD or bounds. Invalid observations,
    thresholds (integers >=2 required), or nonfinite calculations fail closed.
    """
    arms = []
    for values in (adaptive_bps, control_bps):
        try:
            arms.append(tuple(values) if not isinstance(values, (str, bytes, dict)) else None)
        except TypeError:
            arms.append(None)
    invalid = ExperimentVerdict(("INVALID_DATA",),
        *(ArmStats(len(v) if v is not None else 0, None, None, None, None) for v in arms),
        None, None, None)
    if (any(v is None for v in arms) or type(min_arm_n) is not int or min_arm_n < 2
            or type(min_effect_n) is not int or min_effect_n < 2):
        return invalid
    try:
        converted = []
        for arm in arms:
            if any(isinstance(v, bool) or not isinstance(v, Real) for v in arm):
                return invalid
            values = tuple(float(v) for v in arm)
            if not all(math.isfinite(v) for v in values):
                return invalid
            converted.append(values)
        adaptive, control = (_arm(v) for v in converted)
        diff = adaptive.mean_bps - control.mean_bps if adaptive.n and control.n else None
        low = high = None
        if adaptive.n >= 2 and control.n >= 2:
            margin = 1.96 * math.hypot(adaptive.sd_bps / math.sqrt(adaptive.n),
                                     control.sd_bps / math.sqrt(control.n))
            low, high = diff - margin, diff + margin
        numbers = [diff, low, high]
        for arm in (adaptive, control):
            numbers.extend((arm.mean_bps, arm.sd_bps, arm.lower_bps, arm.upper_bps))
        if any(v is not None and not math.isfinite(v) for v in numbers):
            return invalid
    except (ValueError, TypeError, OverflowError):
        return invalid
    codes = []
    for name, arm in (("ADAPTIVE", adaptive), ("CONTROL", control)):
        if arm.n >= min_arm_n:
            if arm.upper_bps < 0:
                codes.append(name + "_NO_EDGE")
            elif arm.lower_bps > 0:
                codes.append(name + "_POSITIVE")
    if adaptive.n < min_effect_n or control.n < min_effect_n:
        codes.append("EFFECT_INSUFFICIENT_DATA")
    elif low > 0:
        codes.append("SELECTION_EFFECT_POSITIVE")
    elif high < 0:
        codes.append("SELECTION_EFFECT_NEGATIVE")
    else:
        codes.append("SELECTION_EFFECT_NOT_SHOWN")
    return ExperimentVerdict(tuple(codes), adaptive, control, diff, low, high)
