"""Offline description of closed evidence; never recommends or admits trades.

SQLite is opened read-only. Only report.json/report.md under --out are written.
Missing predictions remain NO_DATA. UTC-day bootstrap preserves within-day
dependence, but few days and cross-day dependence limit its interpretation.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import random
import re
import sqlite3
import statistics
import tempfile
from typing import Any, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.core.trade_metrics_contract import classify_outcome
from src.services.evidence_budget import decide_evidence_budget
from src.services.learning_experiment_verdict import evaluate_selection_experiment

BOOTSTRAP_SEED = 20261002
BOOTSTRAP_REPLICATES = 2000
NO_DATA = "NO_DATA"


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-standard JSON constant: " + value)


def parse_policy_tag(tags_json: Any) -> dict:
    """One validated policy per row; unrelated string tags are not policies.

    Invalid/ambiguous declarations are counted once per trade and excluded from
    experiment arms. Missing declarations stay NO_POLICY, never CONTROL.
    """
    def absent(status: str) -> dict:
        return dict(status=status, policy_version=status, policy_action=status, policy_probability=None)
    if tags_json is None or tags_json == "":
        return absent("NO_POLICY")
    if not isinstance(tags_json, str):
        return absent("INVALID_TAG")
    try:
        tags = json.loads(tags_json, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            return absent("INVALID_TAG")
        matches = [tag for tag in tags if tag.startswith("paper_source_learning")]
        if not matches:
            return absent("NO_POLICY")
        if len(matches) != 1:
            return absent("INVALID_TAG")
        prefix, separator, payload = matches[0].partition(":")
        if not separator or not re.fullmatch(r"paper_source_learning(?:_[a-zA-Z0-9]+)+", prefix):
            return absent("INVALID_TAG")
        policy = json.loads(payload, object_pairs_hook=_unique_json_object, parse_constant=_reject_json_constant)
        if not isinstance(policy, dict) or policy.get("policy_version") != prefix:
            return absent("INVALID_TAG")
        action, probability = policy.get("policy_action"), policy.get("policy_probability")
        if (action not in ("ADAPTIVE", "CONTROL", "WARMUP", "PROBE", "HOLD")
                or type(probability) not in (int, float) or not 0 <= probability <= 1
                or not math.isfinite(probability)):
            return absent("INVALID_TAG")
        return dict(status="OK", policy_version=prefix, policy_action=action, policy_probability=probability)
    except (ValueError, TypeError, RecursionError):
        return absent("INVALID_TAG")


def learning_profile(source: str) -> str:
    for suffix in ("paper_probe_v2", "closed_v2", "v1"):
        if source.endswith("_" + suffix):
            return suffix
    return "UNKNOWN_PROFILE"


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def load_rows(*, db: Path | None = None, json_path: Path | None = None,
              since: float | None = None) -> list[dict]:
    """--since selects entry time, matching the canonical performance epoch.

    Without --since, report all supplied rows; never guess a live epoch or load
    the write-on-import cache module. Invalid core observations fail explicitly.
    """
    if (db is None) == (json_path is None):
        raise ValueError("Select exactly one of --db / --json")
    if since is not None and _number(since) is None:
        raise ValueError("--since must be finite")
    if db is not None:
        connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.row_factory = sqlite3.Row
            rows = [dict(row) for row in connection.execute("SELECT * FROM closed_trades")]
        finally:
            connection.close()
    else:
        document = json.loads(json_path.read_text(encoding="utf-8"))
        rows = document.get("rows") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            raise ValueError("Evidence JSON must contain a rows list")
    selected = []
    for original in rows:
        if not isinstance(original, dict):
            raise ValueError("Invalid trade row")
        row = dict(original)
        entry = _number(row.get("entry_ts"))
        if entry is None:
            raise ValueError("Invalid entry timestamp")
        if since is not None and entry < since:
            continue
        exit_ts, pnl = _number(row.get("exit_ts")), _number(row.get("pnl_pct"))
        if exit_ts is None or exit_ts < entry or pnl is None or not math.isfinite(pnl * 100):
            raise ValueError("Invalid exit timestamp or net PnL")
        try:
            day = datetime.fromtimestamp(exit_ts, timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("Invalid UTC exit day") from exc
        row.update(entry_ts=entry, exit_ts=exit_ts, pnl_pct=pnl, exit_day_utc=day)
        row["learning_source"] = str(row.get("learning_source") or "UNATTRIBUTED")
        selected.append(row)
    return sorted(selected, key=lambda row: (row["exit_ts"], row["entry_ts"], str(row.get("trade_id", ""))))


def _percentile(ordered: Sequence[float], probability: float) -> float:
    index = (len(ordered) - 1) * probability
    lower, upper = math.floor(index), math.ceil(index)
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def day_block_bootstrap(rows: Sequence[dict]) -> dict:
    """Resample D whole UTC exit-day blocks D times, including every row.

    Means are trade-weighted within each resample (unequal day sizes retained).
    One observed day has a degenerate interval, explicitly marked as limited.
    """
    days: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        days[row["exit_day_utc"]].append(row["pnl_pct"] * 100)
    result = dict(status="OK" if days else NO_DATA, blocks=len(days),
                  seed=BOOTSTRAP_SEED, replicates=BOOTSTRAP_REPLICATES,
                  lower_bps=None, upper_bps=None, limited_blocks=len(days) < 2)
    if not days:
        return result
    blocks = [days[day] for day in sorted(days)]
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_REPLICATES):
        sample = [value for block in rng.choices(blocks, k=len(blocks)) for value in block]
        means.append(statistics.mean(sample))
    means.sort()
    result.update(lower_bps=_percentile(means, .025), upper_bps=_percentile(means, .975))
    return result


def day_block_difference(adaptive: Sequence[dict], control: Sequence[dict]) -> dict:
    """Resample the same UTC days for both arms; retain unequal trade counts.

    A replication missing either arm is undefined, never a zero difference.
    Report skipped replications explicitly; sparse overlap limits interpretation.
    """
    days = defaultdict(lambda: [[], []])
    for index, rows in enumerate((adaptive, control)):
        for row in rows:
            days[row["exit_day_utc"]][index].append(row["pnl_pct"] * 100)
    result = dict(status=NO_DATA, blocks=len(days), shared_blocks=sum(bool(a) and bool(c) for a, c in days.values()),
                  seed=BOOTSTRAP_SEED, replicates=BOOTSTRAP_REPLICATES, valid_replicates=0,
                  skipped_replicates=0, lower_bps=None, upper_bps=None, limited_blocks=len(days) < 2,
                  method="paired UTC exit-day blocks; missing-arm resamples excluded")
    if not adaptive or not control:
        return result
    blocks = [days[day] for day in sorted(days)]
    rng = random.Random(BOOTSTRAP_SEED)
    differences = []
    for _ in range(BOOTSTRAP_REPLICATES):
        selected = rng.choices(blocks, k=len(blocks))
        a, c = ([value for block in selected for value in block[index]] for index in (0, 1))
        if a and c:
            differences.append(statistics.mean(a) - statistics.mean(c))
    differences.sort()
    result.update(valid_replicates=len(differences), skipped_replicates=BOOTSTRAP_REPLICATES - len(differences),
                  limited_blocks=len(days) < 2 or len(differences) < BOOTSTRAP_REPLICATES)
    if differences:
        result.update(status="OK", lower_bps=_percentile(differences, .025), upper_bps=_percentile(differences, .975))
    return result


def _gross_move_bps(row: dict) -> float | None:
    # Realized entry/exit prices and direction; never infer gross from net + fees.
    entry, exit_price = _number(row.get("entry_price")), _number(row.get("exit_price"))
    side = str(row.get("side") or "").upper()
    if entry is None or exit_price is None or entry <= 0 or exit_price <= 0:
        return None
    if side not in {"BUY", "LONG", "SELL", "SHORT"}:
        return None
    direction = 1 if side in {"BUY", "LONG"} else -1
    return _number(direction * (exit_price / entry - 1) * 10000)


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    try:
        return _number(statistics.correlation(xs, ys))
    except (statistics.StatisticsError, ValueError, OverflowError, ZeroDivisionError):
        return None


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks for ties; no dependence on the realized target."""
    ordered = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
            end += 1
        for index in ordered[start:end]:
            result[index] = (start + 1 + end) / 2
        start = end
    return result


