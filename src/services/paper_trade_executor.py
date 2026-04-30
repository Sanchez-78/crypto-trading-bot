"""V10.13u+20: Paper trade executor using real live prices for learning."""
import os
import logging
import time
import uuid
from typing import Optional, Dict, List

log = logging.getLogger(__name__)

# Configuration from environment
_INITIAL_EQUITY = float(os.getenv("PAPER_INITIAL_EQUITY_USD", "10000"))
_POSITION_SIZE = float(os.getenv("PAPER_POSITION_SIZE_USD", "100"))
_FEE_PCT = float(os.getenv("PAPER_FEE_PCT", "0.0015"))  # 0.15% round-trip
_SLIPPAGE_PCT = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.0003"))  # 0.03%
_MAX_OPEN = int(os.getenv("PAPER_MAX_OPEN_POSITIONS", "3"))
_MAX_AGE_S = float(os.getenv("PAPER_MAX_POSITION_AGE_S", "900"))  # 15 min default

# State
_POSITIONS = {}  # position_id -> position_dict
_POSITION_LOCK = __import__("threading").RLock()
_STATE_FILE = "data/paper_open_positions.json"

# P1.1Q Phase 5: Deduplication — track closed trades in current session to prevent double updates
_CLOSED_TRADES_THIS_SESSION = set()  # trade_id -> (learned, metrics_updated)
_CLOSED_TRADES_LOCK = __import__("threading").RLock()


def _save_paper_state() -> None:
    """Save open paper positions to disk with atomic writes."""
    try:
        import json
        with _POSITION_LOCK:
            positions_snapshot = dict(_POSITIONS)

        # Ensure directory exists
        data_dir = os.path.dirname(_STATE_FILE) or "data"
        os.makedirs(data_dir, exist_ok=True)

        # Atomic write: write to temp file, then replace
        tmp_file = _STATE_FILE + ".tmp"
        try:
            with open(tmp_file, "w") as f:
                json.dump(positions_snapshot, f, indent=2, sort_keys=True)
            os.replace(tmp_file, _STATE_FILE)
        except FileNotFoundError:
            # Fallback for race condition: direct write
            with open(_STATE_FILE, "w") as f:
                json.dump(positions_snapshot, f, indent=2, sort_keys=True)

        log.info(
            "[PAPER_STATE_SAVE] open_positions=%d source=%s",
            len(positions_snapshot),
            _STATE_FILE,
        )
    except PermissionError as e:
        log.error(
            "[PAPER_STATE_SAVE_ERROR] permission path=%s uid=%s euid=%s err=%s",
            _STATE_FILE,
            os.getuid() if hasattr(os, "getuid") else "N/A",
            os.geteuid() if hasattr(os, "geteuid") else "N/A",
            str(e),
        )
    except Exception as e:
        log.warning("[PAPER_STATE_SAVE_ERROR] err=%s", str(e))


def _migrate_legacy_position(pos: dict) -> dict:
    """Migrate legacy position missing max_hold_s.

    Args:
        pos: Position dict that may be missing max_hold_s

    Returns:
        Updated position dict with max_hold_s set
    """
    if "max_hold_s" in pos:
        return pos  # Already has max_hold_s

    # Infer from bucket if available
    bucket = pos.get("explore_bucket", "A_STRICT_TAKE")
    if bucket == "B_RECOVERY_READY":
        pos["max_hold_s"] = 900
    elif bucket == "C_WEAK_EV":
        pos["max_hold_s"] = 600
    elif bucket == "D_NEG_EV_CONTROL":
        pos["max_hold_s"] = 300
    elif bucket == "E_NO_PATTERN":
        pos["max_hold_s"] = 300
    else:
        # Default safe value for unknown/A_STRICT_TAKE
        pos["max_hold_s"] = _MAX_AGE_S

    return pos


