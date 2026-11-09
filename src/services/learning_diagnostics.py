"""Pure diagnostics answering why PAPER learning does or does not improve.

Learning can only help if (1) entries carry pre-cost information, (2) learner
contexts differ by more than noise, (3) those differences persist, (4) the
learner's own estimate ranks future outcomes, and (5) selection beats CONTROL
over time. Each check is descriptive; trades are not independent. No I/O.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import statistics
from typing import Sequence

MIN_CONTEXT_N = 20


@dataclass(frozen=True)
class Observation:
    context: str           # learner context key at decision time
    action: str            # ADAPTIVE / CONTROL / PROBE / WARMUP
    estimate_bps: float    # learner's shrunk mean net estimate at decision time
    probability: float     # learner admission probability
    net_bps: float
    gross_bps: float | None
    entry_ts: float


def _mean_ci(values: Sequence[float]) -> dict:
    n = len(values)
    if n < 2:
        return {"n": n, "mean_bps": statistics.mean(values) if n else None, "half_width_bps": None}
    mean = statistics.mean(values)
    return {"n": n, "mean_bps": mean, "half_width_bps": 1.96 * statistics.stdev(values) / math.sqrt(n)}


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3:
        return None
    mx, my = statistics.mean(x), statistics.mean(y)
    sx = math.fsum((a - mx) ** 2 for a in x)
    sy = math.fsum((b - my) ** 2 for b in y)
    if sx == 0 or sy == 0:
        return None
    return math.fsum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sx * sy)


def _spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    return _pearson(_ranks(x), _ranks(y)) if len(x) >= 3 else None


def _chi2_sf(x: float, dof: int) -> float:
    """Upper-tail chi-square probability via the Wilson-Hilferty normal approximation."""
    z = ((x / dof) ** (1 / 3) - (1 - 2 / (9 * dof))) / math.sqrt(2 / (9 * dof))
    return 0.5 * math.erfc(z / math.sqrt(2))


def _critical_rho(n: int) -> float:
    """One-sided 5 % critical rank correlation, normal approximation."""
    return 1.645 / math.sqrt(n - 1)


def diagnose(observations: Sequence[Observation], *, min_context_n: int = MIN_CONTEXT_N) -> dict:
    obs = sorted(observations, key=lambda o: o.entry_ts)
    for o in obs:
        if not all(math.isfinite(v) for v in (o.estimate_bps, o.probability, o.net_bps, o.entry_ts)):
            raise ValueError("invalid_learning_observation")

    gross = [o.gross_bps for o in obs if o.gross_bps is not None and math.isfinite(o.gross_bps)]
    signal = _mean_ci(gross)

    by_context: dict[str, list[float]] = defaultdict(list)
    for o in obs:
        by_context[o.context].append(o.net_bps)
    big = {k: v for k, v in by_context.items() if len(v) >= min_context_n}

    # Between-context spread of means vs. what pure noise would give
    # (chi-square homogeneity of means, Wilson-Hilferty p-value).
    dispersion = None
    if len(big) >= 3:
        means = {k: statistics.mean(v) for k, v in big.items()}
        errors = {k: statistics.variance(v) / len(v) for k, v in big.items()}
        if all(e > 0 for e in errors.values()):
            weights = {k: 1 / e for k, e in errors.items()}
            pooled = math.fsum(weights[k] * means[k] for k in big) / math.fsum(weights.values())
            chi2 = math.fsum((means[k] - pooled) ** 2 / errors[k] for k in big)
            dof = len(big) - 1
            noise = math.sqrt(statistics.mean(errors.values()))
            observed = statistics.stdev(means.values())
            dispersion = {"contexts": len(big), "observed_sd_of_means_bps": observed, "noise_sd_bps": noise,
                          "ratio": observed / noise, "chi2": chi2, "dof": dof, "p_value": _chi2_sf(chi2, dof)}

    # Do early context means predict later ones? (chronological halves)
    persistence = None
    if len(big) >= 4:
        first = [statistics.mean(v[:len(v) // 2]) for v in big.values()]
        second = [statistics.mean(v[len(v) // 2:]) for v in big.values()]
        persistence = {"contexts": len(big), "pearson": _pearson(first, second),
                       "spearman": _spearman(first, second)}

    # Does the learner's estimate at decision time rank the realized result?
    scored = [o for o in obs if o.action in {"ADAPTIVE", "CONTROL", "PROBE"}]
    estimate = {"n": len(scored),
                "spearman": _spearman([o.estimate_bps for o in scored], [o.net_bps for o in scored]),
                "pearson": _pearson([o.estimate_bps for o in scored], [o.net_bps for o in scored])}

    adaptive_p = [o.probability for o in obs if o.action == "ADAPTIVE"]
    probability = ({"n": len(adaptive_p), "min": min(adaptive_p), "mean": statistics.mean(adaptive_p),
                    "max": max(adaptive_p), "sd": statistics.pstdev(adaptive_p)} if adaptive_p else None)

    # Learning curve: ADAPTIVE − CONTROL per chronological quarter of the experiment.
    arms = [o for o in obs if o.action in {"ADAPTIVE", "CONTROL"}]
    curve = []
    if len(arms) >= 8:
        size = math.ceil(len(arms) / 4)
        for index in range(0, len(arms), size):
            chunk = arms[index:index + size]
            a = [o.net_bps for o in chunk if o.action == "ADAPTIVE"]
            c = [o.net_bps for o in chunk if o.action == "CONTROL"]
            curve.append({"from_ts": chunk[0].entry_ts, "to_ts": chunk[-1].entry_ts,
                          "adaptive_n": len(a), "control_n": len(c),
                          "diff_bps": statistics.mean(a) - statistics.mean(c) if a and c else None})

    return {"signal_gross": signal, "context_dispersion": dispersion, "context_persistence": persistence,
            "estimate_vs_outcome": estimate, "adaptive_probability": probability,
            "learning_curve": curve, "reasons": reasons(signal, dispersion, persistence, estimate, curve)}


def reasons(signal: dict, dispersion: dict | None, persistence: dict | None,
            estimate: dict, curve: list) -> list[str]:
    """Plain codes naming which precondition for learning holds or fails."""
    out = []
    if signal["half_width_bps"] is None:
        out.append("SIGNAL_INSUFFICIENT_DATA")
    elif signal["mean_bps"] - signal["half_width_bps"] > 0:
        out.append("SIGNAL_HAS_GROSS_EDGE")
    elif signal["mean_bps"] + signal["half_width_bps"] < 0:
        out.append("SIGNAL_NEGATIVE_GROSS")
    else:
        out.append("SIGNAL_NO_GROSS_EDGE")
    if dispersion is None:
        out.append("CONTEXTS_INSUFFICIENT_DATA")
    else:
        out.append("CONTEXTS_DIFFER" if dispersion["p_value"] < 0.05 else "CONTEXTS_NOISE_ONLY")
    if persistence is None or persistence["spearman"] is None:
        out.append("PERSISTENCE_INSUFFICIENT_DATA")
    else:
        persists = persistence["spearman"] > _critical_rho(persistence["contexts"])
        out.append("CONTEXTS_PERSIST" if persists else "CONTEXTS_DO_NOT_PERSIST")
    if estimate["spearman"] is None or estimate["n"] < 100:
        out.append("ESTIMATE_INSUFFICIENT_DATA")
    else:
        ranks = estimate["spearman"] > _critical_rho(estimate["n"])
        out.append("ESTIMATE_RANKS_OUTCOMES" if ranks else "ESTIMATE_UNINFORMATIVE")
    diffs = [q["diff_bps"] for q in curve if q["diff_bps"] is not None]
    if len(diffs) >= 3:
        out.append("CURVE_IMPROVING" if diffs[-1] > diffs[0] and diffs[-1] > 0 else "CURVE_FLAT_OR_WORSE")
    else:
        out.append("CURVE_INSUFFICIENT_DATA")
    return out