def _calibration(rows: Sequence[dict]) -> dict:
    pairs = []
    for row in rows:
        predicted, realized = _number(row.get("predicted_gross_move_bps")), _gross_move_bps(row)
        if predicted is not None and realized is not None:
            pairs.append((predicted, realized))
    net = [_number(row.get("predicted_net_edge_bps")) for row in rows]
    net = [value for value in net if value is not None]
    predicted, realized = [p for p, _ in pairs], [r for _, r in pairs]
    quintiles = []
    if len(pairs) >= 5:
        cuts = [_percentile(sorted(predicted), fraction) for fraction in (.2, .4, .6, .8)]
        for index in range(5):
            bucket = [(p, r) for p, r in pairs if sum(p > cut for cut in cuts) == index]
            quintiles.append(dict(quintile=index + 1, n=len(bucket),
                mean_predicted_bps=statistics.mean(p for p, _ in bucket) if bucket else None,
                mean_realized_bps=statistics.mean(r for _, r in bucket) if bucket else None))
    return dict(
        status="OK" if len(pairs) >= 5 else NO_DATA, n=len(pairs),
        missing_pairs=len(rows) - len(pairs),
        mean_predicted_gross_bps=statistics.mean(p for p, _ in pairs) if pairs else None,
        mean_realized_gross_bps=statistics.mean(r for _, r in pairs) if pairs else None,
        mean_error_bps=statistics.mean(p - r for p, r in pairs) if pairs else None,
        mean_absolute_error_bps=statistics.mean(abs(p - r) for p, r in pairs) if pairs else None,
        pearson=_correlation(predicted, realized) if len(pairs) >= 5 else None,
        spearman=_correlation(_ranks(predicted), _ranks(realized)) if len(pairs) >= 5 else None,
        quintiles=quintiles,
        diagnostic_note="At least 5 pairs for correlations/quintiles; legacy descriptive means retained below 5. Prediction ties remain together; empty quintiles are possible.",
        net_prediction_n=len(net),
        mean_predicted_net_bps=statistics.mean(net) if net else None,
        net_prediction_note="Legacy v1/closed profiles clip net at zero; paper_probe_v2 preserves signed net predictions.",
    )