def _convert_list_to_dict(positions_list: list) -> dict:
    """Convert legacy list format to canonical dict format.

    Args:
        positions_list: List of position dicts from old format

    Returns:
        Dict mapping trade_id -> position dict
    """
    result = {}
    for idx, pos in enumerate(positions_list):
        # Try to find existing trade_id/id field
        trade_id = pos.get("trade_id") or pos.get("id")

        if trade_id:
            result[trade_id] = pos
        else:
            # Generate stable fallback key
            symbol = pos.get("symbol", "UNKNOWN")
            opened_at_ts = pos.get("entry_ts", pos.get("opened_at_ts", time.time()))
            fallback_id = f"legacy_{idx}_{symbol}_{int(opened_at_ts)}"
            result[fallback_id] = pos

    return result


def _load_paper_state() -> None:
    """Load open paper positions from disk at startup.

    Supports both canonical dict and legacy list formats.
    Automatically converts and saves back in canonical format.
    """
    try:
        import json
        if not os.path.exists(_STATE_FILE):
            log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s missing=true", _STATE_FILE)
            return

        with open(_STATE_FILE, "r") as f:
            positions_data = json.load(f)

        # Handle empty state
        if not positions_data:
            log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s", _STATE_FILE)
            return

        # Convert list to dict if needed
        list_to_dict_count = 0
        if isinstance(positions_data, list):
            if len(positions_data) == 0:
                # Empty list - just log and return
                log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s", _STATE_FILE)
                return

            # Convert list to dict
            positions_data = _convert_list_to_dict(positions_data)
            list_to_dict_count = len(positions_data)
            log.info(
                "[PAPER_STATE_MIGRATE] from=list to=dict count=%d",
                list_to_dict_count,
            )

        # Migrate legacy positions (ensure max_hold_s is set)
        migrated_count = 0
        for trade_id, pos in positions_data.items():
            if "max_hold_s" not in pos:
                positions_data[trade_id] = _migrate_legacy_position(pos)
                migrated_count += 1

        with _POSITION_LOCK:
            _POSITIONS.update(positions_data)

        log.info(
            "[PAPER_STATE_LOAD] open_positions=%d source=%s",
            len(positions_data),
            _STATE_FILE,
        )
        if migrated_count > 0:
            log.info(
                "[PAPER_STATE_MIGRATE] count=%d reason=missing_max_hold_s",
                migrated_count,
            )

        # If we did a list->dict conversion, save back in canonical format
        if list_to_dict_count > 0:
            _save_paper_state()

    except json.JSONDecodeError as e:
        log.warning("[PAPER_STATE_LOAD_ERROR] source=%s err=json_decode err_detail=%s", _STATE_FILE, str(e))
    except Exception as e:
        log.warning("[PAPER_STATE_LOAD_ERROR] source=%s err=%s", _STATE_FILE, str(e))


# Load paper positions from disk on module init
_load_paper_state()


def _normalize_side(side_raw: str) -> tuple[str, str]:
    """Normalize side aliases to canonical form.

    Args:
        side_raw: Raw side (BUY, LONG, SELL, SHORT, etc.)

    Returns:
        (canonical_side, side_raw) tuple where canonical_side is BUY or SELL
    """
    side_upper = str(side_raw).upper().strip() if side_raw else "BUY"
    if side_upper in ("BUY", "LONG"):
        return "BUY", side_raw
    elif side_upper in ("SELL", "SHORT"):
        return "SELL", side_raw
    else:
        # Default to BUY for unknown, log warning
        log.warning(f"[SIDE_NORMALIZATION_DEFAULT] raw={side_raw} defaulting to BUY")
        return "BUY", side_raw


def _generate_trade_id() -> str:
    """Generate unique trade ID."""
    return f"paper_{uuid.uuid4().hex[:12]}"


