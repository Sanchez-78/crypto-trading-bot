"""Walk-forward replay of PAPER learner variants; offline, read-only.

Writes only replay.json/replay.md under --out. Never changes the live learner.
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
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
    if not all(math.isfinite(v) for v in (entry, exit_, net)) or exit_ < entry:
        return None
    side = {"LONG": "BUY", "SHORT": "SELL"}.get(str(row.get("side")).upper(), str(row.get("side")).upper())
    hour = datetime.fromtimestamp(entry, timezone.utc).hour
    features = {"source": str(row.get("learning_source") or row.get("source")), "symbol": str(row.get("symbol")),
                "regime": str(row.get("regime")), "side": side, "hour6": str(hour // 6),
                "pred_bucket": _pred_bucket(row.get("predicted_gross_move_bps"))}
    return Trade(str(row.get("trade_id") or row.get("id")), round(entry * 1000), round(exit_ * 1000), net, features)


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
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--db", type=Path)
    source.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--since", type=float)
    parser.add_argument("--prereg-after", type=float, help="unix seconds; score preregistered variants after it")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    trades = [t for t in (to_trade(r) for r in load(args.db, args.json_path, args.since)) if t]
    result = evaluate(trades, VARIANTS)
    if args.prereg_after is not None:
        result["preregistered"] = evaluate_preregistered(trades, scored_after_ms=round(args.prereg_after * 1000))
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in (("replay.json", json.dumps(result, indent=2, sort_keys=True)), ("replay.md", render(result))):
        tmp = args.out / (name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(args.out / name)
    pre = result.get("preregistered")
    print(f"{result['chosen_on_dev']} {result['verdict']}" + (f" prereg={pre['verdict']} fresh_n={pre['fresh_n']}" if pre else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