def _excursions(rows: Sequence[dict]) -> dict:
    result = {}
    for field, sign in (("mfe_gross_bps", 1), ("mae_gross_bps", -1)):
        values = [_number(row.get(field)) for row in rows]
        values = [value for value in values if value is not None]
        result[field] = dict(status="OK" if values else NO_DATA, n=len(values), missing=len(rows) - len(values),
                             thresholds={str(x): dict(count=sum(sign * v >= x for v in values),
                                fraction=sum(sign * v >= x for v in values) / len(values) if values else None)
                                         for x in (10, 20, 30, 35)})
    return result


def _outcome(row: dict) -> str:
    label = str(row.get("outcome") or "").upper()
    return label if label in {"WIN", "LOSS", "FLAT"} else classify_outcome(row["pnl_pct"]).value


def summarize(rows: Sequence[dict]) -> dict:
    values = [row["pnl_pct"] * 100 for row in rows]
    outcomes = Counter()
    reasons: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        outcomes[_outcome(row)] += 1
        reasons[str(row.get("exit_reason") or "UNKNOWN").upper()].append(row)
    tp, sl = reasons.get("TP", []), reasons.get("SL", [])
    tp_extremes = [_number(row.get("mfe_gross_bps")) for row in tp]
    sl_extremes = [_number(row.get("mae_gross_bps")) for row in sl]
    tp_extremes = [value for value in tp_extremes if value is not None and value >= 0]
    sl_extremes = [abs(value) for value in sl_extremes if value is not None and value <= 0]
    tp_barrier = statistics.median(tp_extremes) if tp_extremes else None
    sl_barrier = statistics.median(sl_extremes) if sl_extremes else None
    tp_mean = statistics.mean(row["pnl_pct"] * 100 for row in tp) if tp else None
    sl_mean = statistics.mean(row["pnl_pct"] * 100 for row in sl) if sl else None
    driftless = (sl_barrier / (tp_barrier + sl_barrier)
                 if tp_barrier is not None and sl_barrier is not None and tp_barrier + sl_barrier > 0 else None)
    breakeven = (-sl_mean / (tp_mean - sl_mean)
                 if tp_mean is not None and sl_mean is not None and tp_mean > 0 > sl_mean else None)
    mean = statistics.mean(values) if values else None
    return dict(
        status="OK" if rows else NO_DATA, n=len(rows),
        outcomes={label: outcomes[label] for label in ("WIN", "LOSS", "FLAT")},
        exit_reasons={reason: dict(n=len(group), mean_net_bps=statistics.mean(r["pnl_pct"] * 100 for r in group),
                                  outcomes=dict(Counter(_outcome(r) for r in group)))
                      for reason, group in sorted(reasons.items())},
        mean_net_bps=mean, sample_sd_bps=statistics.stdev(values) if len(values) >= 2 else None,
        bootstrap_95=day_block_bootstrap(rows), evidence_budget=asdict(decide_evidence_budget(values)),
        barriers=dict(tp_share=len(tp) / (len(tp) + len(sl)) if tp or sl else None,
                      tp_n=len(tp), sl_n=len(sl), median_tp_mfe_bps=tp_barrier, median_sl_abs_mae_bps=sl_barrier,
                      tp_excursion_n=len(tp_extremes), sl_excursion_n=len(sl_extremes),
                      driftless_tp_share=driftless, realized_breakeven_tp_share=breakeven),
        excursions=_excursions(rows), calibration=_calibration(rows),
        cost_sensitivity=dict(status="APPROXIMATION" if rows else NO_DATA,
                              assumed_net_at_9_bps=mean, approximated_net_at_15_bps=mean - 6 if mean is not None else None),
    )


