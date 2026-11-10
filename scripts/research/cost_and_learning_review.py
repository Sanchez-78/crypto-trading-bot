#!/usr/bin/env python3
"""Offline cost-sensitivity and learning-vs-profit review from FROZEN inputs only.

Consumer of existing evidence, not a simulator or evaluator:
- futures-flow screen report.json (already consumed HOLDOUT; no re-run, no bootstrap);
- optionally a frozen C1 prereg_result.json, accepted only through the provenance
  contract below. Raw post-cutoff trades are never read by this tool.

C1 provenance contract (c1_provenance_v1), trust boundary:
  trusted reference = --c1-provenance-sha256, recorded independently when the C1
  result was frozen (not derived from the files being checked)
    -> provenance manifest bytes must hash to it (read once, parsed from the same bytes)
    -> manifest names hypothesis, cutoff, run_id, evaluated_at_ms, result_sha256
    -> prereg_result.json bytes must hash to result_sha256 (read once, same bytes parsed)
    -> structural/protocol consistency of the result (no statistics recomputed)
    -> only then the optional mu aggregate (c1_mu_v1), bound to the same result.
  Output "inputs" keeps observed hashes of bytes actually read (null if not read) apart from
  the expected references. The mu hash identifies the file used; it does not prove that mu
  was computed correctly or by whom.
  Missing C1 -> PENDING. Missing reference/manifest -> NOT_VERIFIED and the result file
  is not opened. Corrupt or inconsistent artefacts -> error (exit 2). An optional mu with
  no verified final C1 is refused before it is opened (exit 3).
  Today's server runs (deploy/research_eval/run_eval.sh) do not write this manifest, so a
  real prereg_result.json stays NOT_VERIFIED until one is recorded at freeze time.

No DB, network, Firebase or executor imports. Output: review.json + review.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Optional

SCHEMA_VERSION = 3
COSTS_BPS = (0.0, 9.0, 15.0, 18.0, 20.0)
RESERVE_BPS = 3.0
TP_BPS, SL_BPS = 35.0, 25.0
BLOCKS = ("TRAIN", "TEST", "HOLDOUT")
HYPOTHESES = ("H1", "H2", "H3", "H4", "H5", "H6", "H7")
TARGETS = ("r15", "tpsl")
UNIVERSE = ("ADAUSDT", "BNBUSDT", "BTCUSDT", "DOTUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
# Fixed-interval series (futures_flow_screen.source_coverage): unique timestamps on a grid
# from the block start, so rows + missing_rows == expected_rows; ranges are maximal runs.
SOURCE_STEP_MS = {"futures": 60_000, "spot": 60_000, "metrics": 300_000}
GAP_SOURCES = tuple(SOURCE_STEP_MS)
EVENT_SOURCES = ("funding",)  # irregular calendar: presence only, no gap inference

# C1 protocol, from docs/remediation/LEARNER_PREREGISTRATION_2026-11-09.md (amendments 1-1c)
# and src/services/learner_replay.py:56-78 -- never taken from the artefact under review.
C1_HYPOTHESIS = "C1_contrarian"
C1_CUTOFF_MS = 1_794_209_516_000
C1_MIN_SCORED = 1000
C1_MIN_BLOCKS = 16
C1_BLOCK_MS = 6 * 3_600_000  # learner_replay.BLOCK_MS: 6 h UTC blocks by entry time
C1_MIN_ELAPSED_MS = 7 * 86_400_000
C1_COMPLETE_MARGIN_MS = 6 * 3_600_000
# learner_replay.bootstrap_lift: 2 000 replicates (BOOTSTRAP_REPLICATES); a finite CI is only
# emitted with >= 90 % valid replicates (learner_replay.py:230).
C1_BOOTSTRAP_REPLICATES = 2000
C1_MIN_VALID_REPLICATES = 1800
# learner_replay.score: upper = estimate > median, lower = estimate <= median, and a finite
# lift needs >= 5 members in each group (learner_replay.py:160-175).
C1_MIN_GROUP = 5
C1_FINAL = ("CONTRARIAN_CONFIRMED", "CONTRARIAN_REFUTED", "CONTRARIAN_NOT_SHOWN")
C1_NOT_FINAL = ("PENDING", "INSUFFICIENT_DATA")
PROVENANCE_CONTRACT = "c1_provenance_v1"
MU_CONTRACT = "c1_mu_v1"
MU_UNIT = "bps"
MU_COST_BASIS = "paper_net_9bps"
# Stable ID-list hash convention (versioned with PROVENANCE_CONTRACT).
ID_HASH_CONVENTION = "sha256(utf8(json.dumps(ids, separators=(',', ':'))))"

# Public schedule checked 2026-11-10 (dated scenario, not the account's verified tier).
FEE_SCENARIOS = {
    "effective_date": "2026-11-10",
    "paper_settlement": {"fee_round_trip_bps": 8.0, "slippage_round_trip_bps": 1.0,
                         "source": "PAPER_FEE_PCT=0.0008, PAPER_SLIPPAGE_PCT=0.0001 (server env)"},
    "binance_spot_vip0": {"maker_bps_per_side": 10.0, "taker_bps_per_side": 10.0,
                          "bnb_discount_bps_per_side": 7.5, "source": "https://www.binance.com/en/fee/trading"},
    "binance_usdm_regular": {"maker_bps_per_side": 2.0, "taker_bps_per_side": 5.0, "bnb_discount": "10 %",
                             "source": "https://www.binance.com/support/faq/360033544231"},
}

EXIT_INVALID = 2
EXIT_REFUSED = 3


class ReviewError(ValueError):
    """Corrupt or inconsistent input (exit 2)."""


class BlindingRefusal(ReviewError):
    """Input that the blinding rules forbid opening (exit 3)."""


def pct_to_bps(fraction: float) -> float:
    """Fraction (0.0008) -> bps (8). 0.01 % = 0.0001 = 1 bps."""
    return _finite(fraction, "fraction") * 10_000.0


def round_trip_bps(per_side_bps: float) -> float:
    return 2.0 * _finite(per_side_bps, "per_side_bps")


def two_point_breakeven_wr(cost_bps: float) -> dict:
    """WR_BE = (SL + c) / (TP + SL). Approximation: only valid if every exit is exactly TP or SL."""
    _finite(cost_bps, "cost_bps")
    return {"cost_bps": cost_bps, "wr_be": (SL_BPS + cost_bps) / (TP_BPS + SL_BPS),
            "status": "APPROXIMATION_TWO_POINT", "invalid_with_timeouts": True}


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReviewError(f"{name} must be a finite number")
    return float(value)


def _count(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReviewError(f"{name} must be an int >= {minimum}")
    return value


def _interval(value: Any, name: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ReviewError(f"{name} must be a [lower, upper] pair")
    lower, upper = (_finite(v, name) for v in value)
    if lower > upper:
        raise ReviewError(f"{name} is reversed")
    return lower, upper


def _reject_constant(token: str) -> None:
    raise ReviewError(f"non-finite JSON constant {token}")


def _no_duplicates(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ReviewError(f"duplicate JSON key {key!r}")
        out[key] = value
    return out


def parse_json(raw: bytes, label: str) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewError(f"corrupt JSON in {label}") from exc
    if not isinstance(data, dict):
        raise ReviewError(f"{label} must contain a JSON object")
    return data


def load_json(path: Path) -> tuple[dict, str]:
    """Read once; the hash and the parsed object come from the same bytes."""
    raw = path.read_bytes()
    return parse_json(raw, str(path)), hashlib.sha256(raw).hexdigest()


def id_hash(ids: list) -> str:
    return hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- futures

def sensitivity(stats: dict, label: str) -> dict:
    """Arithmetic shift of the frozen gross mean and its existing CI by constant costs."""
    n = _count(stats.get("n"), f"{label}.n")
    if n == 0:
        return {"status": "NO_DATA", "n": 0}
    gross = _finite(stats.get("gross_bps"), f"{label}.gross_bps")
    lo9, hi9 = _interval(stats.get("ci95_net9"), f"{label}.ci95_net9")
    gross_ci = (lo9 + 9.0, hi9 + 9.0)  # existing interval, re-expressed gross; no new bootstrap
    return {
        "status": "OK", "n": n, "gross_bps": gross, "gross_ci95": list(gross_ci),
        "net": {f"{c:g}": {"mean_bps": gross - c, "ci95": [gross_ci[0] - c, gross_ci[1] - c]} for c in COSTS_BPS},
        "breakeven_cost_bps": gross,
        "cost_budget_with_reserve_bps": gross - RESERVE_BPS,
        "conservative_budget_from_ci_low_bps": gross_ci[0] - RESERVE_BPS,
        "derivation": "net(c) = gross - c; CI shifted by c; budgets are arithmetic derivations, not new tests",
    }


def _block(report: dict, block: str) -> dict:
    data = report.get(block)
    if not isinstance(data, dict):
        raise ReviewError(f"report missing phase {block}")
    return data


def futures_cost_table(report: dict) -> dict:
    table: dict = {}
    for block in BLOCKS:
        statistics = _block(report, block).get("statistics")
        if not isinstance(statistics, dict):
            raise ReviewError(f"report missing {block}.statistics")
        unknown = set(statistics) - set(HYPOTHESES)
        if unknown:
            raise ReviewError(f"{block}: unsupported hypotheses {sorted(unknown)}")
        for hyp in HYPOTHESES:
            entry = statistics.get(hyp)
            if not isinstance(entry, dict):
                raise ReviewError(f"report missing {block}.{hyp}")
            for target in TARGETS:
                stats = entry.get(target)
                if not isinstance(stats, dict):
                    raise ReviewError(f"report missing {block}.{hyp}.{target}")
                # n lives on the hypothesis in the frozen screen; a nested n must not override it.
                if "n" in stats and stats["n"] != entry.get("n"):
                    raise ReviewError(f"{block}.{hyp}.{target}: n conflicts with hypothesis n")
                merged = {**stats, "n": entry.get("n")}
                table.setdefault(hyp, {}).setdefault(block, {})[target] = sensitivity(merged, f"{block}.{hyp}.{target}")
    return table


def _check_gap_source(src: dict, label: str, step: int, bounds: Optional[tuple[int, int]]) -> tuple[int, int, bool]:
    """Validate one fixed-interval source; returns (ranges, missing_rows, no_data)."""
    if "rows" not in src:
        raise _MissingEvidence(f"{label}: rows missing")
    rows = _count(src.get("rows"), f"{label}.rows")
    expected = _count(src.get("expected_rows"), f"{label}.expected_rows")
    missing = _count(src.get("missing_rows"), f"{label}.missing_rows")
    gaps = src.get("missing_ranges")
    if not isinstance(gaps, list):
        raise ReviewError(f"{label}: missing_ranges must be a list")
    if expected == 0:
        raise _MissingEvidence(f"{label}: no expected rows")
    if missing > expected or rows + missing != expected:
        raise ReviewError(f"{label}: rows + missing_rows != expected_rows")
    if bounds is not None and expected != -(-(bounds[1] - bounds[0]) // step):
        raise ReviewError(f"{label}: expected_rows does not match the block span")
    previous_end = None
    total = 0
    for gap in gaps:
        if not isinstance(gap, dict):
            raise ReviewError(f"{label}: malformed missing range")
        start = _count(gap.get("start_ms"), f"{label}.range.start_ms")
        end = _count(gap.get("end_exclusive_ms"), f"{label}.range.end_exclusive_ms")
        count = _count(gap.get("count"), f"{label}.range.count", minimum=1)
        if end <= start or end - start != count * step:
            raise ReviewError(f"{label}: range length does not match count and interval")
        if previous_end is not None and start <= previous_end:
            raise ReviewError(f"{label}: ranges overlap, touch or are unordered")
        if bounds is not None and (start < bounds[0] or end > bounds[1] or (start - bounds[0]) % step):
            raise ReviewError(f"{label}: range outside the block grid")
        previous_end = end
        total += count
    if total != missing:
        raise ReviewError(f"{label}: range counts do not add up to missing_rows")
    return len(gaps), missing, rows == 0


class _MissingEvidence(Exception):
    """Absent (not contradictory) coverage evidence -> NOT_VERIFIED."""


def coverage_review(report: dict) -> dict:
    """OK only for positively documented complete coverage; documented gaps -> PARTIAL."""
    blocks: dict = {}
    for block in BLOCKS:
        data = _block(report, block)
        coverage = data.get("coverage")
        start, end = data.get("start_ms"), data.get("end_ms")
        bounds = None
        if start is not None or end is not None:
            bounds = (_count(start, f"{block}.start_ms"), _count(end, f"{block}.end_ms"))
            if bounds[1] <= bounds[0]:
                raise ReviewError(f"{block}: end_ms not after start_ms")
        problems: list[str] = []
        no_data: list[str] = []
        ranges = rows = 0
        if not isinstance(coverage, list) or not coverage:
            problems.append("coverage missing or empty")
            coverage = []
        seen = set()
        for entry in coverage:
            if not isinstance(entry, dict) or not isinstance(entry.get("sources"), dict):
                raise ReviewError(f"{block}: malformed coverage entry")
            symbol = entry.get("symbol")
            if symbol in seen:
                raise ReviewError(f"{block}: duplicate coverage symbol {symbol!r}")
            seen.add(symbol)
            sources = entry["sources"]
            for name in GAP_SOURCES:
                src = sources.get(name)
                if not isinstance(src, dict):
                    problems.append(f"{symbol}: source {name} missing")
                    continue
                try:
                    n_ranges, n_missing, empty = _check_gap_source(
                        src, f"{block}.{symbol}.{name}", SOURCE_STEP_MS[name], bounds)
                except _MissingEvidence as exc:
                    problems.append(str(exc))
                    continue
                ranges += n_ranges
                rows += n_missing
                if empty:
                    no_data.append(f"{symbol}: source {name} has no rows")
            for name in EVENT_SOURCES:
                src = sources.get(name)
                if not isinstance(src, dict) or _count(src.get("rows"), f"{block}.{symbol}.{name}.rows") == 0:
                    problems.append(f"{symbol}: source {name} missing or empty")
        for symbol in UNIVERSE:
            if symbol not in seen:
                problems.append(f"symbol {symbol} missing")
        unexpected = seen - set(UNIVERSE)
        if unexpected:
            problems.append(f"unexpected symbols {sorted(unexpected)}")
        status = ("NOT_VERIFIED" if problems else "NO_DATA" if no_data else "PARTIAL" if ranges else "OK")
        blocks[block] = {"status": status, "missing_range_count": ranges,
                         "missing_rows_by_source_interval": rows, "problems": problems + no_data,
                         "grid_bounds_checked": bounds is not None}
    order = {"OK": 0, "PARTIAL": 1, "NO_DATA": 2, "NOT_VERIFIED": 3}
    overall = max((b["status"] for b in blocks.values()), key=order.__getitem__)
    return {"status": overall, "blocks": blocks,
            "missing_range_count": sum(b["missing_range_count"] for b in blocks.values()),
            "missing_rows_by_source_interval": sum(b["missing_rows_by_source_interval"] for b in blocks.values()),
            "note": "ranges != minutes; rows are in each source's own interval (1m futures/spot, 5m metrics); "
                    "funding is checked for presence only; grid bounds are checked only where the "
                    "frozen block stores start_ms/end_ms"}


# --------------------------------------------------------------------- C1

def split_means(mu: float, lift: float, upper_n: int, lower_n: int) -> dict:
    """Group means implied by overall mean mu and lift for the SAME scored set (no CI)."""
    _count(upper_n, "upper_n", minimum=1)
    _count(lower_n, "lower_n", minimum=1)
    _finite(mu, "mu")
    _finite(lift, "lift")
    q = upper_n / (upper_n + lower_n)
    return {"q": q, "mean_upper_bps": mu + (1 - q) * lift, "mean_lower_bps": mu - q * lift,
            "status": "DERIVED_POINT_ESTIMATE_NO_CI"}


def verify_provenance(manifest: dict) -> dict:
    if manifest.get("contract") != PROVENANCE_CONTRACT:
        raise ReviewError("unsupported C1 provenance contract")
    if manifest.get("hypothesis") != C1_HYPOTHESIS:
        raise ReviewError("provenance names a different hypothesis")
    if manifest.get("scored_after_ms") != C1_CUTOFF_MS:
        raise ReviewError("provenance cutoff differs from the preregistration")
    if manifest.get("id_hash_convention") != ID_HASH_CONVENTION:
        raise ReviewError("provenance uses an unknown ID hash convention")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ReviewError("provenance lacks run_id")
    result_sha = manifest.get("result_sha256")
    if not isinstance(result_sha, str) or len(result_sha) != 64:
        raise ReviewError("provenance lacks result_sha256")
    evaluated = _count(manifest.get("evaluated_at_ms"), "provenance.evaluated_at_ms", minimum=1)
    return {"run_id": run_id, "result_sha256": result_sha, "evaluated_at_ms": evaluated}


def verify_result(result: dict, prov: dict) -> dict:
    """Consistency of the supplied frozen result with the protocol; no recomputation."""
    if result.get("scored_after_ms") != C1_CUTOFF_MS:
        raise ReviewError("result cutoff differs from the preregistration")
    if result.get("final_n") != C1_MIN_SCORED or result.get("min_days") != 7:
        raise ReviewError("result protocol constants differ from the preregistration")
    verdict = result.get("verdict")
    if verdict in C1_NOT_FINAL:
        return {"status": verdict}
    if verdict not in C1_FINAL:
        raise ReviewError("unknown C1 verdict")
    ids = result.get("scored_trade_ids")
    if not isinstance(ids, list) or not ids:
        raise ReviewError("scored_trade_ids missing or empty")
    # learner_replay_report.to_trade: Trade IDs are str(trade_id) and never empty.
    if any(not isinstance(i, str) or not i for i in ids):
        raise ReviewError("scored_trade_ids must be non-empty strings")
    if len(set(ids)) != len(ids):
        raise ReviewError("scored_trade_ids contain duplicates")
    if len(ids) < C1_MIN_SCORED:
        raise ReviewError("fewer scored trades than the protocol minimum")
    fresh_n = _count(result.get("fresh_n"), "fresh_n")
    if fresh_n < len(ids):
        raise ReviewError("fresh_n smaller than the scored prefix")
    hyp = (result.get("variants") or {}).get(C1_HYPOTHESIS)
    if not isinstance(hyp, dict):
        raise ReviewError("result lacks the C1_contrarian variant")
    upper_n = _count(hyp.get("upper_n"), "upper_n", minimum=1)
    lower_n = _count(hyp.get("lower_n"), "lower_n", minimum=1)
    if upper_n + lower_n != len(ids) or _count(hyp.get("n"), "n") != len(ids):
        raise ReviewError("group counts do not add up to the scored IDs")
    if upper_n > len(ids) // 2:
        raise ReviewError("upper median group larger than half of the scored set")
    if min(upper_n, lower_n) < C1_MIN_GROUP:
        raise ReviewError("median group smaller than the protocol minimum")
    lift = _finite(hyp.get("lift_bps"), "lift_bps")
    welch = _interval([hyp.get("lift_low_bps"), hyp.get("lift_high_bps")], "Welch CI")
    boot = hyp.get("day_bootstrap")
    if not isinstance(boot, dict):
        raise ReviewError("block bootstrap missing")
    boot_ci = _interval([boot.get("lower_bps"), boot.get("upper_bps")], "block bootstrap CI")
    valid = _count(boot.get("valid"), "bootstrap valid replicates")
    if not C1_MIN_VALID_REPLICATES <= valid <= C1_BOOTSTRAP_REPLICATES:
        raise ReviewError("bootstrap valid replicates outside the protocol range")
    blocks = _count(boot.get("blocks"), "bootstrap blocks")
    if blocks < C1_MIN_BLOCKS:
        raise ReviewError("fewer 6h blocks than the protocol minimum")
    last_entry = _count(result.get("scored_last_entry_ms"), "scored_last_entry_ms", minimum=1)
    if last_entry <= C1_CUTOFF_MS:
        raise ReviewError("last scored entry is not after the cutoff")
    # Necessary condition only: distinct blocks cannot exceed the trades or the 6h blocks
    # spanned by (cutoff, last_entry]. Individual entry timestamps are not in the artefact.
    max_blocks = last_entry // C1_BLOCK_MS - (C1_CUTOFF_MS + 1) // C1_BLOCK_MS + 1
    if blocks > min(len(ids), max_blocks):
        raise ReviewError("more 6h blocks than the scored trades or time span allow")
    evaluated = prov["evaluated_at_ms"]
    if evaluated - C1_CUTOFF_MS < C1_MIN_ELAPSED_MS:
        raise ReviewError("evaluation earlier than 7 x 24 h after the cutoff")
    if evaluated < last_entry + C1_COMPLETE_MARGIN_MS:
        raise ReviewError("evaluation earlier than 6 h after the last scored entry")
    expected = ("CONTRARIAN_CONFIRMED" if welch[0] > 0 and boot_ci[0] > 0 else
                "CONTRARIAN_REFUTED" if welch[1] < 0 and boot_ci[1] < 0 else "CONTRARIAN_NOT_SHOWN")
    if verdict != expected:
        raise ReviewError("declared verdict is inconsistent with the declared intervals")
    return {
        "status": verdict, "lift_bps": lift, "lift_ci95_welch": list(welch),
        "lift_ci95_block_bootstrap": list(boot_ci), "bootstrap_unit": "6h UTC blocks",
        "bootstrap_blocks": blocks, "upper_n": upper_n, "lower_n": lower_n, "scored_n": len(ids),
        "scored_set_sha256": id_hash(ids), "id_hash_convention": ID_HASH_CONVENTION,
        "run_id": prov["run_id"], "result_sha256": prov["result_sha256"], "profitability": "NOT_VERIFIED",
    }


def verify_mu(mu: dict, c1: dict) -> dict:
    if mu.get("contract") != MU_CONTRACT:
        raise ReviewError("unsupported mu contract")
    for key, expected in (("result_sha256", c1["result_sha256"]), ("scored_set_sha256", c1["scored_set_sha256"]),
                          ("scored_after_ms", C1_CUTOFF_MS), ("unit", MU_UNIT), ("cost_basis", MU_COST_BASIS)):
        if mu.get(key) != expected:
            raise ReviewError(f"mu {key} does not match the verified C1 result")
    return split_means(_finite(mu.get("mu_bps"), "mu_bps"), c1["lift_bps"], c1["upper_n"], c1["lower_n"])


def empty_identity(provenance_sha: Optional[str]) -> dict:
    """Input identity: *_observed = hash of bytes actually read (null if not read);
    *_expected = reference compared against. A reference is never reported as observed."""
    return {"c1_provenance_sha256_expected": provenance_sha or None, "c1_provenance_sha256_observed": None,
            "c1_provenance_verified": False, "c1_result_sha256_expected": None,
            "c1_result_sha256_observed": None, "c1_result_verified": False,
            "c1_mu_sha256_observed": None, "c1_run_id": None}


def c1_review(result_path: Optional[Path], provenance_path: Optional[Path], provenance_sha: Optional[str],
              mu_path: Optional[Path], loader: Callable[[Path], tuple[dict, str]], exposure: dict,
              identity: dict) -> dict:
    def refuse_mu(reason: str) -> None:
        if mu_path is not None:
            raise BlindingRefusal(f"--c1-mu refused without a verified final C1 ({reason}); mu was not opened")

    if result_path is None:
        refuse_mu("no C1 result")
        return {"status": "PENDING", "reason": "no frozen prereg_result.json supplied"}
    if provenance_path is None or not provenance_sha:
        refuse_mu("no trusted provenance")
        return {"status": "NOT_VERIFIED", "reason": "no provenance manifest and trusted reference hash; "
                "the result file was not opened", "missing": ["--c1-provenance", "--c1-provenance-sha256"]}
    manifest, manifest_sha = loader(provenance_path)
    identity["c1_provenance_sha256_observed"] = manifest_sha
    if manifest_sha != provenance_sha:
        refuse_mu("provenance hash mismatch")
        return {"status": "NOT_VERIFIED", "reason": "provenance manifest does not match the trusted reference; "
                "the result file was not opened"}
    identity["c1_provenance_verified"] = True
    prov = verify_provenance(manifest)
    identity["c1_result_sha256_expected"] = prov["result_sha256"]
    identity["c1_run_id"] = prov["run_id"]
    exposure["frozen_c1_result_read"] = True
    result, result_sha = loader(result_path)
    identity["c1_result_sha256_observed"] = result_sha
    if result_sha != prov["result_sha256"]:
        refuse_mu("result hash mismatch")
        return {"status": "NOT_VERIFIED", "reason": "result bytes do not match the provenance manifest"}
    identity["c1_result_verified"] = True
    c1 = verify_result(result, prov)
    if c1["status"] in C1_NOT_FINAL:
        refuse_mu(c1["status"])
        return {**c1, "reason": "frozen artefact is not a final verdict"}
    if mu_path is not None:
        exposure["frozen_c1_mu_read"] = True
        # Identity of the bytes used, not proof that mu was computed correctly or by whom.
        mu, mu_sha = loader(mu_path)
        identity["c1_mu_sha256_observed"] = mu_sha
        c1["split"] = verify_mu(mu, c1)
    return c1


def four_questions(c1: dict, coverage: dict) -> list[dict]:
    return [
        {"question": "Jsou data použitelná?", "status": coverage["status"],
         "evidence": f"{coverage['missing_range_count']} rozsahů mezer v pokrytí futures screenu; checksum != coverage"},
        {"question": "Umí learner lépe seřadit kandidáty?", "status": c1["status"],
         "evidence": "jen ověřený zmrazený verdikt C1"},
        {"question": "Má vybraná politika kladný net?", "status": "NOT_VERIFIED",
         "evidence": "kladný lift není důkaz kladného post-cost výsledku"},
        {"question": "Je připravena změna bota?", "status": "NO",
         "evidence": "vyžaduje nový protokol, review a autorizovanou replikaci"},
    ]


def render(review: dict) -> str:
    exp = review["exposure"]
    yes = lambda flag: "ano" if flag else "ne"
    lines = ["# Přehled nákladů a učení (offline, zmrazené vstupy)", "",
             f"Schéma {review['schema_version']}. Ceník k {FEE_SCENARIOS['effective_date']} (datovaný scénář, "
             "ne ověřený tier účtu).", "",
             "## Čtyři otázky", "", "| Otázka | Stav | Důkaz |", "|---|---|---|"]
    lines += [f"| {q['question']} | {q['status']} | {q['evidence']} |" for q in review["four_questions"]]
    cov = review["coverage"]
    lines += ["", f"Pokrytí: **{cov['status']}**, rozsahů mezer {cov['missing_range_count']}, chybějících řádků "
              f"(v intervalu zdroje) {cov['missing_rows_by_source_interval']}."]
    lines += ["", "## Bod zvratu WR (dvoubodová aproximace, neplatí při timeoutech)", "",
              "| náklad bps | WR_BE |", "|---:|---:|"]
    lines += [f"| {w['cost_bps']:g} | {w['wr_be'] * 100:.2f} % |" for w in review["breakeven_wr"]]
    lines += ["", "## Futures screen: náklad bodu zvratu (HOLDOUT, odvození)", "",
              "| Hyp. | Target | n | gross [CI] | bod zvratu | rozpočet s rezervou 3 | konzervativně z dolní meze |",
              "|---|---|---:|---|---:|---:|---:|"]
    for hyp, blocks in review["futures_cost_table"].items():
        for target, s in blocks["HOLDOUT"].items():
            if s["status"] == "NO_DATA":
                lines.append(f"| {hyp} | {target} | 0 | NO_DATA | — | — | — |")
                continue
            lo, hi = s["gross_ci95"]
            lines.append(f"| {hyp} | {target} | {s['n']} | {s['gross_bps']:.2f} [{lo:.2f}; {hi:.2f}] | "
                         f"{s['breakeven_cost_bps']:.2f} | {s['cost_budget_with_reserve_bps']:.2f} | "
                         f"{s['conservative_budget_from_ci_low_bps']:.2f} |")
    c1 = review["c1"]
    lines += ["", "## C1", "", f"Stav: **{c1['status']}**.", "",
              f"Čtení: raw post-cutoff obchody {yes(exp['raw_post_cutoff_trades_read'])} (nástroj je nikdy nečte); "
              f"zmrazený výsledek C1 {yes(exp['frozen_c1_result_read'])}; "
              f"zmrazený agregát mu {yes(exp['frozen_c1_mu_read'])}.", ""]
    ids = review["inputs"]
    lines.append(f"Vstupy: manifest očekávaný `{ids['c1_provenance_sha256_expected']}`, přečtený "
                 f"`{ids['c1_provenance_sha256_observed']}` (shoda {yes(ids['c1_provenance_verified'])}); "
                 f"výsledek očekávaný `{ids['c1_result_sha256_expected']}`, přečtený "
                 f"`{ids['c1_result_sha256_observed']}` (shoda {yes(ids['c1_result_verified'])}); "
                 f"mu přečtené `{ids['c1_mu_sha256_observed']}` (identita bytů, ne důkaz správnosti mu).")
    lines.append("")
    if c1.get("reason"):
        lines.append(f"Důvod: {c1['reason']}.")
    if c1["status"] in C1_FINAL:
        lines.append(f"Lift {c1['lift_bps']} bps, Welch {c1['lift_ci95_welch']}, bootstrap (6h bloky, "
                     f"{c1['bootstrap_blocks']}) {c1['lift_ci95_block_bootstrap']}, upper_n {c1['upper_n']}, "
                     f"lower_n {c1['lower_n']}, run {c1['run_id']}. Ziskovost: NOT_VERIFIED.")
    lines += ["", "Záporný rozpočet = rezerva nevychází ani při nulovém nákladu. Maker mění i výběr a ceny fillů; "
              "nelze odvodit pouhým odečtením menšího fee.", ""]
    return "\n".join(lines)


def build(report_path: Path, c1_path: Optional[Path] = None, mu_path: Optional[Path] = None, *,
          provenance_path: Optional[Path] = None, provenance_sha: Optional[str] = None,
          loader: Optional[Callable[[Path], tuple[dict, str]]] = None) -> dict:
    load = loader or load_json
    report, report_sha = load(report_path)
    table = futures_cost_table(report)
    coverage = coverage_review(report)
    exposure = {"raw_post_cutoff_trades_read": False, "frozen_c1_result_read": False, "frozen_c1_mu_read": False}
    identity = empty_identity(provenance_sha)
    c1 = c1_review(c1_path, provenance_path, provenance_sha, mu_path, load, exposure, identity)
    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {"futures_report_sha256": report_sha, **identity},
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "units": "bps; 1 bps = 0.01 % = 0.0001 fraction; costs are round-trip unless named per_side",
        "fee_scenarios": FEE_SCENARIOS,
        "breakeven_wr": [two_point_breakeven_wr(c) for c in COSTS_BPS],
        "futures_cost_table": table,
        "coverage": coverage,
        "c1": c1,
        "exposure": exposure,
        "four_questions": four_questions(c1, coverage),
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--futures-report", type=Path, required=True)
    parser.add_argument("--c1-result", type=Path, help="frozen prereg_result.json (optional)")
    parser.add_argument("--c1-provenance", type=Path, help="c1_provenance_v1 manifest for --c1-result")
    parser.add_argument("--c1-provenance-sha256", help="trusted reference hash of the manifest, recorded at freeze")
    parser.add_argument("--c1-mu", type=Path, help="c1_mu_v1 JSON for the same verified scored set")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    inputs = {p.resolve() for p in (args.futures_report, args.c1_result, args.c1_provenance, args.c1_mu) if p}
    targets = [args.out / "review.json", args.out / "review.md"]
    for target in targets:
        if target.resolve() in inputs:
            raise ReviewError(f"refusing to overwrite input {target}")
        if target.exists():
            raise ReviewError(f"refusing to overwrite existing output {target}; use a new --out")
    review = build(args.futures_report, args.c1_result, args.c1_mu, provenance_path=args.c1_provenance,
                   provenance_sha=args.c1_provenance_sha256)
    args.out.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(review, indent=2, sort_keys=True, allow_nan=False), encoding="utf-8")
    targets[1].write_text(render(review), encoding="utf-8")
    print(f"c1={review['c1']['status']} coverage={review['coverage']['status']} out={args.out}")
    return 0


def cli(argv: Optional[list[str]] = None) -> int:
    try:
        return main(argv)
    except BlindingRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except ReviewError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    sys.exit(cli())