def _calculate_pnl(
    side: str,
    entry_price: float,
    exit_price: float,
    size_usd: float,
    fee_pct: float = None,
    slippage_pct: float = None,
) -> dict:
    """Calculate PnL for a paper trade.

    Args:
        side: "BUY" or "SELL"
        entry_price: Entry price
        exit_price: Exit price
        size_usd: Position size in USD
        fee_pct: Fee percentage (default from config)
        slippage_pct: Slippage percentage (default from config)

    Returns:
        dict with gross_pnl_pct, fee_pct, slippage_pct, net_pnl_pct, outcome
    """
    if fee_pct is None:
        fee_pct = _FEE_PCT
    if slippage_pct is None:
        slippage_pct = _SLIPPAGE_PCT

    # Directional return
    if side == "BUY":
        gross_return = (exit_price - entry_price) / entry_price
    else:  # SELL
        gross_return = (entry_price - exit_price) / entry_price

    gross_pnl_pct = gross_return * 100

    # Costs (as percentage of entry)
    fee_cost_pct = fee_pct * 100  # Round-trip
    slippage_cost_pct = slippage_pct * 100

    # Net PnL
    net_pnl_pct = gross_pnl_pct - fee_cost_pct - slippage_cost_pct

    # Outcome based on net PnL (not exit reason)
    if net_pnl_pct > 0.05:  # 0.05% profit threshold
        outcome = "WIN"
    elif net_pnl_pct < -0.05:  # -0.05% loss threshold
        outcome = "LOSS"
    else:
        outcome = "FLAT"

    return {
        "gross_pnl_pct": round(gross_pnl_pct, 4),
        "fee_pct": round(fee_cost_pct, 4),
        "slippage_pct": round(slippage_cost_pct, 4),
        "net_pnl_pct": round(net_pnl_pct, 4),
        "outcome": outcome,
    }


def _check_exploration_exposure_caps(symbol: str, bucket: Optional[str]) -> Optional[dict]:
    """Check exploration-specific exposure caps.

    Rules:
    - max_open_per_symbol = 1
    - max_open_per_bucket = 2
    - max_open_per_symbol_bucket = 1

    Returns:
        None if caps OK, else {"status": "blocked", "reason": ..., "detail": ...}
    """
    if not bucket:
        return None  # Not an exploration trade, skip caps

    symbol_count = sum(1 for p in _POSITIONS.values() if p["symbol"] == symbol and p.get("explore_bucket"))
    bucket_count = sum(1 for p in _POSITIONS.values() if p.get("explore_bucket") == bucket)
    symbol_bucket_count = sum(
        1 for p in _POSITIONS.values()
        if p["symbol"] == symbol and p.get("explore_bucket") == bucket
    )

    # Check symbol cap
    if symbol_count >= 1:
        return {
            "status": "blocked",
            "reason": "max_open_per_symbol",
            "detail": f"symbol={symbol} open_symbol={symbol_count} bucket={bucket}",
        }

    # Check bucket cap
    if bucket_count >= 2:
        return {
            "status": "blocked",
            "reason": "max_open_per_bucket",
            "detail": f"bucket={bucket} open_bucket={bucket_count} symbol={symbol}",
        }

    # Check symbol-bucket cap
    if symbol_bucket_count >= 1:
        return {
            "status": "blocked",
            "reason": "max_open_per_symbol_bucket",
            "detail": f"symbol={symbol} bucket={bucket} open_symbol_bucket={symbol_bucket_count}",
        }

    return None