def build_report(rows: Sequence[dict], *, since: float | None = None) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    profiles: dict[str, list[dict]] = defaultdict(list)
    policies = defaultdict(lambda: defaultdict(list))
    versions = set()
    daily = defaultdict(list)
    daily_actions = defaultdict(lambda: defaultdict(list))
    tag_counts = Counter()
    for row in rows:
        grouped[row["learning_source"]].append(row)
        profiles[learning_profile(row["learning_source"])].append(row)
        policy = parse_policy_tag(row.get("tags_json"))
        tag_counts[policy["status"]] += 1
        policies[policy["policy_version"]][policy["policy_action"]].append(row)
        if policy["status"] == "OK":
            versions.add(policy["policy_version"])
        daily[row["exit_day_utc"]].append(row["pnl_pct"] * 100)
        daily_actions[row["exit_day_utc"]][policy["policy_action"]].append(row["pnl_pct"] * 100)
    experiments = {}
    for version in sorted(versions):
        adaptive, control = (policies[version].get(action, []) for action in ("ADAPTIVE", "CONTROL"))
        experiments[version] = dict(
            verdict=asdict(evaluate_selection_experiment([r["pnl_pct"] * 100 for r in adaptive],
                                                       [r["pnl_pct"] * 100 for r in control])),
            bootstrap_difference_95=day_block_difference(adaptive, control))
    policy_groups = {}
    for version, actions in sorted(policies.items()):
        policy_groups[version] = {}
        for action, group in sorted(actions.items()):
            probabilities = [parse_policy_tag(r.get("tags_json"))["policy_probability"] for r in group]
            probabilities = [p for p in probabilities if p is not None]
            policy_groups[version][action] = dict(**summarize(group),
                policy_probability=dict(n=len(probabilities), mean=statistics.mean(probabilities) if probabilities else None,
                                        min=min(probabilities) if probabilities else None, max=max(probabilities) if probabilities else None))
    return dict(
        schema_version=1, status="OK" if rows else NO_DATA, since_entry_ts=since,
        units="bps = pnl_pct * 100; excursions are explicit gross bps",
        notes=["Popis dodaných dat; bez doporučení a bez závěru o edge.",
               "Stop meze jsou orientační: obchody nejsou nezávislé.",
               "Bootstrap: celé UTC dny podle exit_ts, 2000 replikací, pevný seed; málo dnů a závislost mezi dny omezují výklad.",
               "Náklady 9→15 bps: aproximace net15 = net9 - 6, nikoli ověření aktuální sazby účtu.",
               "Bez --since jsou zahrnuty všechny dodané řádky, automatický výběr epochy se neprovádí.",
               "Chybějící predikce jsou NO_DATA; legacy net predikce jsou oříznuté nulou, paper_probe_v2 zachovává znaménko.",
               "Verdikt používá předem daná n>=30 pro rameno a n>=100 v obou ramenech pro efekt; žádné ladění na těchto datech.",
               "CONTROL je náhodný podíl kandidátů, nikoli paralelní portfolio; intervaly nejsou kauzální důkaz.",
               "Welchův standard error se zde násobí předepsaným z=1.96 (normální aproximace); ramena používají z=1.645.",
               "Kalibrace: při n<5 NO_DATA pro rozšířenou diagnostiku; staré popisné průměry zůstávají. Shodné predikce se v kvintilech nedělí."],
        total=summarize(rows), by_learning_source={source: summarize(group) for source, group in sorted(grouped.items())},
        by_profile={profile: summarize(group) for profile, group in sorted(profiles.items())},
        policy_tag_counts={key: tag_counts[key] for key in ("OK", "NO_POLICY", "INVALID_TAG")},
        by_policy=policy_groups, experiments=experiments,
        daily=[dict(day_utc=day, n=len(values), mean_net_bps=statistics.mean(values),
                    by_policy_action={action: dict(n=len(items), mean_net_bps=statistics.mean(items))
                                      for action, items in sorted(daily_actions[day].items())})
               for day, values in sorted(daily.items())],
    )


