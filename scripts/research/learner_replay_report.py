"""Walk-forward replay of PAPER learner variants; offline, read-only.

Writes replay.json/replay.md under --out and, once, the frozen --prereg-result together with
its provenance manifest (prereg_provenance.json). Never changes the live learner.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
from typing import Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.learner_replay import DEV_FRACTION, Trade, VARIANTS, evaluate, evaluate_preregistered


def _pred_bucket(value) -> str:
    if type(value) not in (int, float) or not math.isfinite(value):
        return "NA"
    return "lt2" if value < 2 else "lt6" if value < 6 else "ge6"


def to_trade(row: dict) -> Trade | None:
    try:
        entry, exit_, net = float(row["entry_ts"]), float(row["exit_ts"]), float(row["pnl_pct"]) * 100
    except (KeyError, TypeError, ValueError):
        return None
    # Non-positive durations are excluded here; the replay API itself fails closed on them.
    if not all(math.isfinite(v) for v in (entry, exit_, net)) or exit_ <= entry:
        return None
    side = {"LONG": "BUY", "SHORT": "SELL"}.get(str(row.get("side")).upper(), str(row.get("side")).upper())
    hour = datetime.fromtimestamp(entry, timezone.utc).hour
    features = {"source": str(row.get("learning_source") or row.get("source")), "symbol": str(row.get("symbol")),
                "regime": str(row.get("regime")), "side": side, "hour6": str(hour // 6),
                "pred_bucket": _pred_bucket(row.get("predicted_gross_move_bps"))}
    trade_id = row.get("trade_id") or row.get("id")
    if trade_id in (None, ""):
        return None
    return Trade(str(trade_id), round(entry * 1000), round(exit_ * 1000), net, features)


def load(db: Path | None, json_path: Path | None, since: float | None) -> list[dict]:
    if db is not None:
        connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            connection.execute("PRAGMA query_only=ON")
            connection.row_factory = sqlite3.Row
            rows = [dict(r) for r in connection.execute("SELECT * FROM closed_trades")]
        finally:
            connection.close()
    else:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        rows = payload["rows"] if isinstance(payload, dict) else payload
    return [r for r in rows if since is None or (r.get("entry_ts") or 0) >= since]


def render(result: dict) -> str:
    fmt = lambda v: "NA" if v is None else f"{v:+.2f}" if isinstance(v, float) else str(v)
    lines = ["# Replay variant učení (walk-forward)", "",
             f"n={result['n']}; vývoj {result['dev_n']} (prvních {int(DEV_FRACTION * 100)} %), holdout {result['holdout_n']}.",
             "Odhad každého obchodu používá jen obchody uzavřené před jeho vstupem. Lift = průměr net horní poloviny",
             "podle odhadu minus dolní poloviny. Varianta se vybírá jen na vývojové části a jednou testuje na holdoutu.",
             "Obchody nejsou nezávislé; interval je orientační.", "",
             f"**Vybráno na vývoji: {result['chosen_on_dev']} → {result['verdict']}**", "",
             "| Varianta | vývoj lift | vývoj ρ | holdout lift [95% CI] | holdout ρ |", "|---|---:|---:|---|---:|"]
    for name, item in result["variants"].items():
        d, h = item["dev"], item["holdout"]
        lines.append(f"| {name} | {fmt(d['lift_bps'])} | {fmt(d['spearman'])} | "
                     f"{fmt(h['lift_bps'])} [{fmt(h['lift_low_bps'])}; {fmt(h['lift_high_bps'])}] | {fmt(h['spearman'])} |")
    lines += ["", "Tento holdout je z historických dat (exploratorní), nikoli test předregistrované hypotézy."
              + (" Obsahuje jen obchody vstoupené do cutoffu předregistrace." if result.get("exploratory_until_ms") else "")]
    pre = result.get("preregistered")
    if pre:
        lines += ["", "## Předregistrovaná hypotéza C1 (jen čerstvá data, jediné pevné vyhodnocení)", "",
                  f"Cutoff {pre['scored_after_ms']} ms; čerstvých obchodů {pre['fresh_n']}/{pre['final_n']}, "
                  f"dnů {pre['days_elapsed']}/{pre['min_days']}: **{pre['verdict']}**"]
        if pre["variants"] is None:
            lines.append("Výsledky jsou do pevného konce skryté (amendment 1), aby opakované běhy nemohly nahlížet.")
        else:
            lines += ["", "| Varianta | lift [Welch 95% CI] | denní bootstrap 95% | ρ |", "|---|---|---|---:|"]
            for name, h in pre["variants"].items():
                b = h["day_bootstrap"]
                lines.append(f"| {name} | {fmt(h['lift_bps'])} [{fmt(h['lift_low_bps'])}; {fmt(h['lift_high_bps'])}] | "
                             f"[{fmt(b['lower_bps'])}; {fmt(b['upper_bps'])}] ({b['blocks']} dnů) | {fmt(h['spearman'])} |")
    return "\n".join(lines) + "\n"


# Provenance written at the moment of freezing (contract checked by
# scripts/research/cost_and_learning_review.py; keep these literals in sync).
PROVENANCE_CONTRACT = "c1_provenance_v1"
ID_HASH_CONVENTION = "sha256(utf8(json.dumps(ids, separators=(',', ':'))))"


def provenance_path(result_path: Path) -> Path:
    return result_path.with_name("prereg_provenance.json")


# One log token: no whitespace or control characters, so a run ID cannot forge a second
# PROVENANCE line (review 71, B2). run_eval.sh uses %Y%m%dT%H%M%SZ.
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")


def _fsync_dir(directory: Path) -> None:
    """Persist a rename/creation in the directory (POSIX); Windows cannot open directories."""
    if os.name == "nt":
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_frozen(path: Path, payload: bytes) -> None:
    """Content fsync before the atomic rename, directory fsync after it (review 71, B3)."""
    tmp = path.with_name(path.name + ".tmp")
    # Never write through an existing name: a stale .tmp may be a hardlink to another file
    # (e.g. the provenance log) and "wb" would truncate that inode (review 73). Unlink the
    # name, then create a fresh inode exclusively.
    tmp.unlink(missing_ok=True)
    with open(tmp, "xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    path.chmod(0o444)
    _fsync_dir(path.parent)


def _append_reference(log: Path, run_id: str, manifest_sha: str, result_sha: str) -> None:
    """Append the trusted reference and force it to disk (audit 70, A1)."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    created = not log.exists()
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"{stamp} PROVENANCE run={run_id} manifest_sha256={manifest_sha} result_sha256={result_sha}\n")
        handle.flush()
        os.fsync(handle.fileno())
    if created:
        _fsync_dir(log.parent)


