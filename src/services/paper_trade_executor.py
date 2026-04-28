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


def _save_paper_state() -> None:
    """Save open paper positions to disk."""
    try:
        import json
        with _POSITION_LOCK:
            positions_snapshot = dict(_POSITIONS)
        os.makedirs("data", exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump(positions_snapshot, f, indent=2)
        log.info(
            "[PAPER_STATE_SAVE] open_positions=%d source=%s",
            len(positions_snapshot),
            _STATE_FILE,
        )
    except Exception as e:
        log.warning("[PAPER_STATE_SAVE_ERROR] err=%s", str(e))


def _load_paper_state() -> None:
    """Load open paper positions from disk at startup."""
    try:
        import json
        if not os.path.exists(_STATE_FILE):
            log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s reason=file_not_found", _STATE_FILE)
            return
        with open(_STATE_FILE, "r") as f:
            positions_data = json.load(f)
        with _POSITION_LOCK:
            _POSITIONS.update(positions_data)
        log.info(
            "[PAPER_STATE_LOAD] open_positions=%d source=%s",
            len(positions_data),
            _STATE_FILE,
        )
    except Exception as e:
        log.warning("[PAPER_STATE_LOAD_ERROR] err=%s", str(e))


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

    with _POSITION_LOCK:
        if len(_POSITIONS) >= _MAX_OPEN:
            log.error(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=max_open_exceeded open=%d",
                symbol,
                len(_POSITIONS),
            )
            return {"status": "blocked", "reason": "max_open_exceeded"}

        # Check exploration-specific exposure caps
        cap_check = _check_exploration_exposure_caps(symbol, bucket)
        if cap_check:
            log.error(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=%s %s",
                symbol,
                cap_check["reason"],
                cap_check["detail"],
            )
            return cap_check

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
        "original_decision": extra.get("original_decision") if extra else "TAKE",
        "reject_reason": extra.get("reject_reason") if extra else None,
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

        exit_reason = None
        if current_price >= pos["tp"]:
            exit_reason = "TP"
        elif current_price <= pos["sl"]:
            exit_reason = "SL"
        elif age_s >= pos["timeout_s"]:
            exit_reason = "TIMEOUT"

        if exit_reason:
            closed_trade = close_paper_position(trade_id, current_price, ts, exit_reason)
            if closed_trade:
                closed_trades.append(closed_trade)

    return closed_trades


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
        "[PAPER_EXIT] symbol=%s reason=%s entry=%.8f exit=%.8f net_pnl_pct=%.4f outcome=%s hold_s=%d max_hold_s=%d bucket=%s",
        pos["symbol"],
        reason,
        pos["entry_price"],
        price,
        pnl_data["net_pnl_pct"],
        pnl_data["outcome"],
        int(duration_s),
        int(pos.get("max_hold_s") or _MAX_AGE_S),
        pos.get("explore_bucket", "A_STRICT_TAKE"),
    )

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