def _check_training_sampler_caps(symbol: str, bucket: Optional[str]) -> Optional[dict]:
    """Check training sampler-specific exposure caps (P1.1N secondary layer).

    Rules:
    - max_open_per_symbol = 1 (PAPER_TRAIN_MAX_OPEN_PER_SYMBOL)
    - max_open_per_bucket = 2 (PAPER_TRAIN_MAX_OPEN_PER_BUCKET)

    Returns:
        None if caps OK, else {"status": "blocked", "reason": ..., "detail": ...}
    """
    if not bucket:
        return None  # Not a training sampler trade, skip caps

    try:
        from src.core.runtime_mode import PAPER_TRAIN_MAX_OPEN_PER_SYMBOL, PAPER_TRAIN_MAX_OPEN_PER_BUCKET
    except Exception:
        return None

    symbol_count = sum(
        1 for p in _POSITIONS.values()
        if p["symbol"] == symbol and p.get("paper_source") == "training_sampler"
    )
    bucket_count = sum(
        1 for p in _POSITIONS.values()
        if p.get("training_bucket") == bucket and p.get("paper_source") == "training_sampler"
    )

    # Check symbol cap
    if symbol_count >= PAPER_TRAIN_MAX_OPEN_PER_SYMBOL:
        log.info(
            "[PAPER_ENTRY_BLOCKED] reason=training_sampler_max_open_per_symbol "
            "symbol=%s open_symbol=%d bucket=%s",
            symbol,
            symbol_count,
            bucket,
        )
        return {
            "status": "blocked",
            "reason": "training_sampler_max_open_per_symbol",
            "detail": f"symbol={symbol} open_symbol={symbol_count} bucket={bucket}",
        }

    # Check bucket cap
    if bucket_count >= PAPER_TRAIN_MAX_OPEN_PER_BUCKET:
        log.info(
            "[PAPER_ENTRY_BLOCKED] reason=training_sampler_max_open_per_bucket "
            "bucket=%s open_bucket=%d symbol=%s",
            bucket,
            bucket_count,
            symbol,
        )
        return {
            "status": "blocked",
            "reason": "training_sampler_max_open_per_bucket",
            "detail": f"bucket={bucket} open_bucket={bucket_count} symbol={symbol}",
        }

    return None