def _fmt(value: Any) -> str:
    return NO_DATA if value is None else f"{value:.6f}" if isinstance(value, float) else str(value)


def render_markdown(report: dict) -> str:
    lines = ["# P0.8+ — popis evidence epochy", "", *report["notes"], "", f"Stav: {report['status']}", ""]
    for label, group in [("Celkem", report["total"]), *report["by_learning_source"].items()]:
        ci, budget, barriers = group["bootstrap_95"], group["evidence_budget"], group["barriers"]
        lines += [f"## {label}", "", f"n={group['n']}; WIN/LOSS/FLAT=" + "/".join(str(v) for v in group["outcomes"].values()),
                  f"Čistý průměr {_fmt(group['mean_net_bps'])} bps; výběrová SD {_fmt(group['sample_sd_bps'])} bps.",
                  f"Denní bootstrap 95 %: [{_fmt(ci['lower_bps'])}, {_fmt(ci['upper_bps'])}] bps; UTC dnů={ci['blocks']}.",
                  f"Stop pravidlo: {budget['code']}; allowed={budget['allowed']}; dolní/horní mez "
                  f"{_fmt(budget['lower_bound_bps'])}/{_fmt(budget['upper_bound_bps'])} bps.", "",
                  "| Výstup | n | WIN/LOSS/FLAT | Průměr net bps |", "|---|---:|---|---:|"]
        for reason, stats in group["exit_reasons"].items():
            counts = "/".join(str(stats["outcomes"].get(key, 0)) for key in ("WIN", "LOSS", "FLAT"))
            lines.append(f"| {reason} | {stats['n']} | {counts} | {_fmt(stats['mean_net_bps'])} |")
        lines += ["", f"Podíl TP/(TP+SL): {_fmt(barriers['tp_share'])}; driftless reference: {_fmt(barriers['driftless_tp_share'])}; "
                  f"realizovaný break-even: {_fmt(barriers['realized_breakeven_tp_share'])}.",
                  f"Medián TP MFE={_fmt(barriers['median_tp_mfe_bps'])} bps (n={barriers['tp_excursion_n']}), "
                  f"SL |MAE|={_fmt(barriers['median_sl_abs_mae_bps'])} bps (n={barriers['sl_excursion_n']}).", "",
                  "| X bps | MFE ≥ X | MAE ≤ −X |", "|---:|---|---|"]
        for threshold in (10, 20, 30, 35):
            cells = []
            for field in ("mfe_gross_bps", "mae_gross_bps"):
                data = group["excursions"][field]
                stat = data["thresholds"][str(threshold)]
                cells.append(f"{stat['count']}/{data['n']} ({_fmt(stat['fraction'])})")
            lines.append(f"| {threshold} | {' | '.join(cells)} |")
        calibration, costs = group["calibration"], group["cost_sensitivity"]
        lines += ["", "Exkurzní podíly mají ve jmenovateli pouze platná měření; NULL není nula.",
                  f"Kalibrace hrubého pohybu: {calibration['status']}, n={calibration['n']}, chybí={calibration['missing_pairs']}; "
                  f"predikce {_fmt(calibration['mean_predicted_gross_bps'])}, realizace {_fmt(calibration['mean_realized_gross_bps'])}, "
                  f"bias (pred−real) {_fmt(calibration['mean_error_bps'])}, MAE {_fmt(calibration['mean_absolute_error_bps'])} bps.",
                  f"Pearson={_fmt(calibration['pearson'])}; Spearman={_fmt(calibration['spearman'])}.",
                  f"Uložená net predikce: n={calibration['net_prediction_n']}, průměr {_fmt(calibration['mean_predicted_net_bps'])} bps; "
                  "legacy profily oříznuté nulou, paper_probe_v2 se znaménkem.",
                  f"Aproximace nákladů: net při 9 bps {_fmt(costs['assumed_net_at_9_bps'])}; "
                  f"net při 15 bps {_fmt(costs['approximated_net_at_15_bps'])} bps.", ""]
        if calibration["quintiles"]:
            lines += ["| Kvintil predikce | n | Průměr predikce gross bps | Průměr realizace gross bps |",
                      "|---:|---:|---:|---:|"]
            for bucket in calibration["quintiles"]:
                lines.append(f"| {bucket['quintile']} | {bucket['n']} | {_fmt(bucket['mean_predicted_bps'])} | {_fmt(bucket['mean_realized_bps'])} |")
            lines.append("")
    lines += ["## Profily a přiřazení politiky", "", "| Profil | n | Průměr net bps | SD bps |",
              "|---|---:|---:|---:|"]
    for profile, group in report["by_profile"].items():
        lines.append(f"| {profile} | {group['n']} | {_fmt(group['mean_net_bps'])} | {_fmt(group['sample_sd_bps'])} |")
    lines += ["", "Policy tagy (počty obchodů): " + ", ".join(f"{k}={v}" for k, v in report["policy_tag_counts"].items()), "",
              "| Verze / akce | n | Průměr net bps | SD bps | Dolní / horní mez | Pravděpodobnost min / průměr / max |",
              "|---|---:|---:|---:|---|---|"]
    for version, actions in report["by_policy"].items():
        for action, group in actions.items():
            budget, probability = group["evidence_budget"], group["policy_probability"]
            lines.append(f"| {version} / {action} | {group['n']} | {_fmt(group['mean_net_bps'])} | {_fmt(group['sample_sd_bps'])} | "
                         f"{_fmt(budget['lower_bound_bps'])} / {_fmt(budget['upper_bound_bps'])} | "
                         + " / ".join(_fmt(probability[k]) for k in ("min", "mean", "max")) + " |")
    lines += ["", "## Předem stanovený verdikt experimentu", ""]
    if not report["experiments"]:
        lines += [NO_DATA, ""]
    for version, experiment in report["experiments"].items():
        verdict, bootstrap = experiment["verdict"], experiment["bootstrap_difference_95"]
        lines += [f"### {version}", "", ", ".join(verdict["codes"]),
                  f"ADAPTIVE n={verdict['adaptive']['n']}; CONTROL n={verdict['control']['n']}.",
                  f"Rozdíl ADAPTIVE−CONTROL: {_fmt(verdict['diff_bps'])} bps; Welch SE × 1,96 interval "
                  f"[{_fmt(verdict['diff_low_bps'])}, {_fmt(verdict['diff_high_bps'])}] bps.",
                  f"Denní blokový bootstrap rozdílu: {bootstrap['status']}, "
                  f"[{_fmt(bootstrap['lower_bps'])}, {_fmt(bootstrap['upper_bps'])}] bps; "
                  f"dnů={bootstrap['blocks']}, společných={bootstrap['shared_blocks']}, "
                  f"platných replikací={bootstrap['valid_replicates']}/{bootstrap['replicates']}, "
                  f"vynechaných={bootstrap['skipped_replicates']}, omezené bloky={bootstrap['limited_blocks']}.", ""]
    lines += ["## Časová řada podle UTC dne uzavření", "", "| Den UTC | Akce | n | Průměr net bps |", "|---|---|---:|---:|"]
    for day in report["daily"]:
        lines.append(f"| {day['day_utc']} | CELKEM | {day['n']} | {_fmt(day['mean_net_bps'])} |")
        for action, stats in day["by_policy_action"].items():
            lines.append(f"| {day['day_utc']} | {action} | {stats['n']} | {_fmt(stats['mean_net_bps'])} |")
    lines.append("")
    return "\n".join(lines)


def _write_report(path: Path, content: str) -> None:
    # Replace the directory entry, not its inode: an existing hardlink must not
    # modify an unrelated file outside --out. Temp files stay inside --out.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".report-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path)
    source.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--since", type=float)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        rows = load_rows(db=args.db, json_path=args.json_path, since=args.since)
        report = build_report(rows, since=args.since)
        encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
        markdown = render_markdown(report)
        directory = args.out.resolve()
        source_path = (args.db or args.json_path).resolve()
        outputs = [directory / name for name in ("report.json", "report.md")]
        for path in outputs:
            if path.is_symlink() or path.resolve() == source_path or (path.exists() and path.samefile(source_path)):
                raise ValueError("Output must not overwrite input or follow a file symlink")
        directory.mkdir(parents=True, exist_ok=True)
        for path, content in zip(outputs, (encoded + "\n", markdown)):
            _write_report(path, content)
    except (ValueError, OSError, sqlite3.Error, OverflowError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
