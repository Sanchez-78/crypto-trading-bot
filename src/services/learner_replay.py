"""Chronological replay of PAPER learner variants on closed trades (pure, no I/O).

Each trade gets the estimate a variant would have produced at its entry time,
using only trades already closed by then. Variants are fixed in VARIANTS before
evaluation. Selection protocol: choose by lift on the development part only,
then test that single variant once on the later holdout part.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
import statistics
from typing import Mapping, Sequence

DEV_FRACTION = 0.6


@dataclass(frozen=True)
class Trade:
    trade_id: str
    entry_ms: int
    exit_ms: int
    net_bps: float
    features: Mapping[str, str]


@dataclass(frozen=True)
class Variant:
    name: str
    keys: tuple[str, ...]
    half_life: float | None = 16.0   # in closes of the same context; None = no decay
    prior_weight: float = 5.0         # pseudo-observations of the global prior
    empirical_bayes: bool = False     # prior weight from estimated noise/between variance
    sign: float = 1.0                 # -1 ranks contexts contrarian (prefer worse history)


BASE_KEYS = ("source", "symbol", "regime", "side")
VARIANTS: tuple[Variant, ...] = (
    Variant("V0_current", BASE_KEYS, 16.0),
    Variant("V1_long_memory", BASE_KEYS, 64.0),
    Variant("V2_no_decay", BASE_KEYS, None),
    Variant("V3_source_side", ("source", "side"), 64.0),
    Variant("V4_symbol_side", ("symbol", "side"), 64.0),
    Variant("V5_source_symbol_side", ("source", "symbol", "side"), 64.0),
    Variant("V6_source_regime_side", ("source", "regime", "side"), 64.0),
    Variant("V7_base_plus_hour", BASE_KEYS + ("hour6",), 64.0),
    Variant("V8_source_prediction", ("source", "pred_bucket"), 64.0),
    Variant("V9_empirical_bayes", BASE_KEYS, None, empirical_bayes=True),
)

# Pre-registered 2026-11-09 (docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md),
# after the anti-persistence was seen on older data; judged ONLY on trades entered
# after the registration timestamp, with no variant search. V0 here is an
# approximation of the live rule (global prior, no cohort/provenance filter).
PREREGISTERED_HYPOTHESIS = "C1_contrarian"
PREREGISTERED: tuple[Variant, ...] = (
    Variant("V0_current", BASE_KEYS, 16.0),
    Variant("V2_no_decay", BASE_KEYS, None),
    Variant("C1_contrarian", BASE_KEYS, None, sign=-1.0),
)
# Amendment 1 (2026-11-09, external audit F02/F11, before any fresh result was read):
# one fixed look. Scored set = the first FINAL_N fresh trades, evaluated only once at
# least FINAL_N fresh trades exist AND FINAL_MIN_DAYS UTC days have elapsed since the
# cutoff. Until then results are withheld (PENDING), so repeated runs cannot peek.
PREREGISTERED_FINAL_N = 1000
PREREGISTERED_MIN_DAYS = 7
BOOTSTRAP_SEED = 20261109
BOOTSTRAP_REPLICATES = 2000
DAY_MS = 86_400_000
# Amendment 1b (same day, after independent review, still before any fresh result):
# - the scored set is taken only when every earlier trade must already be closed
#   (snapshot time >= last scored entry + COMPLETE_MARGIN_MS; max hold is 900 s);
# - bootstrap blocks are 6-hour UTC windows and at least MIN_BLOCKS are required,
#   otherwise INSUFFICIENT_DATA (1 000 trades at ~220/day span only ~5 days).
COMPLETE_MARGIN_MS = 6 * 3_600_000
BLOCK_MS = 6 * 3_600_000
MIN_BLOCKS = 16


class _Stat:
    __slots__ = ("s", "w", "n", "sq")

    def __init__(self) -> None:
        self.s = self.w = self.sq = 0.0
        self.n = 0

    def add(self, x: float, decay: float) -> None:
        self.s = self.s * decay + x
        self.w = self.w * decay + 1.0
        self.sq += x * x
        self.n += 1


def replay(trades: Sequence[Trade], variant: Variant) -> list[float]:
    """Estimates aligned with `trades` order (which must be sorted by entry_ms)."""
    decay = 1.0 if variant.half_life is None else 2 ** (-1 / variant.half_life)
    closes = sorted(range(len(trades)), key=lambda i: (trades[i].exit_ms, trades[i].trade_id))
    contexts: dict[tuple, _Stat] = defaultdict(_Stat)
    total, total_sq, total_n = 0.0, 0.0, 0
    pointer, estimates = 0, []
    key = lambda t: tuple(t.features.get(k, "") for k in variant.keys)
    for trade in trades:
        # Strictly earlier closes only: a close at the same millisecond has no defined order.
        while pointer < len(closes) and trades[closes[pointer]].exit_ms < trade.entry_ms:
            done = trades[closes[pointer]]
            contexts[key(done)].add(done.net_bps, decay)
            total += done.net_bps
            total_sq += done.net_bps ** 2
            total_n += 1
            pointer += 1
        prior = total / total_n if total_n else 0.0
        own = contexts.get(key(trade))
        weight = variant.prior_weight
        if variant.empirical_bayes and total_n >= 30 and len(contexts) >= 3:
            weight = _eb_weight(contexts.values(), total / total_n, total_sq / total_n - (total / total_n) ** 2)
        if own is None or own.w == 0:
            estimates.append(variant.sign * prior)
        else:
            estimates.append(variant.sign * (own.s + prior * weight) / (own.w + weight))
    return estimates


def _eb_weight(stats, grand: float, total_var: float) -> float:
    """Noise variance / between-context variance (method of moments), bounded."""
    usable = [s for s in stats if s.n >= 2]
    if len(usable) < 3 or total_var <= 0:
        return 5.0
    noise = total_var
    between = statistics.mean((s.s / s.w - grand) ** 2 - noise / s.n for s in usable)
    return min(1e6, max(1.0, noise / between)) if between > 0 else 1e6


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


def _spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    sx = math.fsum((a - mx) ** 2 for a in rx)
    sy = math.fsum((b - my) ** 2 for b in ry)
    if sx == 0 or sy == 0:
        return None
    return math.fsum((a - mx) * (b - my) for a, b in zip(rx, ry)) / math.sqrt(sx * sy)


def score(estimates: Sequence[float], nets: Sequence[float]) -> dict:
    """Selection lift: mean net of the upper half by estimate minus the lower half."""
    n = len(estimates)
    if n < 20:
        return {"n": n, "spearman": None, "lift_bps": None, "lift_low_bps": None, "lift_high_bps": None}
    cut = statistics.median(estimates)
    upper = [y for e, y in zip(estimates, nets) if e > cut]
    lower = [y for e, y in zip(estimates, nets) if e <= cut]
    if len(upper) < 5 or len(lower) < 5:
        return {"n": n, "spearman": _spearman(estimates, nets), "lift_bps": None,
                "lift_low_bps": None, "lift_high_bps": None}
    lift = statistics.mean(upper) - statistics.mean(lower)
    se = math.sqrt(statistics.variance(upper) / len(upper) + statistics.variance(lower) / len(lower))
    return {"n": n, "spearman": _spearman(estimates, nets), "lift_bps": lift,
            "lift_low_bps": lift - 1.96 * se, "lift_high_bps": lift + 1.96 * se,
            "upper_n": len(upper), "lower_n": len(lower)}


def validate(trades: Sequence[Trade]) -> list[Trade]:
    """Fail closed on duplicate IDs, non-finite outcomes or non-positive durations."""
    ids = [t.trade_id for t in trades]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_replay_trade_id")
    if any(not math.isfinite(t.net_bps) or t.exit_ms <= t.entry_ms for t in trades):
        raise ValueError("invalid_replay_trade")
    return sorted(trades, key=lambda t: (t.entry_ms, t.trade_id))


def evaluate(trades: Sequence[Trade], variants: Sequence[Variant] = VARIANTS,
             dev_fraction: float = DEV_FRACTION) -> dict:
    trades = validate(trades)
    split = int(len(trades) * dev_fraction)
    nets = [t.net_bps for t in trades]
    results = {}
    for variant in variants:
        est = replay(trades, variant)
        results[variant.name] = {"dev": score(est[:split], nets[:split]),
                                 "holdout": score(est[split:], nets[split:])}
    ranked = [name for name in results if results[name]["dev"]["lift_bps"] is not None]
    chosen = max(ranked, key=lambda name: results[name]["dev"]["lift_bps"]) if ranked else None
    verdict = "INSUFFICIENT_DATA"
    if chosen is not None:
        hold = results[chosen]["holdout"]
        if hold["lift_low_bps"] is None:
            verdict = "INSUFFICIENT_DATA"
        elif hold["lift_low_bps"] > 0:
            verdict = "HOLDOUT_LIFT_CONFIRMED"
        else:
            verdict = "HOLDOUT_LIFT_NOT_CONFIRMED"
    return {"n": len(trades), "dev_n": split, "holdout_n": len(trades) - split,
            "split_entry_ms": trades[split].entry_ms if 0 < split < len(trades) else None,
            "chosen_on_dev": chosen, "verdict": verdict, "variants": results}


def bootstrap_lift(estimates: Sequence[float], nets: Sequence[float], days: Sequence[int], *,
                   seed: int = BOOTSTRAP_SEED, replicates: int | None = None) -> dict:
    """Block bootstrap of the median-split lift over the given block labels (6 h UTC windows)."""
    import random
    replicates = BOOTSTRAP_REPLICATES if replicates is None else replicates
    blocks: dict[int, list[int]] = defaultdict(list)
    for index, day in enumerate(days):
        blocks[day].append(index)
    keys = sorted(blocks)
    rng = random.Random(seed)
    lifts = []
    for _ in range(replicates):
        idx = [i for _k in keys for i in blocks[rng.choice(keys)]]
        result = score([estimates[i] for i in idx], [nets[i] for i in idx])
        if result["lift_bps"] is not None:
            lifts.append(result["lift_bps"])
    if len(keys) < MIN_BLOCKS or len(lifts) < replicates * 0.9:
        return {"blocks": len(keys), "valid": len(lifts), "lower_bps": None, "upper_bps": None}
    lifts.sort()
    return {"blocks": len(keys), "valid": len(lifts),
            "lower_bps": lifts[int(0.025 * len(lifts))], "upper_bps": lifts[int(0.975 * len(lifts)) - 1]}


def scored_count(trades: Sequence[Trade], fresh: Sequence[int]) -> int | None:
    """Amendment 1c: max(FINAL_N, trades needed to cover MIN_BLOCKS 6 h blocks); None = not yet."""
    blocks: set[int] = set()
    for count, index in enumerate(fresh, 1):
        blocks.add(trades[index].entry_ms // BLOCK_MS)
        if count >= PREREGISTERED_FINAL_N and len(blocks) >= MIN_BLOCKS:
            return count
    return None


def evaluate_preregistered(trades: Sequence[Trade], *, scored_after_ms: int, now_ms: int) -> dict:
    """Single fixed look for the PREREGISTERED hypothesis (amendment 1).

    Earlier trades feed the estimates but are never scored. Before the fixed end
    the variant results are withheld (verdict PENDING).
    """
    trades = validate(trades)
    fresh = [i for i, t in enumerate(trades) if t.entry_ms > scored_after_ms]
    days_elapsed = (now_ms - scored_after_ms) / DAY_MS
    base = {"scored_after_ms": scored_after_ms, "fresh_n": len(fresh), "final_n": PREREGISTERED_FINAL_N,
            "min_days": PREREGISTERED_MIN_DAYS, "days_elapsed": round(days_elapsed, 2)}
    needed = scored_count(trades, fresh)
    if (needed is None or days_elapsed < PREREGISTERED_MIN_DAYS
            or now_ms < trades[fresh[needed - 1]].entry_ms + COMPLETE_MARGIN_MS):
        return {**base, "verdict": "PENDING", "variants": None}
    scored = fresh[:needed]
    nets = [trades[i].net_bps for i in scored]
    days = [trades[i].entry_ms // BLOCK_MS for i in scored]
    results = {}
    for variant in PREREGISTERED:
        est = replay(trades, variant)
        picked = [est[i] for i in scored]
        results[variant.name] = {**score(picked, nets), "day_bootstrap": bootstrap_lift(picked, nets, days)}
    hypothesis = results[PREREGISTERED_HYPOTHESIS]
    boot = hypothesis["day_bootstrap"]
    if hypothesis["lift_low_bps"] is None or boot["lower_bps"] is None:
        verdict = "INSUFFICIENT_DATA"
    elif hypothesis["lift_low_bps"] > 0 and boot["lower_bps"] > 0:
        verdict = "CONTRARIAN_CONFIRMED"
    elif hypothesis["lift_high_bps"] < 0 and boot["upper_bps"] < 0:
        verdict = "CONTRARIAN_REFUTED"
    else:
        verdict = "CONTRARIAN_NOT_SHOWN"
    return {**base, "scored_last_entry_ms": trades[scored[-1]].entry_ms, "verdict": verdict, "variants": results,
            "scored_trade_ids": [trades[i].trade_id for i in scored]}