def open_paper_position(
    signal: dict,
    price: float,
    ts: float,
    reason: str = "RDE_TAKE",
    extra: Optional[dict] = None,
) -> dict:
    """Open a paper trading position using real live price.

    Args:
        signal: Signal dict with ev, score, p, coh, af, symbol, side, etc.
        price: Current real market price (MUST be real, not synthetic)
        ts: Timestamp of entry
        reason: Entry reason (default "RDE_TAKE")
        extra: Optional dict with paper_source, explore_bucket, etc.

    Returns:
        dict: {"trade_id": ..., "status": "opened", "symbol": ..., ...}
    """
    if not price or price <= 0:
        log.error("[PAPER_ENTRY_BLOCKED] symbol=%s reason=invalid_price", signal.get("symbol"))
        return {"status": "blocked", "reason": "invalid_price"}

    symbol = signal.get("symbol", "UNKNOWN")
    bucket = extra.get("explore_bucket") if extra else None
    training_bucket = extra.get("training_bucket") if extra else None
    paper_source = extra.get("paper_source") if extra else None

    with _POSITION_LOCK:
        # Check exploration-specific exposure caps FIRST (before total max cap)
        cap_check = _check_exploration_exposure_caps(symbol, bucket)
        if cap_check:
            log.error(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=%s %s",
                symbol,
                cap_check["reason"],
                cap_check["detail"],
            )
            return cap_check

        # Check training sampler-specific caps (P1.1N secondary layer)
        if paper_source == "training_sampler":
            training_cap_check = _check_training_sampler_caps(symbol, training_bucket)
            if training_cap_check:
                log.error(
                    "[PAPER_ENTRY_BLOCKED] symbol=%s reason=%s %s",
                    symbol,
                    training_cap_check["reason"],
                    training_cap_check["detail"],
                )
                return training_cap_check

        # Then check total paper position cap
        if len(_POSITIONS) >= _MAX_OPEN:
            log.error(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=max_open_exceeded open=%d bucket=%s",
                symbol,
                len(_POSITIONS),
                bucket or training_bucket or "N/A",
            )
            return {"status": "blocked", "reason": "max_open_exceeded"}

    trade_id = _generate_trade_id()
    side_raw = signal.get("action", signal.get("side", "BUY"))
    side, side_raw_stored = _normalize_side(side_raw)

    # Apply exploration sizing if provided; otherwise use default position size
    size_usd = _POSITION_SIZE
    if extra and "final_size_usd" in extra:
        size_usd = extra["final_size_usd"]

    position = {
        "trade_id": trade_id,
        "mode": "paper_live",
        "symbol": symbol,
        "side": side,
        "side_raw": side_raw_stored,
        "entry_price": price,
        "entry_ts": ts,
        "size_usd": size_usd,
        "tp": price * 1.012,  # 1.2% TP placeholder
        "sl": price * 0.988,  # 1.2% SL placeholder
        "timeout_s": _MAX_AGE_S,
        "regime": signal.get("regime", "NEUTRAL"),
        "features": signal.get("features", {}),
        "ev_at_entry": signal.get("ev", 0.0),
        "score_at_entry": signal.get("score", 0.0),
        "p_at_entry": signal.get("p", signal.get("confidence", 0.5)),
        "coh_at_entry": signal.get("coh", signal.get("coherence", 1.0)),
        "af_at_entry": signal.get("af", signal.get("auditor_factor", 1.0)),
        "rde_decision": reason,
        "paper_source": extra.get("paper_source") if extra else "normal_rde_take",
        "explore_bucket": extra.get("explore_bucket") if extra else "A_STRICT_TAKE",
        "training_bucket": (extra.get("training_bucket") or extra.get("explore_bucket", "A_STRICT_TAKE")) if extra else "A_STRICT_TAKE",  # P1.1M: preserve training bucket
        "explore_sub_bucket": extra.get("explore_sub_bucket") if extra else "",  # P1.1i
        "original_decision": extra.get("original_decision") if extra else "TAKE",
        "reject_reason": extra.get("reject_reason") if extra else None,
        "side_inferred": extra.get("side_inferred") if extra else False,  # P1.1M
        "cost_edge_ok": extra.get("cost_edge_ok") if extra else True,  # P1.1M
        "expected_move_pct": extra.get("expected_move_pct") if extra else 0.0,  # P1.1M
        "required_move_pct": extra.get("required_move_pct") if extra else 0.23,  # P1.1M
        "size_mult": extra.get("size_mult") if extra else 1.0,
        "max_hold_s": extra.get("max_hold_s") if extra else _MAX_AGE_S,
        "tags": extra.get("tags") if extra else [],
        "created_at": ts,
    }

    with _POSITION_LOCK:
        _POSITIONS[trade_id] = position

    log.warning(
        "[PAPER_ENTRY] symbol=%s side=%s price=%.8f size_usd=%.2f ev=%.4f score=%.3f reason=%s",
        symbol,
        side,
        price,
        size_usd,
        position["ev_at_entry"],
        position["score_at_entry"],
        reason,
    )

    # Persist state after opening position
    _save_paper_state()

    return {
        "status": "opened",
        "trade_id": trade_id,
        "symbol": symbol,
        "entry_price": price,
    }


def update_paper_positions(
    symbol_prices: Dict[str, float],
    ts: float,
) -> List[dict]:
    """Update all open paper positions with current prices and check exits.

    Args:
        symbol_prices: {symbol: current_price, ...}
        ts: Current timestamp

    Returns:
        list of closed trade dicts
    """
    closed_trades = []

    with _POSITION_LOCK:
        positions_to_check = list(_POSITIONS.items())

    for trade_id, pos in positions_to_check:
        symbol = pos["symbol"]
        current_price = symbol_prices.get(symbol)

        if not current_price or current_price <= 0:
            continue  # No valid price, skip

        # Check exit conditions
        entry_price = pos["entry_price"]
        age_s = ts - pos["entry_ts"]

        # Use per-position max_hold_s (for exploration) or default timeout_s
        max_hold = pos.get("max_hold_s", pos.get("timeout_s", _MAX_AGE_S))

        exit_reason = None
        if current_price >= pos["tp"]:
            exit_reason = "TP"
        elif current_price <= pos["sl"]:
            exit_reason = "SL"
        elif age_s >= max_hold:
            exit_reason = "TIMEOUT"

        if exit_reason:
            closed_trade = close_paper_position(trade_id, current_price, ts, exit_reason)
            if closed_trade:
                closed_trades.append(closed_trade)

    return closed_trades


