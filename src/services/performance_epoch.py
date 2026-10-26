"""Explicit reporting periods; starting one never deletes trades or learning."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

from src.core.trade_metrics_contract import classify_trade_outcome, compute_profit_factor


def epoch_path(cache_path: str) -> Path:
    return Path(cache_path).resolve().parent / "performance_epoch.json"


def load_epoch(cache_path: str) -> dict | None:
    path = epoch_path(cache_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Invalid performance epoch schema")
    started = float(data["started_at"])
    if not math.isfinite(started) or started <= 0 or not data.get("epoch_id"):
        raise ValueError("Invalid performance epoch")
    return data


def start_epoch(cache_path: str, *, release_id: str, started_at: float | None = None) -> dict:
    """Operator action, never called from an HTTP route or ordinary startup."""
    started = time.time() if started_at is None else float(started_at)
    if not math.isfinite(started) or started <= 0:
        raise ValueError("Invalid performance epoch timestamp")
    data = {"schema_version": 1, "epoch_id": uuid.uuid4().hex,
            "started_at": started, "release_id": release_id,
            "selection": "entry_ts_at_or_after_start", "historical_trades_preserved": True}
    path = epoch_path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Archive an earlier period descriptor, not its trades or learning state.
    previous = load_epoch(cache_path)
    if previous:
        archive = path.with_name("performance_epochs")
        archive.mkdir(exist_ok=True)
        safe_name = uuid.uuid4().hex + ".json"
        (archive / safe_name).write_text(json.dumps(previous, indent=2), encoding="utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".performance_epoch-", delete=False) as output:
            temporary = Path(output.name)
            json.dump(data, output, indent=2, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return data


def epoch_metrics(cache_path: str, epoch: dict) -> dict:
    """Read all closed positions OPENED in the period, with canonical outcomes.

    Existing positions keep their old attribution when they close after reset.
    USD P/L and normalized return PF are deliberately reported separately.
    """
    started = float(epoch["started_at"])
    if not math.isfinite(started) or started <= 0:
        raise ValueError("Invalid performance epoch timestamp")
    counts = {"WIN": 0, "LOSS": 0, "FLAT": 0}
    gains = losses = net_pct = net_usd = 0.0
    pct_gains = pct_losses = 0.0
    exits = {"tp": 0, "sl": 0, "scratch": 0, "stagnation": 0, "timeout": 0}
    day_start = time.time() // 86400 * 86400
    today = 0
    conn = sqlite3.connect(Path(cache_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        columns = {column[1] for column in conn.execute("PRAGMA table_info(closed_trades)")}
        outcome_column = "outcome" if "outcome" in columns else "NULL AS outcome"
        rows = conn.execute(
            f"SELECT pnl_usd,pnl_pct,{outcome_column},exit_reason,entry_ts,exit_ts FROM closed_trades "
            "WHERE entry_ts>=? ORDER BY exit_ts", (started,))
        for usd, pct, outcome, reason, entry_ts, exit_ts in rows:
            usd, pct = float(usd), float(pct)
            if not math.isfinite(usd) or not math.isfinite(pct):
                raise ValueError("Invalid period PnL")
            entry_ts, exit_ts = float(entry_ts), float(exit_ts)
            if (not math.isfinite(entry_ts) or not math.isfinite(exit_ts)
                    or entry_ts < started or exit_ts < entry_ts):
                raise ValueError("Invalid period trade timestamp")
            label = classify_trade_outcome({"outcome": outcome, "net_pnl_pct": pct}, usd)
            counts[label] += 1
            net_usd += usd
            net_pct += pct
            gains += max(usd, 0.0)
            losses += min(usd, 0.0)
            pct_gains += max(pct, 0.0)
            pct_losses += min(pct, 0.0)
            today += int(float(exit_ts) >= day_start)
            reason = str(reason or "").lower()
            key = "timeout" if "timeout" in reason else "scratch" if "scratch" in reason else "stagnation" if "stag" in reason else reason
            if key in exits:
                exits[key] += 1
    finally:
        conn.close()
    if not all(math.isfinite(value) for value in (gains, losses, net_pct, net_usd, pct_gains, pct_losses)):
        raise ValueError("Invalid period aggregate")
    n = sum(counts.values())
    wr = counts["WIN"] / n if n else 0.0
    # Wilson interval reports sampling uncertainty; zero observations prove nothing.
    z = 1.959963984540054
    lower = ((wr + z*z/(2*n) - z*math.sqrt(wr*(1-wr)/n + z*z/(4*n*n))) /
             (1 + z*z/n)) if n else 0.0
    return {**epoch, "n": n, "wins": counts["WIN"], "losses": counts["LOSS"],
            "flats": counts["FLAT"], "win_rate_pct": round(wr*100, 4),
            "wr_lower_95_pct": round(lower*100, 4), "net_pnl_usd": round(net_usd, 8),
            "net_pnl_pct": round(net_pct, 6),
            "profit_factor_usd_basis": compute_profit_factor([gains, losses]),
            "profit_factor_pct_basis": compute_profit_factor([pct_gains, pct_losses]),
            "closed_today": today, "exit_distribution": exits,
            "observed_goal_met": bool(n and wr > 0.5 and net_usd > 0),
            "statistical_wr_above_50": lower > 0.5}