def validate_freeze_inputs(path: Path, run_id: str | None, provenance_log: Path | None) -> None:
    """Fail closed before any write (audit 70 A2, review 71 B1/B2)."""
    if not run_id or provenance_log is None:
        raise ValueError("freezing requires run_id and provenance_log")
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must be one log token [A-Za-z0-9._:-], max 64 chars")
    # resolve() follows symlinks and makes relative paths absolute; the targets need not exist.
    log = provenance_log.resolve()
    protected = {p.resolve() for base in (path, provenance_path(path))
                 for p in (base, base.with_name(base.name + ".tmp"))}
    if log in protected:
        raise ValueError("provenance_log must not alias the result, the manifest or their temp files")
    # Different resolved paths can still be one inode (hardlink, review 73): compare the
    # identity of every existing pair. Only a missing file is a non-match; any other
    # error while checking identity fails closed.
    for target in protected:
        try:
            same = os.path.samefile(log, target)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError("cannot verify that provenance_log is a distinct file") from exc
        if same:
            raise ValueError("provenance_log must not alias the result, the manifest or their temp files")


def frozen_preregistered(trades: list[Trade], cutoff_ms: int, path: Path | None,
                         run_id: str | None = None,
                         provenance_log: Path | None = None) -> tuple[dict, str | None]:
    """Return (result, provenance manifest sha256 if frozen by THIS call, else None).

    Freezing requires run_id and provenance_log (fail closed, audit 70 A2).
    """
    if path is not None and path.exists():
        frozen = json.loads(path.read_text(encoding="utf-8"))
        if frozen.get("scored_after_ms") != cutoff_ms:
            raise ValueError("prereg_result_cutoff_mismatch")
        return frozen, None
    now_ms = round(time.time() * 1000)
    result = evaluate_preregistered(trades, scored_after_ms=cutoff_ms, now_ms=now_ms)
    # Only conclusive verdicts are frozen; INSUFFICIENT_DATA stays recomputable.
    if path is not None and result["verdict"] in {"CONTRARIAN_CONFIRMED", "CONTRARIAN_REFUTED", "CONTRARIAN_NOT_SHOWN"}:
        validate_freeze_inputs(path, run_id, provenance_log)
        payload = json.dumps(result, indent=2, sort_keys=True).encode("utf-8")
        result_sha = hashlib.sha256(payload).hexdigest()
        manifest = json.dumps({
            "contract": PROVENANCE_CONTRACT, "hypothesis": "C1_contrarian", "scored_after_ms": cutoff_ms,
            "run_id": run_id, "evaluated_at_ms": now_ms,
            "result_sha256": result_sha, "id_hash_convention": ID_HASH_CONVENTION,
        }, indent=2, sort_keys=True).encode("utf-8")
        manifest_sha = hashlib.sha256(manifest).hexdigest()
        # Order: manifest -> reference in the append-only log (fsync) -> result. The result
        # file is the freeze marker, so whenever it exists its reference is already logged.
        # A crash before the marker leaves an orphan manifest/log line; the next
        # (re-)evaluation writes a new manifest and a new line with its own run ID.
        _write_frozen(provenance_path(path), manifest)
        _append_reference(provenance_log, run_id, manifest_sha, result_sha)
        _write_frozen(path, payload)
        return result, manifest_sha
    return result, None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path)
    source.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--since", type=float)
    parser.add_argument("--prereg-after", type=float, help="unix seconds; score preregistered variants after it")
    parser.add_argument("--prereg-result", type=Path,
                        help="immutable file: written on the first non-PENDING result, returned unchanged afterwards")
    parser.add_argument("--run-id", help="evaluation run ID recorded in the provenance manifest at freeze")
    parser.add_argument("--provenance-log", type=Path,
                        help="append-only log (verdict.log) receiving the PROVENANCE reference at freeze")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.prereg_result is not None:
        try:  # same checks as the library, before any evaluation or write
            validate_freeze_inputs(args.prereg_result, args.run_id, args.provenance_log)
        except ValueError as exc:
            parser.error(f"--prereg-result: {exc}")
    trades = [t for t in (to_trade(r) for r in load(args.db, args.json_path, args.since)) if t]
    provenance_sha = None
    if args.prereg_after is None:
        result = evaluate(trades, VARIANTS)
    else:
        cutoff_ms = round(args.prereg_after * 1000)
        # Blinding: exploratory variants see only pre-cutoff trades (C1 = -V2 on any shared set).
        result = evaluate([t for t in trades if t.entry_ms <= cutoff_ms], VARIANTS)
        result["exploratory_until_ms"] = cutoff_ms
        result["preregistered"], provenance_sha = frozen_preregistered(trades, cutoff_ms, args.prereg_result,
                                                                       args.run_id, args.provenance_log)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in (("replay.json", json.dumps(result, indent=2, sort_keys=True)), ("replay.md", render(result))):
        tmp = args.out / (name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(args.out / name)
    pre = result.get("preregistered")
    print(f"{result['chosen_on_dev']} {result['verdict']}"
          + (f" prereg={pre['verdict']} fresh_n={pre['fresh_n']}/{pre['final_n']} days={pre['days_elapsed']}/{pre['min_days']}"
             if pre else "")
          # Informational echo; the trusted reference is the PROVENANCE line written at freeze.
          + (f" provenance_sha256={provenance_sha}" if provenance_sha else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