def _canonical_closed_paper_trade(raw: dict) -> dict:
    """P1.1Q Phase 2: Convert any closed paper trade to canonical form.

    Guarantees all fields are safe types:
    - symbol: str
    - regime: str
    - side: "BUY"|"SELL"|"UNKNOWN"
    - bucket: str (training_bucket or explore_bucket, prefer training)
    - training_bucket/explore_bucket: both filled consistently
    - sub_bucket: str|None (never iterable where unexpected)
    - tags: list[str]
    - features: dict
    - score/ws: float
    - net_pnl_pct: float
    - pnl_decimal: net_pnl_pct / 100.0
    - outcome: WIN|LOSS|FLAT|UNKNOWN
    - exit_reason: str
    """
    # Core identity fields
    symbol = str(raw.get("symbol") or "UNKNOWN")
    regime = str(raw.get("regime") or raw.get("regime_at_entry") or "UNKNOWN")

    # Side (BUY/SELL/UNKNOWN)
    side_raw = raw.get("side") or raw.get("action") or "UNKNOWN"
    if isinstance(side_raw, str):
        side = side_raw.upper() if side_raw.upper() in ("BUY", "SELL") else "UNKNOWN"
    else:
        side = "UNKNOWN"

    # Buckets - prefer training_bucket, fallback to explore_bucket
    training_bucket = str(raw.get("training_bucket") or "").strip() or None
    explore_bucket = str(raw.get("explore_bucket") or "").strip() or None
    bucket = training_bucket or explore_bucket or "UNKNOWN"

    # Ensure both are set for consistency
    if not training_bucket:
        training_bucket = bucket if bucket != "UNKNOWN" else "UNKNOWN"
    if not explore_bucket:
        explore_bucket = bucket if bucket != "UNKNOWN" else "UNKNOWN"

    # Sub-bucket (must be str or None, never iterable)
    sub_bucket = raw.get("training_sub_bucket") or raw.get("explore_sub_bucket")
    if sub_bucket and not isinstance(sub_bucket, str):
        sub_bucket = str(sub_bucket) if sub_bucket else None

    # Tags - always a list of strings
    tags = raw.get("tags")
    if tags is None:
        tags = []
    elif isinstance(tags, str):
        tags = [tags]
    elif isinstance(tags, (list, tuple, set)):
        tags = [str(t) for t in tags if t]
    else:
        try:
            tags = [str(t) for t in tags if t]
        except Exception:
            tags = []

    # Features - always a dict
    features = raw.get("features")
    if not isinstance(features, dict):
        features = {}

    # Scores/win-score
    score = float(raw.get("score_at_entry") or raw.get("score") or raw.get("ws") or 0.0)
    ws = score  # alias

    # PnL fields
    net_pnl_pct = float(raw.get("net_pnl_pct") or 0.0)
    pnl_decimal = net_pnl_pct / 100.0

    # Outcome
    outcome = str(raw.get("outcome") or "UNKNOWN")
    if outcome not in ("WIN", "LOSS", "FLAT"):
        outcome = "UNKNOWN"

    # Exit reason
    exit_reason = str(raw.get("exit_reason") or raw.get("reason") or "UNKNOWN")

    return {
        "symbol": symbol,
        "regime": regime,
        "side": side,
        "bucket": bucket,
        "training_bucket": training_bucket,
        "explore_bucket": explore_bucket,
        "sub_bucket": sub_bucket,
        "tags": tags,
        "features": features,
        "score": score,
        "ws": ws,
        "net_pnl_pct": net_pnl_pct,
        "pnl_decimal": pnl_decimal,
        "outcome": outcome,
        "exit_reason": exit_reason,
    }


