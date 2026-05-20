#!/usr/bin/env python3
"""
Export paper training dataset from CryptoMaster logs.

Parse [PAPER_TRAIN_QUALITY_ENTRY], [PAPER_TRAIN_QUALITY_EXIT], [PAPER_TRAIN_ECON_ATTRIB],
[LM_STATE_AFTER_UPDATE] logs and export as JSONL dataset for offline analysis.

Research-only: no trading logic changes, no Firebase writes.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional


def parse_kv_tokens(message: str) -> dict:
    """
    Parse key=value tokens from log message.

    Handles:
    - trade_id=paper_123
    - symbol=BTCUSDT
    - net_pnl_pct=-0.1800
    - touched_tp=False
    - training_bucket=C_WEAK_EV_TRAIN
    """
    result = {}
    # Match key=value patterns; values can be quoted or unquoted
    pattern = r'(\w+)=("[^"]*"|\'[^\']*\'|[^\s]+)'
    for match in re.finditer(pattern, message):
        key = match.group(1)
        value = match.group(2).strip('\'"')
        result[key] = value
    return result


def _safe_float(v: Optional[str], default: float = None) -> Optional[float]:
    """Convert to float safely."""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


def _safe_int(v: Optional[str], default: int = None) -> Optional[int]:
    """Convert to int safely."""
    if v is None:
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _safe_bool(v: Optional[str], default: bool = None) -> Optional[bool]:
    """Convert to bool safely."""
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() in ('true', '1', 'yes', 'on')


def parse_entry_log(line: str) -> Optional[dict]:
    """
    Parse [PAPER_TRAIN_QUALITY_ENTRY] log line.

    Expected format:
    [PAPER_TRAIN_QUALITY_ENTRY] trade_id=paper_x symbol=ETHUSDT side=BUY entry=2137.77 tp_pct=0.273 sl_pct=0.450 ...
    """
    if "[PAPER_TRAIN_QUALITY_ENTRY]" not in line:
        return None

    try:
        # Extract message part and timestamp prefix if available
        ts_raw = None
        if "]" not in line:
            return None
        prefix, message = line.split("]", 1)
        # Extract timestamp from prefix (e.g. "2026-05-19 10:00:00.500")
        parts = prefix.split()
        if len(parts) >= 2:
            ts_raw = " ".join(parts[0:2])

        message = message.strip()
        kv = parse_kv_tokens(message)

        return {
            "log_type": "PAPER_TRAIN_QUALITY_ENTRY",
            "entry_ts_raw": ts_raw,
            "trade_id": kv.get("trade_id"),
            "symbol": kv.get("symbol"),
            "side": kv.get("side"),
            "source": kv.get("source"),
            "bucket": kv.get("bucket"),
            "training_bucket": kv.get("training_bucket"),
            "entry_regime": kv.get("regime") or kv.get("entry_regime"),
            "entry": _safe_float(kv.get("entry")),
            "tp_pct": _safe_float(kv.get("tp_pct")),
            "sl_pct": _safe_float(kv.get("sl_pct")),
            "tp_pct_before": _safe_float(kv.get("tp_pct_before")),
            "sl_pct_before": _safe_float(kv.get("sl_pct_before")),
            "cost_edge_ok": _safe_bool(kv.get("cost_edge_ok")),
            "cost_edge_bypassed": _safe_bool(kv.get("cost_edge_bypassed")),
            "bypass_reason": kv.get("bypass_reason"),
            "geometry_calibrated": _safe_bool(kv.get("geometry_calibrated")),
        }
    except Exception:
        return None


def parse_exit_log(line: str) -> Optional[dict]:
    """
    Parse [PAPER_TRAIN_QUALITY_EXIT] log line.

    Expected format:
    [PAPER_TRAIN_QUALITY_EXIT] trade_id=paper_x exit=2143.62 outcome=WIN hold_s=52 ...
    """
    if "[PAPER_TRAIN_QUALITY_EXIT]" not in line:
        return None

    try:
        if "]" not in line:
            return None
        prefix, message = line.split("]", 1)
        # Extract timestamp from prefix if available
        ts_raw = None
        parts = prefix.split()
        if len(parts) >= 2:
            ts_raw = " ".join(parts[0:2])

        message = message.strip()
        kv = parse_kv_tokens(message)

        return {
            "log_type": "PAPER_TRAIN_QUALITY_EXIT",
            "exit_ts_raw": ts_raw,
            "trade_id": kv.get("trade_id"),
            "exit": _safe_float(kv.get("exit")),
            "exit_regime": kv.get("exit_regime") or kv.get("regime"),
            "outcome": kv.get("outcome"),
            "reason": kv.get("reason"),
            "attribution": kv.get("attribution"),
            "mfe_pct": _safe_float(kv.get("mfe_pct")),
            "mae_pct": _safe_float(kv.get("mae_pct")),
            "net_pnl_pct": _safe_float(kv.get("net_pnl_pct")),
            "gross_move_pct": _safe_float(kv.get("gross_move_pct")),
            "fee_drag_pct": _safe_float(kv.get("fee_drag_pct")),
            "touched_tp": _safe_bool(kv.get("touched_tp")),
            "touched_sl": _safe_bool(kv.get("touched_sl")),
            "near_tp": _safe_bool(kv.get("near_tp")),
            "near_sl": _safe_bool(kv.get("near_sl")),
            "timeout": _safe_bool(kv.get("timeout")),
            "hold_s": _safe_float(kv.get("hold_s")),
            "hold_limit_s": _safe_float(kv.get("hold_limit_s")),
        }
    except Exception:
        return None


def parse_attribution_log(line: str) -> Optional[dict]:
    """
    Parse [PAPER_TRAIN_ECON_ATTRIB] log line for detailed economic attribution.

    Expected format:
    [PAPER_TRAIN_ECON_ATTRIB] trade_id=paper_x ... attribution=NORMAL_WIN ...
    """
    if "[PAPER_TRAIN_ECON_ATTRIB]" not in line:
        return None

    try:
        if "]" not in line:
            return None
        prefix, message = line.split("]", 1)
        ts_raw = None
        parts = prefix.split()
        if len(parts) >= 2:
            ts_raw = " ".join(parts[0:2])

        message = message.strip()
        kv = parse_kv_tokens(message)

        return {
            "log_type": "PAPER_TRAIN_ECON_ATTRIB",
            "ts_raw": ts_raw,
            "trade_id": kv.get("trade_id"),
            "attribution": kv.get("attribution"),
            "reason": kv.get("reason"),
            "entry": _safe_float(kv.get("entry")),
            "exit": _safe_float(kv.get("exit")),
            "net_pnl_pct": _safe_float(kv.get("net_pnl_pct")),
            "gross_move_pct": _safe_float(kv.get("gross_move_pct")),
            "fee_drag_pct": _safe_float(kv.get("fee_drag_pct")),
            "mfe_pct": _safe_float(kv.get("mfe_pct")),
            "mae_pct": _safe_float(kv.get("mae_pct")),
            "tp_pct": _safe_float(kv.get("tp_pct")),
            "sl_pct": _safe_float(kv.get("sl_pct")),
            "touched_tp": _safe_bool(kv.get("touched_tp")),
            "touched_sl": _safe_bool(kv.get("touched_sl")),
            "near_tp": _safe_bool(kv.get("near_tp")),
            "near_sl": _safe_bool(kv.get("near_sl")),
            "hold_s": _safe_float(kv.get("hold_s")),
            "hold_limit_s": _safe_float(kv.get("hold_limit_s")),
            "timeout": _safe_bool(kv.get("timeout")),
            "cost_edge_ok": _safe_bool(kv.get("cost_edge_ok")),
            "cost_edge_bypassed": _safe_bool(kv.get("cost_edge_bypassed")),
            "bypass_reason": kv.get("bypass_reason"),
        }
    except Exception:
        return None


def parse_lm_state_log(line: str) -> Optional[dict]:
    """
    Parse [LM_STATE_AFTER_UPDATE] log line to extract trade counts.

    Expected format:
    [LM_STATE_AFTER_UPDATE] ... lm_total_trades=38 ...
    """
    if "[LM_STATE_AFTER_UPDATE]" not in line:
        return None

    try:
        if "]" not in line:
            return None
        message = line.split("]", 1)[1].strip()
        kv = parse_kv_tokens(message)

        return {
            "log_type": "LM_STATE_AFTER_UPDATE",
            "trade_id": kv.get("trade_id"),
            "lm_total_trades": _safe_int(kv.get("lm_total_trades")),
        }
    except Exception:
        return None


def join_trade_records(
    entries: dict,
    exits: dict,
    attrs: dict,
    lm_updates: dict,
) -> list[dict]:
    """
    Join entry, exit, attribution, and LM state records by trade_id.

    Args:
        entries: dict of {trade_id: entry_record}
        exits: dict of {trade_id: exit_record}
        attrs: dict of {trade_id: attr_record}
        lm_updates: dict of {trade_id: lm_record}

    Returns:
        list of merged trade records with canonical schema
    """
    all_trade_ids = set(entries.keys()) | set(exits.keys())
    records = []

    for trade_id in sorted(all_trade_ids):
        entry = entries.get(trade_id, {})
        exit_rec = exits.get(trade_id, {})
        attr = attrs.get(trade_id, {})
        lm = lm_updates.get(trade_id, {})

        # Attribution takes precedence over exit for certain fields
        attribution = attr.get("attribution") or exit_rec.get("attribution")
        reason = attr.get("reason") or exit_rec.get("reason")

        # Merge records into canonical schema
        merged = {
            "trade_id": trade_id,
            "symbol": entry.get("symbol") or exit_rec.get("symbol") or attr.get("symbol"),
            "side": entry.get("side") or exit_rec.get("side") or attr.get("side"),
            "source": entry.get("source") or exit_rec.get("source") or attr.get("source"),
            "bucket": entry.get("bucket"),
            "training_bucket": entry.get("training_bucket") or exit_rec.get("training_bucket") or attr.get("training_bucket"),
            "entry_regime": entry.get("entry_regime") or attr.get("entry_regime"),
            "exit_regime": exit_rec.get("exit_regime") or attr.get("exit_regime"),
            # Price/geometry
            "entry": entry.get("entry") or exit_rec.get("entry") or attr.get("entry"),
            "exit": exit_rec.get("exit") or attr.get("exit"),
            "tp_pct": entry.get("tp_pct") or attr.get("tp_pct"),
            "sl_pct": entry.get("sl_pct") or attr.get("sl_pct"),
            "tp_pct_before": entry.get("tp_pct_before") or attr.get("tp_pct_before"),
            "sl_pct_before": entry.get("sl_pct_before") or attr.get("sl_pct_before"),
            # Performance metrics
            "mfe_pct": exit_rec.get("mfe_pct") or attr.get("mfe_pct"),
            "mae_pct": exit_rec.get("mae_pct") or attr.get("mae_pct"),
            "net_pnl_pct": exit_rec.get("net_pnl_pct") or attr.get("net_pnl_pct"),
            "gross_move_pct": exit_rec.get("gross_move_pct") or attr.get("gross_move_pct"),
            "fee_drag_pct": exit_rec.get("fee_drag_pct") or attr.get("fee_drag_pct"),
            # Outcome & attribution
            "outcome": exit_rec.get("outcome") or attr.get("outcome"),
            "reason": reason,
            "attribution": attribution,
            # Timing & barrier events
            "hold_s": exit_rec.get("hold_s") or attr.get("hold_s"),
            "hold_limit_s": exit_rec.get("hold_limit_s") or attr.get("hold_limit_s"),
            "timeout": exit_rec.get("timeout") or attr.get("timeout"),
            "touched_tp": exit_rec.get("touched_tp") or attr.get("touched_tp"),
            "touched_sl": exit_rec.get("touched_sl") or attr.get("touched_sl"),
            "near_tp": exit_rec.get("near_tp") or attr.get("near_tp"),
            "near_sl": exit_rec.get("near_sl") or attr.get("near_sl"),
            # Cost & edges
            "cost_edge_ok": entry.get("cost_edge_ok") or attr.get("cost_edge_ok"),
            "cost_edge_bypassed": entry.get("cost_edge_bypassed") or attr.get("cost_edge_bypassed"),
            "bypass_reason": entry.get("bypass_reason") or attr.get("bypass_reason"),
            "geometry_calibrated": entry.get("geometry_calibrated"),
            # Timestamps
            "entry_ts_raw": entry.get("entry_ts_raw"),
            "exit_ts_raw": exit_rec.get("exit_ts_raw") or attr.get("ts_raw"),
        }
        records.append(merged)

    return records


def export_jsonl(records: list[dict], output_path: str) -> None:
    """Write records as JSONL."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def process_log_file(log_path: str) -> list[dict]:
    """
    Parse log file and return joined trade records.
    """
    entries = {}
    exits = {}
    attrs = {}
    lm_updates = {}

    with open(log_path, "r") as f:
        for line in f:
            # Try each parser
            entry = parse_entry_log(line)
            if entry:
                trade_id = entry.get("trade_id")
                if trade_id:
                    entries[trade_id] = entry
                continue

            exit_rec = parse_exit_log(line)
            if exit_rec:
                trade_id = exit_rec.get("trade_id")
                if trade_id:
                    exits[trade_id] = exit_rec
                continue

            attr = parse_attribution_log(line)
            if attr:
                trade_id = attr.get("trade_id")
                if trade_id:
                    attrs[trade_id] = attr
                continue

            lm = parse_lm_state_log(line)
            if lm:
                trade_id = lm.get("trade_id")
                if trade_id:
                    lm_updates[trade_id] = lm
                continue

    return join_trade_records(entries, exits, attrs, lm_updates)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Export paper training dataset from CryptoMaster logs"
    )
    parser.add_argument("log_file", help="Path to log file")
    parser.add_argument(
        "--output",
        default="data/research/paper_training_dataset.jsonl",
        help="Output JSONL path (default: data/research/paper_training_dataset.jsonl)"
    )

    args = parser.parse_args()

    if not Path(args.log_file).exists():
        print(f"Error: log file not found: {args.log_file}", file=sys.stderr)
        sys.exit(1)

    try:
        records = process_log_file(args.log_file)
        export_jsonl(records, args.output)
        print(f"Exported {len(records)} trades to {args.output}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