def _safe_learning_update_for_paper_trade(pos: dict, pnl_data: dict) -> bool:
    """P1.1V: Convert closed paper trade to learning update. Decouple learning from telemetry. Never raises.

    Args:
        pos: Position dict (closed trade with metadata)
        pnl_data: PnL breakdown dict with net_pnl_pct, outcome

    Returns:
        True if learning succeeded, False if skipped or errored
    """
    # Merge and canonicalize
    try:
        merged = {**pos, **pnl_data}
        canon = _canonical_closed_paper_trade(merged)

        # Skip if symbol missing
        if not canon["symbol"] or canon["symbol"] == "UNKNOWN":
            log.debug("[LEARNING_UPDATE_SKIP] reason=no_symbol bucket=%s", canon["bucket"])
            return False
    except Exception as e:
        log.exception("[LEARNING_UPDATE_ERROR] canonicalization failed: %s", e)
        return False

    # P1.1V: Separate learning update from telemetry (telemetry errors don't mask learning result)
    ok = False
    try:
        from src.services.learning_monitor import update_from_paper_trade
        ok = bool(update_from_paper_trade(canon))
        log.info(
            "[LEARNING_UPDATE] ok=%s source=paper_closed_trade symbol=%s regime=%s bucket=%s outcome=%s net_pnl_pct=%.4f",
            ok,
            canon["symbol"],
            canon["regime"],
            canon["bucket"],
            canon["outcome"],
            canon["net_pnl_pct"],
        )
    except Exception as e:
        log.exception(
            "[LEARNING_UPDATE_ERROR] err=%r symbol=%s bucket=%s fn=update_from_paper_trade",
            e,
            canon.get("symbol"),
            canon.get("bucket"),
        )
        return False

    # P1.1V: Telemetry in separate try/except so learning success isn't masked by telemetry errors
    try:
        from src.services.paper_training_sampler import (
            record_training_closed,
            record_training_learning_update,
        )
        record_training_closed(bucket=canon["bucket"], outcome=canon["outcome"])
        if ok:
            record_training_learning_update()
    except Exception as e:
        log.warning(
            "[PAPER_TRAIN_METRICS_ERROR] err=%r symbol=%s bucket=%s",
            e,
            canon.get("symbol"),
            canon.get("bucket"),
        )

    return ok


def _primary_bucket_for_closed_trade(t: dict) -> str:
    """P1.1T: Determine exact primary bucket — never ambiguous, never fallback to A_STRICT_TAKE."""
    return str(
        t.get("training_bucket")
        or t.get("explore_bucket")
        or t.get("bucket")
        or "UNKNOWN"
    )


def _safe_bucket_metrics_update_for_paper_trade(raw_trade: dict) -> bool:
    """P1.1T: Isolated bucket metrics update. ONLY called once per closed trade. Never A_STRICT_TAKE fallback.

    Args:
        raw_trade: Raw closed trade dict

    Returns:
        True if update succeeded, False if error (never raises)
    """
    try:
        # Normalize to canonical form
        t = _canonical_closed_paper_trade(raw_trade)

        # P1.1T: Determine primary bucket exactly once, no ambiguity
        primary = _primary_bucket_for_closed_trade(t)

        # Prepare metrics dict with primary bucket only
        # No parent bucket, no fallback bucket, no A_STRICT_TAKE unless primary IS A_STRICT_TAKE
        metrics_dict = {
            "explore_bucket": primary,
            "explore_sub_bucket": str(t.get("sub_bucket") or "N/A"),
            "outcome": t.get("outcome") or "UNKNOWN",
            "net_pnl_pct": _safe_float(t.get("net_pnl_pct"), 0.0),
            "exit_reason": t.get("exit_reason") or "UNKNOWN",
        }

        # Call metrics update once (bucket_metrics will log the update)
        from src.services.bucket_metrics import update_bucket_metrics
        update_bucket_metrics(metrics_dict)

        return True

    except Exception as e:
        bucket = raw_trade.get("training_bucket") or raw_trade.get("explore_bucket") or "UNKNOWN"
        log.exception(
            "[BUCKET_METRICS_ERROR] err=%s bucket=%s symbol=%s fn=_safe_bucket_metrics_update_for_paper_trade",
            str(e),
            bucket,
            raw_trade.get("symbol", "UNKNOWN"),
        )
        return False


def _safe_float(v, default=0.0):
    """P1.1T: Type-safe float conversion."""
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def close_paper_position(
    position_id: str,
    price: float,
    ts: float,
    reason: str,
) -> Optional[dict]:
    """Close a paper position and produce closed trade dict.

    Args:
        position_id: Trade ID to close
        price: Exit price (MUST be real)
        ts: Exit timestamp
        reason: Exit reason (TP, SL, TIMEOUT, MANUAL, etc.)

    Returns:
        dict: Closed trade with all canonical fields, or None if not found
    """
    if not price or price <= 0:
        log.error("[PAPER_EXIT_BLOCKED] trade_id=%s reason=invalid_price", position_id)
        return None

    with _POSITION_LOCK:
        if position_id not in _POSITIONS:
            return None
        pos = _POSITIONS.pop(position_id)

    # Calculate PnL
    pnl_data = _calculate_pnl(
        side=pos["side"],
        entry_price=pos["entry_price"],
        exit_price=price,
        size_usd=pos["size_usd"],
    )

    duration_s = ts - pos["entry_ts"]

    closed_trade = {
        **pos,
        "exit_price": price,
        "exit_ts": ts,
        "exit_reason": reason,
        "duration_s": duration_s,
        "gross_pnl_pct": pnl_data["gross_pnl_pct"],
        "fee_pct": pnl_data["fee_pct"],
        "slippage_pct": pnl_data["slippage_pct"],
        "net_pnl_pct": pnl_data["net_pnl_pct"],
        "outcome": pnl_data["outcome"],
        "unit_pnl": (pnl_data["net_pnl_pct"] / 100.0) * pos["size_usd"],
        "weighted_pnl": (pnl_data["net_pnl_pct"] / 100.0) * pos["size_usd"],
    }

    log.warning(
        "[PAPER_EXIT] symbol=%s reason=%s entry=%.8f exit=%.8f net_pnl_pct=%.4f outcome=%s hold_s=%d max_hold_s=%d bucket=%s training_bucket=%s",
        pos["symbol"],
        reason,
        pos["entry_price"],
        price,
        pnl_data["net_pnl_pct"],
        pnl_data["outcome"],
        int(duration_s),
        int(pos.get("max_hold_s") or _MAX_AGE_S),
        pos.get("explore_bucket", "A_STRICT_TAKE"),
        pos.get("training_bucket", ""),
    )

    # P1.1Q Phase 5: Deduplication — ensure we only update learning/metrics once per trade_id
    with _CLOSED_TRADES_LOCK:
        if position_id in _CLOSED_TRADES_THIS_SESSION:
            log.debug(f"[PAPER_CLOSE_DEDUPE] trade_id={position_id} already processed, skipping learning/metrics updates")
            return closed_trade
        _CLOSED_TRADES_THIS_SESSION.add(position_id)

    # P1.1L Phase 6: Call learning update for training trades
    # P1.1Q: Use safe adapter with canonical normalization
    if pos.get("paper_source") == "training_sampler":
        _safe_learning_update_for_paper_trade(pos, pnl_data)

    # P1.1Q: Update bucket metrics with safe adapter
    _safe_bucket_metrics_update_for_paper_trade(closed_trade)

    # Persist state after closing position
    _save_paper_state()

    return closed_trade


def get_paper_open_positions() -> list[dict]:
    """Get all open paper positions.

    Returns:
        list of position dicts
    """
    with _POSITION_LOCK:
        return [dict(pos) for pos in _POSITIONS.values()]


def get_paper_trade_by_id(trade_id: str) -> Optional[dict]:
    """Get specific open paper position.

    Args:
        trade_id: Trade ID to retrieve

    Returns:
        position dict or None
    """
    with _POSITION_LOCK:
        if trade_id in _POSITIONS:
            return dict(_POSITIONS[trade_id])
    return None


def reset_paper_positions():
    """Reset all open positions (for testing)."""
    with _POSITION_LOCK:
        _POSITIONS.clear()
