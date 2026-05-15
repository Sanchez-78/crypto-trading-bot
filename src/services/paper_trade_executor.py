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

# P1.1Y: Throttle PAPER_ENTRY_BLOCKED spam (max once per symbol/bucket/reason per 60s)
_PAPER_ENTRY_BLOCKED_THROTTLE = {}  # (symbol, bucket, reason) -> last_log_ts
_PAPER_ENTRY_BLOCKED_TTL = 60.0  # seconds between logs per key

# P1.1AA: Throttle PAPER_TIMEOUT_SCAN logs (max once per 60s)
_PAPER_TIMEOUT_SCAN_THROTTLE = 0.0  # last scan log timestamp
_PAPER_TIMEOUT_SCAN_TTL = 60.0  # seconds between scan logs

# P1.1AG: Paper training quality summary aggregator
_PAPER_CLOSED_TRADES_BUFFER = []  # List of closed trades for summary aggregation
_PAPER_CLOSED_TRADES_LOCK = __import__("threading").RLock()
_PAPER_SUMMARY_LAST_LOG = 0.0  # Last summary log timestamp
_PAPER_SUMMARY_INTERVAL = 300.0  # 5 minutes between summary logs

# P1.1AH: Track which trades had quality entry logs for mismatch detection
_QUALITY_ENTRY_LOGGED = set()  # trade_id -> bool for trades with quality_entry logs
_QUALITY_ENTRY_LOCK = __import__("threading").RLock()

# P1.1AJ: Track which trades had quality exit logs for idempotent logging
_QUALITY_EXIT_LOGGED = set()  # trade_ids with quality exit logged
_QUALITY_EXIT_LOCK = __import__("threading").RLock()


def _is_training_position(pos: dict) -> bool:
    """Check if position is a paper training position using broader gate.

    Matches the is_training check at line ~208-211.
    """
    return (
        pos.get("training_bucket") == "C_WEAK_EV_TRAIN"
        or pos.get("paper_source") == "training_sampler"
    )


def _log_quality_exit_once(closed_trade: dict, position: dict, path: str = "unknown") -> None:
    """Idempotent wrapper for quality exit logging.

    Ensures each trade_id has at most one quality exit log, regardless of path.
    """
    trade_id = closed_trade.get("trade_id")
    if not trade_id:
        return

    with _QUALITY_EXIT_LOCK:
        if trade_id in _QUALITY_EXIT_LOGGED:
            return  # Already logged

        if _is_training_position(position):
            _log_paper_train_quality_exit(closed_trade, position)
            _QUALITY_EXIT_LOGGED.add(trade_id)


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


def _safe_float(value, default=0.0) -> float:
    """P1.1Z: Safely convert value to float with fallback."""
    try:
        if value is None:
            return float(default)
        return float(value)
    except (ValueError, TypeError):
        return float(default)


def _safe_int(value, default=0) -> int:
    """P1.1Z: Safely convert value to int with fallback."""
    try:
        if value is None:
            return int(default)
        return int(float(value))
    except (ValueError, TypeError):
        return int(default)


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

        # P1.1Z: Normalize training positions to fix legacy timeout values
        normalized_count = 0
        for trade_id, pos in positions_data.items():
            training_bucket = pos.get("training_bucket")
            paper_source = pos.get("paper_source")
            is_training = (
                training_bucket == "C_WEAK_EV_TRAIN"
                or paper_source == "training_sampler"
            )

            if is_training:
                # Ensure training bucket is set
                if not training_bucket:
                    pos["training_bucket"] = "C_WEAK_EV_TRAIN"

                # Normalize timeout to effective hold time (max 300s for training)
                max_hold = _safe_float(pos.get("max_hold_s"), 300.0)
                timeout = _safe_float(pos.get("timeout_s"), max_hold)
                effective_timeout = min(max_hold or 300.0, timeout or 300.0, 300.0)

                if timeout != effective_timeout:
                    pos["timeout_s"] = effective_timeout
                    normalized_count += 1

                # Ensure entry_ts and created_at are consistent
                entry_ts = pos.get("entry_ts") or pos.get("created_at")
                if entry_ts:
                    if "entry_ts" not in pos:
                        pos["entry_ts"] = entry_ts
                    if "created_at" not in pos:
                        pos["created_at"] = entry_ts

                if normalized_count > 0 or (timeout != effective_timeout):
                    log.info(
                        "[PAPER_POSITION_NORMALIZED] trade_id=%s symbol=%s training_bucket=C_WEAK_EV_TRAIN "
                        "timeout_s=%.0f max_hold_s=%.0f",
                        trade_id,
                        pos.get("symbol", "UNKNOWN"),
                        effective_timeout,
                        max_hold,
                    )
                    positions_data[trade_id] = pos

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

        # P1.1Z: Reconcile stale positions (non-fatal — separate error handling)
        try:
            reconcile_result = _reconcile_stale_paper_positions()
            alive_count = len(_POSITIONS)
            log.info(
                "[PAPER_STATE_RECONCILE_SUMMARY] loaded=%d normalized=%d stale_closed=%d stale_pending=%d alive=%d",
                len(positions_data),
                normalized_count,
                reconcile_result.get("closed", 0),
                reconcile_result.get("pending", 0),
                alive_count,
            )
        except Exception as e:
            log.exception("[PAPER_STATE_RECONCILE_ERROR] source=%s err=%s", _STATE_FILE, str(e))

        # If we did a list->dict conversion, save back in canonical format
        if list_to_dict_count > 0:
            _save_paper_state()

    except json.JSONDecodeError as e:
        log.warning("[PAPER_STATE_LOAD_ERROR] source=%s err=json_decode err_detail=%s", _STATE_FILE, str(e))
    except Exception as e:
        log.warning("[PAPER_STATE_LOAD_ERROR] source=%s err=%s", _STATE_FILE, str(e))


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


def _effective_paper_hold_s(pos: dict) -> float:
    """P1.1Z: Calculate effective hold time for training positions.

    Training positions (C_WEAK_EV_TRAIN) must not stay open longer than max_hold_s (300s).
    Non-training positions use their configured timeout.

    Args:
        pos: Position dict with training_bucket, max_hold_s, timeout_s, etc.

    Returns:
        Effective hold time in seconds
    """
    if not isinstance(pos, dict):
        return 300.0

    bucket = str(pos.get("training_bucket") or pos.get("bucket") or pos.get("explore_bucket") or "")
    source = str(pos.get("paper_source") or pos.get("mode") or "")

    is_training = (
        bucket == "C_WEAK_EV_TRAIN"
        or source == "training_sampler"
    )

    max_hold = _safe_float(pos.get("max_hold_s"), 300.0)
    timeout = _safe_float(pos.get("timeout_s"), max_hold)

    if is_training:
        # Training positions: effective hold is min of max_hold and timeout, capped at 300s
        return max(30.0, min(max_hold or 300.0, timeout or 300.0, 300.0))

    # Non-training: use configured timeout or max_hold
    return max(30.0, timeout or max_hold or 300.0)


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


def _reconcile_stale_paper_positions(now: Optional[float] = None, price_by_symbol: Optional[dict] = None) -> dict:
    """P1.1Z: Close stale training positions that exceed effective hold time.

    Args:
        now: Current timestamp (default: time.time())
        price_by_symbol: Dict of current prices by symbol

    Returns:
        dict with counts: {"closed": N, "pending": N, "alive": N}
    """
    if now is None:
        now = time.time()
    if price_by_symbol is None:
        price_by_symbol = {}

    closed_count = 0
    pending_count = 0
    positions_to_close = []

    with _POSITION_LOCK:
        for trade_id, pos in list(_POSITIONS.items()):
            entry_ts = _safe_float(pos.get("entry_ts") or pos.get("created_at"), 0.0)
            if entry_ts <= 0:
                continue

            age_s = now - entry_ts
            effective_hold = _effective_paper_hold_s(pos)

            if age_s >= effective_hold:
                positions_to_close.append((trade_id, pos, age_s, effective_hold))

    # Close positions outside lock to avoid deadlock
    for trade_id, pos, age_s, effective_hold in positions_to_close:
        try:
            symbol = pos.get("symbol", "UNKNOWN")
            exit_price = price_by_symbol.get(symbol) or pos.get("last_price") or pos.get("entry_price", 0.0)

            close_paper_position(
                position_id=trade_id,
                price=exit_price,
                ts=now,
                reason="TIMEOUT",
            )

            log.info(
                "[PAPER_STALE_RECONCILE] trade_id=%s symbol=%s age_s=%.1f effective_hold_s=%.1f action=closed reason=TIMEOUT",
                trade_id,
                symbol,
                age_s,
                effective_hold,
            )
            closed_count += 1
        except Exception as e:
            log.warning(f"[PAPER_STALE_RECONCILE_ERROR] trade_id={trade_id} err={e}")
            pending_count += 1

    with _POSITION_LOCK:
        alive_count = len(_POSITIONS)

    return {
        "closed": closed_count,
        "pending": pending_count,
        "alive": alive_count,
    }


def _is_position_stale(pos: dict, now: Optional[float] = None) -> bool:
    """P1.1Z: Check if a position has exceeded its effective hold time."""
    if now is None:
        now = time.time()

    entry_ts = _safe_float(pos.get("entry_ts") or pos.get("created_at"), 0.0)
    if entry_ts <= 0:
        return False

    age_s = now - entry_ts
    effective_hold = _effective_paper_hold_s(pos)
    return age_s >= effective_hold


def _check_exploration_exposure_caps(symbol: str, bucket: Optional[str]) -> Optional[dict]:
    """Check exploration-specific exposure caps.

    Rules:
    - max_open_per_symbol = 1
    - max_open_per_bucket = 2
    - max_open_per_symbol_bucket = 1

    P1.1Z: Ignore stale positions in cap counts.

    Returns:
        None if caps OK, else {"status": "blocked", "reason": ..., "detail": ...}
    """
    if not bucket:
        return None  # Not an exploration trade, skip caps

    now = time.time()
    symbol_count = sum(
        1 for p in _POSITIONS.values()
        if p["symbol"] == symbol and p.get("explore_bucket") and not _is_position_stale(p, now)
    )
    bucket_count = sum(
        1 for p in _POSITIONS.values()
        if p.get("explore_bucket") == bucket and not _is_position_stale(p, now)
    )
    symbol_bucket_count = sum(
        1 for p in _POSITIONS.values()
        if p["symbol"] == symbol and p.get("explore_bucket") == bucket and not _is_position_stale(p, now)
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

    P1.1Z: Ignore stale positions in cap counts.

    Returns:
        None if caps OK, else {"status": "blocked", "reason": ..., "detail": ...}
    """
    if not bucket:
        return None  # Not a training sampler trade, skip caps

    try:
        from src.core.runtime_mode import PAPER_TRAIN_MAX_OPEN_PER_SYMBOL, PAPER_TRAIN_MAX_OPEN_PER_BUCKET
    except Exception:
        return None

    now = time.time()
    symbol_count = sum(
        1 for p in _POSITIONS.values()
        if p["symbol"] == symbol and p.get("paper_source") == "training_sampler" and not _is_position_stale(p, now)
    )
    bucket_count = sum(
        1 for p in _POSITIONS.values()
        if p.get("training_bucket") == bucket and p.get("paper_source") == "training_sampler" and not _is_position_stale(p, now)
    )

    # Check symbol cap
    if symbol_count >= PAPER_TRAIN_MAX_OPEN_PER_SYMBOL:
        # P1.1Y: Throttle spam
        throttle_key = (symbol, bucket, "training_sampler_max_open_per_symbol")
        now_ts = time.time()
        last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
        if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
            log.info(
                "[PAPER_ENTRY_BLOCKED] reason=training_sampler_max_open_per_symbol "
                "symbol=%s open_symbol=%d bucket=%s",
                symbol,
                symbol_count,
                bucket,
            )
            _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
        return {
            "status": "blocked",
            "reason": "training_sampler_max_open_per_symbol",
            "detail": f"symbol={symbol} open_symbol={symbol_count} bucket={bucket}",
        }

    # Check bucket cap
    if bucket_count >= PAPER_TRAIN_MAX_OPEN_PER_BUCKET:
        # P1.1Y: Throttle spam
        throttle_key = (symbol, bucket, "training_sampler_max_open_per_bucket")
        now_ts = time.time()
        last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
        if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
            log.info(
                "[PAPER_ENTRY_BLOCKED] reason=training_sampler_max_open_per_bucket "
                "bucket=%s open_bucket=%d symbol=%s",
                bucket,
                bucket_count,
                symbol,
            )
            _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
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
        # P1.1Y: Throttle spam
        symbol = signal.get("symbol", "UNKNOWN")
        throttle_key = (symbol, "N/A", "invalid_price")
        now_ts = time.time()
        last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
        if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
            log.error("[PAPER_ENTRY_BLOCKED] symbol=%s reason=invalid_price", symbol)
            _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
        return {"status": "blocked", "reason": "invalid_price"}

    symbol = signal.get("symbol", "UNKNOWN")
    # P1.1AF: Ensure bucket field is set (primary is training_bucket, fallback to explore_bucket)
    training_bucket = extra.get("training_bucket") if extra else None
    explore_bucket = extra.get("explore_bucket") if extra else None
    bucket = training_bucket or explore_bucket  # Primary: training_bucket, fallback: explore_bucket
    paper_source = extra.get("paper_source") if extra else None

    with _POSITION_LOCK:
        # Check exploration-specific exposure caps FIRST (before total max cap)
        cap_check = _check_exploration_exposure_caps(symbol, bucket)
        if cap_check:
            # P1.1Y: Throttle spam
            throttle_key = (symbol, bucket or "N/A", cap_check["reason"])
            now_ts = time.time()
            last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
            if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
                log.error(
                    "[PAPER_ENTRY_BLOCKED] symbol=%s reason=%s %s",
                    symbol,
                    cap_check["reason"],
                    cap_check["detail"],
                )
                _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
            return cap_check

        # Check training sampler-specific caps (P1.1N secondary layer)
        if paper_source == "training_sampler":
            training_cap_check = _check_training_sampler_caps(symbol, training_bucket)
            if training_cap_check:
                # P1.1Y: Throttle spam
                throttle_key = (symbol, training_bucket or "N/A", training_cap_check["reason"])
                now_ts = time.time()
                last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
                if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
                    log.error(
                        "[PAPER_ENTRY_BLOCKED] symbol=%s reason=%s %s",
                        symbol,
                        training_cap_check["reason"],
                        training_cap_check["detail"],
                    )
                    _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
                return training_cap_check

        # Then check total paper position cap (P1.1Z: exclude stale positions)
        now = time.time()
        alive_positions = [p for p in _POSITIONS.values() if not _is_position_stale(p, now)]
        if len(alive_positions) >= _MAX_OPEN:
            # P1.1Y: Throttle PAPER_ENTRY_BLOCKED spam (max once per symbol/bucket/reason per 60s)
            bucket_name = bucket or training_bucket or "N/A"
            throttle_key = (symbol, bucket_name, "max_open_exceeded")
            last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
            if now - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
                log.error(
                    "[PAPER_ENTRY_BLOCKED] symbol=%s reason=max_open_exceeded open=%d bucket=%s",
                    symbol,
                    len(alive_positions),
                    bucket_name,
                )
                _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now
            return {"status": "blocked", "reason": "max_open_exceeded"}

    trade_id = _generate_trade_id()
    side_raw = signal.get("action", signal.get("side", "BUY"))
    side, side_raw_stored = _normalize_side(side_raw)

    # Apply exploration sizing if provided; otherwise use default position size
    size_usd = _POSITION_SIZE
    if extra and "final_size_usd" in extra:
        size_usd = extra["final_size_usd"]

    # P1.1AI: Use side-aware TP/SL for paper training
    tp_sl = normalize_paper_tp_sl(side, price, price * 1.012, price * 0.988)
    if tp_sl is None:
        log.error(
            "[PAPER_ENTRY_BLOCKED] symbol=%s reason=tp_sl_impossible side=%s entry=%.8f",
            symbol,
            side,
            price,
        )
        return {"status": "blocked", "reason": "tp_sl_impossible"}

    if tp_sl.get("repaired"):
        log.warning(
            "[PAPER_TRAIN_TP_SL_REPAIRED] trade_id=%s symbol=%s side=%s old_tp=%.8f old_sl=%.8f new_tp=%.8f new_sl=%.8f reason=%s",
            trade_id,
            symbol,
            side,
            price * 1.012,
            price * 0.988,
            tp_sl["tp"],
            tp_sl["sl"],
            tp_sl["repair_reason"],
        )

    position = {
        "trade_id": trade_id,
        "mode": "paper_live",
        "symbol": symbol,
        "side": side,
        "side_raw": side_raw_stored,
        "entry_price": price,
        "entry_ts": ts,
        "size_usd": size_usd,
        "tp": tp_sl["tp"],
        "sl": tp_sl["sl"],
        "tp_pct_at_entry": tp_sl["tp_pct"],  # Store for diagnostics
        "sl_pct_at_entry": tp_sl["sl_pct"],
        "rr_at_entry": tp_sl["rr"],
        "timeout_s": _MAX_AGE_S,
        "regime": signal.get("regime", "NEUTRAL"),
        "features": signal.get("features", {}),
        "ev_at_entry": signal.get("ev", 0.0),
        "score_at_entry": signal.get("score", 0.0),
        "score_raw_at_entry": extra.get("score_raw") if extra else None,  # P1.1AI: canonical score fields
        "score_final_at_entry": extra.get("score_final") if extra else None,
        "p_at_entry": signal.get("p", signal.get("confidence", 0.5)),
        "coh_at_entry": signal.get("coh", signal.get("coherence", 1.0)),
        "af_at_entry": signal.get("af", signal.get("auditor_factor", 1.0)),
        "rde_decision": reason,
        "paper_source": extra.get("paper_source") if extra else "normal_rde_take",
        "explore_bucket": explore_bucket,
        "training_bucket": training_bucket,
        "bucket": bucket,  # P1.1AF: Canonical bucket field for learning state propagation
        "explore_sub_bucket": extra.get("explore_sub_bucket") if extra else "",  # P1.1i
        "original_decision": extra.get("original_decision") if extra else "TAKE",
        "reject_reason": extra.get("reject_reason") if extra else None,
        "side_inferred": extra.get("side_inferred") if extra else False,  # P1.1M
        "cost_edge_ok": extra.get("cost_edge_ok") if extra else True,  # P1.1M
        "cost_edge_bypassed": extra.get("cost_edge_bypassed", False) if extra else False,  # P1.1AK
        "cost_edge_bypass_reason": extra.get("cost_edge_bypass_reason", "none") if extra else "none",  # P1.1AK
        "bootstrap_closed_trades": extra.get("bootstrap_closed_trades", 0) if extra else 0,  # P1.1AK
        "expected_move_pct": extra.get("expected_move_pct") if extra else 0.0,  # P1.1M
        "required_move_pct": extra.get("required_move_pct") if extra else 0.23,  # P1.1M
        "size_mult": extra.get("size_mult") if extra else 1.0,
        "max_hold_s": extra.get("max_hold_s") if extra else _MAX_AGE_S,
        "tags": extra.get("tags") if extra else [],
        "created_at": ts,
        # P1.1AG: Track MFE/MAE for diagnostics
        "max_seen": price,
        "min_seen": price,
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

    # P1.1AG: Add entry quality diagnostics for paper training
    if paper_source == "training_sampler":
        _log_paper_train_quality_entry(position, signal)

    # Persist state after opening position
    _save_paper_state()

    return {
        "status": "opened",
        "trade_id": trade_id,
        "symbol": symbol,
        "entry_price": price,
    }


_LAST_KNOWN_PRICE_MAX_AGE_S = float(os.getenv("PAPER_LAST_PRICE_MAX_AGE_S", "120"))


def check_and_close_timeout_positions(now: Optional[float] = None) -> List[dict]:
    """P1.1AA+V3.1: Scan all open positions and close those that exceed effective hold time.

    Runs independently of price updates so timeout closes happen even when a symbol
    stops receiving price ticks.

    V3.1: Uses last known real market price (last_price/last_price_ts).
    If no recent price is available the position is quarantined with
    TIMEOUT_NO_PRICE and learning_skipped=True — never uses entry_price fallback
    which would produce fake flat PnL that poisons learning.

    Args:
        now: Current timestamp (default: time.time())

    Returns:
        list of closed trade dicts
    """
    global _PAPER_TIMEOUT_SCAN_THROTTLE

    if now is None:
        now = time.time()

    closed_trades = []
    positions_to_check = []
    expired_count = 0
    alive_count = 0

    with _POSITION_LOCK:
        for trade_id, pos in list(_POSITIONS.items()):
            entry_ts = _safe_float(pos.get("entry_ts") or pos.get("created_at"), 0.0)
            if entry_ts <= 0:
                continue
            age_s = now - entry_ts
            effective_hold = _effective_paper_hold_s(pos)
            if age_s >= effective_hold:
                positions_to_check.append((trade_id, pos, age_s, effective_hold))
                expired_count += 1
            else:
                alive_count += 1

    # Throttled diagnostic log
    if now - _PAPER_TIMEOUT_SCAN_THROTTLE >= _PAPER_TIMEOUT_SCAN_TTL:
        next_expiry_s = None
        with _POSITION_LOCK:
            for pos in _POSITIONS.values():
                entry_ts = _safe_float(pos.get("entry_ts") or pos.get("created_at"), 0.0)
                if entry_ts > 0:
                    remaining_s = max(0.0, _effective_paper_hold_s(pos) - (now - entry_ts))
                    if next_expiry_s is None or remaining_s < next_expiry_s:
                        next_expiry_s = remaining_s
        log.info(
            "[PAPER_TIMEOUT_SCAN] open=%d expired=%d alive=%d next_expiry_s=%.1f",
            len(_POSITIONS),
            expired_count,
            alive_count,
            next_expiry_s or 0.0,
        )
        _PAPER_TIMEOUT_SCAN_THROTTLE = now

    # Close timed-out positions (outside lock to avoid deadlock)
    for trade_id, pos, age_s, effective_hold in positions_to_check:
        symbol = pos.get("symbol", "UNKNOWN")
        last_price = pos.get("last_price", 0.0)
        last_price_ts = pos.get("last_price_ts", 0.0)
        price_age_s = now - last_price_ts if last_price_ts > 0 else float("inf")

        log.info(
            "[PAPER_TIMEOUT_DUE] trade_id=%s symbol=%s age_s=%.1f hold_limit_s=%.1f bucket=%s training_bucket=%s",
            trade_id, symbol, age_s, effective_hold,
            pos.get("explore_bucket", "UNKNOWN"),
            pos.get("training_bucket", ""),
        )

        if last_price and last_price > 0 and price_age_s <= _LAST_KNOWN_PRICE_MAX_AGE_S:
            # Close with real last-known market price (V3.1: no entry_price fallback)
            try:
                closed_trade = close_paper_position(
                    position_id=trade_id, price=last_price, ts=now, reason="TIMEOUT"
                )
                if closed_trade:
                    log.info(
                        "[PAPER_CLOSE_PATH] trade_id=%s symbol=%s reason=TIMEOUT learning_called=%s metrics_called=True",
                        trade_id, symbol, pos.get("paper_source") == "training_sampler",
                    )
                    closed_trades.append(closed_trade)
            except Exception as e:
                log.warning("[PAPER_TIMEOUT_CLOSE_ERROR] trade_id=%s err=%s", trade_id, e)
        else:
            # No recent price — quarantine: free the cap but skip learning
            log.warning(
                "[PAPER_TIMEOUT_NO_PRICE] trade_id=%s symbol=%s age_s=%d price_age_s=%.0f"
                " — closing without learning update",
                trade_id, symbol, int(age_s),
                price_age_s if price_age_s != float("inf") else -1,
            )
            with _POSITION_LOCK:
                if trade_id not in _POSITIONS:
                    continue
                pos = _POSITIONS.pop(trade_id)
            closed_trade = {
                **pos,
                "exit_price": 0.0,
                "exit_ts": now,
                "exit_reason": "TIMEOUT_NO_PRICE",
                "duration_s": age_s,
                "gross_pnl_pct": 0.0,
                "net_pnl_pct": 0.0,
                "outcome": "FLAT",
                "unit_pnl": 0.0,
                "weighted_pnl": 0.0,
                "learning_skipped": True,
            }

            # P1.1AJ: Emit quality exit for TIMEOUT_NO_PRICE (idempotent, all training positions)
            _log_quality_exit_once(closed_trade, pos, path="timeout_no_price")

            _save_paper_state()
            closed_trades.append(closed_trade)

    return closed_trades


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

        # Store last known price so timeout scanner can use real market price
        # P1.1AG: Track max_seen and min_seen for MFE/MAE calculation
        with _POSITION_LOCK:
            if trade_id in _POSITIONS:
                _POSITIONS[trade_id]["last_price"] = current_price
                _POSITIONS[trade_id]["last_price_ts"] = ts
                # Update extremes
                _POSITIONS[trade_id]["max_seen"] = max(_POSITIONS[trade_id].get("max_seen", current_price), current_price)
                _POSITIONS[trade_id]["min_seen"] = min(_POSITIONS[trade_id].get("min_seen", current_price), current_price)

        # Check exit conditions (P1.1AI: side-aware)
        entry_price = pos["entry_price"]
        age_s = ts - pos["entry_ts"]
        side = pos.get("side", "BUY")

        # P1.1Z: Use effective hold time (respects training position max_hold_s)
        effective_hold = _effective_paper_hold_s(pos)
        max_hold = pos.get("max_hold_s", pos.get("timeout_s", _MAX_AGE_S))
        timeout_s = pos.get("timeout_s", max_hold)

        exit_reason = None
        # P1.1AI: Side-aware TP/SL check
        if side == "BUY":
            tp_hit = current_price >= pos["tp"]
            sl_hit = current_price <= pos["sl"]
        else:  # SELL
            tp_hit = current_price <= pos["tp"]
            sl_hit = current_price >= pos["sl"]

        if tp_hit:
            exit_reason = "TP"
        elif sl_hit:
            exit_reason = "SL"
        elif age_s >= effective_hold:
            exit_reason = "TIMEOUT"

        if exit_reason:
            closed_trade = close_paper_position(position_id=trade_id, price=current_price, ts=ts, reason=exit_reason)
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

    # Buckets - P1.1AF: prefer canonical bucket field, then training_bucket, then explore_bucket
    bucket_raw = str(raw.get("bucket") or "").strip() or None
    training_bucket = str(raw.get("training_bucket") or "").strip() or None
    explore_bucket = str(raw.get("explore_bucket") or "").strip() or None
    bucket = bucket_raw or training_bucket or explore_bucket or "UNKNOWN"

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

    log.info(
        "[PAPER_CLOSE_PATH] trade_id=%s symbol=%s reason=%s",
        position_id,
        pos["symbol"],
        reason,
    )

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

    # P1.1AF: Log canonical bucket field (set from training_bucket or explore_bucket)
    canonical_bucket = pos.get("bucket") or pos.get("training_bucket") or pos.get("explore_bucket") or "A_STRICT_TAKE"

    log.warning(
        "[PAPER_EXIT] trade_id=%s symbol=%s reason=%s entry=%.8f exit=%.8f net_pnl_pct=%.4f outcome=%s hold_s=%d max_hold_s=%d bucket=%s training_bucket=%s",
        position_id,
        pos["symbol"],
        reason,
        pos["entry_price"],
        price,
        pnl_data["net_pnl_pct"],
        pnl_data["outcome"],
        int(duration_s),
        int(pos.get("max_hold_s") or _MAX_AGE_S),
        canonical_bucket,
        pos.get("training_bucket", ""),
    )

    # P1.1AJ: Log exit quality before deduplication (idempotent, all training positions)
    _log_quality_exit_once(closed_trade, pos, path="close_paper_position")

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

    # P1.1AG: Add to closed trades buffer for summary aggregation
    with _PAPER_CLOSED_TRADES_LOCK:
        _PAPER_CLOSED_TRADES_BUFFER.append(closed_trade)

    # Persist state after closing position
    _save_paper_state()

    # P1.1AG: Check if we should log summary
    _maybe_log_paper_quality_summary()

    # P1.1AJ: Safety net — ensure quality exit logged for training positions
    trade_id = closed_trade.get("trade_id")
    if _is_training_position(pos) and trade_id not in _QUALITY_EXIT_LOGGED:
        log.warning(
            "[PAPER_TRAIN_QUALITY_EXIT_MISSING] trade_id=%s symbol=%s reason=%s path=close_fallback",
            trade_id, pos.get("symbol", "na"), closed_trade.get("exit_reason", "unknown"),
        )
        _log_quality_exit_once(closed_trade, pos, path="fallback")

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


def normalize_paper_tp_sl(side: str, entry: float, tp: float, sl: float) -> dict:
    """P1.1AI: Compute side-valid TP/SL distances and repair inverted levels.

    BUY:  tp > entry > sl (TP above, SL below)
    SELL: sl > entry > tp (SL above, TP below)

    If SELL arrives with BUY-style levels (tp > entry, sl < entry), reflect
    distances around entry to fix the inversion.

    Args:
        side: "BUY" or "SELL"
        entry: Entry price
        tp: Take-profit price (may need repair)
        sl: Stop-loss price (may need repair)

    Returns:
        dict with keys: tp, sl, tp_pct, sl_pct, rr, repaired, repair_reason
        tp/sl are corrected for the side. If impossible after repair, returns None.
    """
    if entry <= 0:
        return None

    repaired = False
    repair_reason = None

    # Check if SELL arrived with inverted levels and repair if needed
    if side == "SELL" and tp > entry and sl < entry:
        # Reflect distances: swap to correct SELL semantics
        old_tp, old_sl = tp, sl
        tp = entry - abs(old_tp - entry)  # Pull TP below entry
        sl = entry + abs(entry - old_sl)  # Pull SL above entry
        repaired = True
        repair_reason = "sell_levels_inverted"

    # Validate corrected levels
    if side == "BUY":
        tp_valid = tp > entry
        sl_valid = sl < entry
    else:  # SELL
        tp_valid = tp < entry
        sl_valid = sl > entry

    if not (tp_valid and sl_valid):
        # Impossible levels even after repair
        return None

    # Compute distances and RR
    if side == "BUY":
        tp_pct = abs(tp - entry) / entry * 100.0 if entry > 0 else 0.0
        sl_pct = abs(entry - sl) / entry * 100.0 if entry > 0 else 0.0
    else:  # SELL
        tp_pct = abs(entry - tp) / entry * 100.0 if entry > 0 else 0.0
        sl_pct = abs(sl - entry) / entry * 100.0 if entry > 0 else 0.0

    rr = tp_pct / sl_pct if sl_pct > 0 else 0.0

    return {
        "tp": tp,
        "sl": sl,
        "tp_pct": tp_pct,
        "sl_pct": sl_pct,
        "rr": rr,
        "repaired": repaired,
        "repair_reason": repair_reason,
    }


def check_quality_entry_mismatch(trade_id: str, symbol: str, source: str) -> None:
    """P1.1AH: Check if a paper training entry has a corresponding quality entry log.

    If PAPER_TRAIN_ENTRY was logged but no PAPER_TRAIN_QUALITY_ENTRY exists,
    emit a diagnostic warning (does not block entry).

    Args:
        trade_id: The paper trade ID
        symbol: The symbol
        source: The entry source (e.g., "training_sampler")
    """
    if not trade_id or trade_id == "UNKNOWN":
        return

    with _QUALITY_ENTRY_LOCK:
        if trade_id not in _QUALITY_ENTRY_LOGGED:
            log.warning(
                "[PAPER_TRAIN_QUALITY_MISMATCH] type=missing_quality_entry trade_id=%s symbol=%s source=%s",
                trade_id,
                symbol,
                source,
            )


# P1.1AG: Paper training quality diagnostics helpers

def _log_paper_train_quality_entry(position: dict, signal: dict) -> None:
    """Log entry quality snapshot for paper training positions.

    Args:
        position: The opened position dict
        signal: The original signal that triggered the entry
    """
    try:
        # Extract fields with defensive defaults
        trade_id = position.get("trade_id", "na")

        # P1.1AH: Mark that quality entry was logged for this trade_id
        if trade_id != "na":
            with _QUALITY_ENTRY_LOCK:
                _QUALITY_ENTRY_LOGGED.add(trade_id)
        symbol = position.get("symbol", "na")
        side = position.get("side", "na")
        source = position.get("paper_source", "na")
        bucket = position.get("bucket") or position.get("training_bucket", "na")
        training_bucket = position.get("training_bucket", "na")
        regime = position.get("regime", "na")

        # Score fields - try canonical decision first
        score_raw = signal.get("score_raw", signal.get("score", 0.0))
        score_final = signal.get("score_final", signal.get("score", 0.0))

        ev = float(signal.get("ev") or 0.0)
        p = float(signal.get("p") or signal.get("confidence") or 0.5)
        coh = float(signal.get("coh") or signal.get("coherence") or 1.0)
        expected_move_pct = float(position.get("expected_move_pct") or 0.0)
        cost_edge_ok = position.get("cost_edge_ok", True)

        entry = float(position.get("entry_price") or 0.0)
        tp = float(position.get("tp") or 0.0)
        sl = float(position.get("sl") or 0.0)

        # P1.1AI: Handle expected_move_pct units — ATR absolute can be mislabeled as percent
        atr = float(signal.get("atr") or 0.0)
        expected_move_src = "position"
        if expected_move_pct > 2.0 and atr > 0 and abs(expected_move_pct - atr) < 0.1:
            # Heuristic: if expected_move_pct ≈ atr and both are > 2, likely mislabeled absolute ATR
            if entry > 0 and atr < entry * 0.02:  # If ATR < 2% of price, treat as absolute
                expected_move_pct_corrected = (atr / entry) * 100.0
                log.warning(
                    "[PAPER_TRAIN_ANOMALY] type=expected_move_unit_mismatch symbol=%s atr=%.8f entry=%.8f reported_pct=%.3f corrected_pct=%.3f",
                    symbol,
                    atr,
                    entry,
                    expected_move_pct,
                    expected_move_pct_corrected,
                )
                expected_move_pct = expected_move_pct_corrected
                expected_move_src = "atr_abs_corrected"

        # Calculate TP/SL pcts (should already be correct from normalize_paper_tp_sl)
        tp_pct = position.get("tp_pct_at_entry", 0.0)
        sl_pct = position.get("sl_pct_at_entry", 0.0)
        rr = position.get("rr_at_entry", 0.0)

        # P1.1AI: Properly handle score fields — detect missing vs zero
        score_raw_pos = position.get("score_raw_at_entry")
        score_final_pos = position.get("score_final_at_entry")
        score_missing = score_raw_pos is None and score_final_pos is None

        if score_raw_pos is not None:
            score_raw = float(score_raw_pos)
        elif score_final_pos is not None:
            score_raw = float(score_final_pos)
        else:
            score_raw = signal.get("score_raw", signal.get("score", None))
            if score_raw is not None:
                score_raw = float(score_raw)
            else:
                score_raw = None

        if score_final_pos is not None:
            score_final = float(score_final_pos)
        elif score_raw_pos is not None:
            score_final = float(score_raw_pos)
        else:
            score_final = signal.get("score_final", signal.get("score", None))
            if score_final is not None:
                score_final = float(score_final)
            else:
                score_final = None

        spread = float(signal.get("spread") or 0.0)
        hold_limit_s = int(position.get("max_hold_s") or 300)

        # Format score fields for logging
        score_raw_str = f"{score_raw:.3f}" if score_raw is not None else "na"
        score_final_str = f"{score_final:.3f}" if score_final is not None else "na"

        # P1.1AK: Extract bypass context fields
        cost_edge_bypassed = position.get("cost_edge_bypassed", False)
        cost_edge_bypass_reason = position.get("cost_edge_bypass_reason", "none")

        log.info(
            "[PAPER_TRAIN_QUALITY_ENTRY] trade_id=%s symbol=%s side=%s source=%s bucket=%s training_bucket=%s regime=%s ev=%.4f p=%.3f score_raw=%s score_final=%s score_missing=%s coh=%.3f expected_move_pct=%.3f expected_move_src=%s cost_edge_ok=%s cost_edge_bypassed=%s bypass_reason=%s entry=%.8f tp=%.8f sl=%.8f tp_pct=%.3f sl_pct=%.3f rr=%.3f atr=%.8f spread=%.8f hold_limit_s=%d",
            trade_id,
            symbol,
            side,
            source,
            bucket,
            training_bucket,
            regime,
            ev,
            p,
            score_raw_str,
            score_final_str,
            score_missing,
            coh,
            expected_move_pct,
            expected_move_src,
            cost_edge_ok,
            cost_edge_bypassed,
            cost_edge_bypass_reason,
            entry,
            tp,
            sl,
            tp_pct,
            sl_pct,
            rr,
            atr,
            spread,
            hold_limit_s,
        )

        # P1.1AK: Anomaly detection — cost_edge_ok=False but not bypassed
        if cost_edge_ok is False and cost_edge_bypassed is False:
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=cost_edge_false_without_bypass trade_id=%s symbol=%s source=%s",
                trade_id,
                symbol,
                source,
            )

        # P1.1AJ: Log diagnostic context when score is missing
        if score_missing and score_raw is None and score_final is None:
            available_keys = list(signal.keys()) if signal else []
            log.warning(
                "[PAPER_SCORE_MISSING_CONTEXT] symbol=%s source=%s keys=%s ev=%.4f ws=%.3f decision=%s",
                symbol,
                source,
                ",".join(available_keys),
                ev,
                float(signal.get("ws", 0.5)),
                signal.get("decision", "na"),
            )

        # P1.1AI: Log anomalies detected at entry
        # Only log score_zero_but_take if score is truly present and zero
        if score_raw is not None and score_final is not None:
            if score_raw == 0.0 and score_final == 0.0 and ev > 0:
                log.warning(
                    "[PAPER_TRAIN_ANOMALY] type=score_zero_but_take symbol=%s ev=%.4f score_raw=%.3f score_final=%.3f source=%s",
                    symbol,
                    ev,
                    score_raw,
                    score_final,
                    source,
                )
        elif score_missing and ev > 0:
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=score_missing_for_take symbol=%s ev=%.4f source=%s",
                symbol,
                ev,
                source,
            )

        if expected_move_pct > 5.0:
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=expected_move_extreme symbol=%s expected_move_pct=%.3f source=%s",
                symbol,
                expected_move_pct,
                source,
            )

        if (side == "BUY" and tp <= entry) or (side == "SELL" and tp >= entry):
            log.error(
                "[PAPER_TRAIN_ANOMALY] type=tp_sl_invalid symbol=%s entry=%.8f tp=%.8f sl=%.8f side=%s",
                symbol,
                entry,
                tp,
                sl,
                side,
            )
    except Exception as e:
        log.warning("[PAPER_TRAIN_QUALITY_ENTRY_ERROR] err=%s", str(e))


def _maybe_log_paper_train_econ_summary(trades: list) -> None:
    """Log economic summary of paper training trades (TP/SL geometry, near-miss metrics)."""
    if not trades:
        return

    try:
        closed = len(trades)
        timeouts = [t for t in trades if "TIMEOUT" in t.get("exit_reason", "")]
        timeout_rate = len(timeouts) / closed if closed > 0 else 0.0

        # near-TP timeout: TIMEOUT where mfe >= 70% of tp_pct
        # near-SL timeout: TIMEOUT where mae >= 70% of sl_pct
        # both_touch: trades where mfe >= tp_pct AND mae >= sl_pct
        near_tp = 0
        near_sl = 0
        both_touch = 0

        for t in trades:
            entry = float(t.get("entry_price", 0.0))
            max_seen = float(t.get("max_seen", entry))
            min_seen = float(t.get("min_seen", entry))
            side = t.get("side", "BUY")
            tp_pct = abs(float(t.get("tp_pct_at_entry", 0.012)))
            sl_pct = abs(float(t.get("sl_pct_at_entry", 0.012)))

            if entry > 0:
                if side == "BUY":
                    mfe = (max_seen - entry) / entry
                    mae = (entry - min_seen) / entry
                else:
                    mfe = (entry - min_seen) / entry
                    mae = (max_seen - entry) / entry
            else:
                mfe = 0.0
                mae = 0.0

            # Near-TP for TIMEOUT positions
            if "TIMEOUT" in t.get("exit_reason", "") and tp_pct > 0 and mfe / tp_pct >= 0.7:
                near_tp += 1
            # Near-SL for TIMEOUT positions
            if "TIMEOUT" in t.get("exit_reason", "") and sl_pct > 0 and mae / sl_pct >= 0.7:
                near_sl += 1
            # Both TP and SL touched
            if tp_pct > 0 and sl_pct > 0 and mfe >= tp_pct and mae >= sl_pct:
                both_touch += 1

        both_touch_rate = both_touch / closed if closed > 0 else 0.0
        avg_tp_pct = sum(abs(float(t.get("tp_pct_at_entry", 0.0))) for t in trades) / closed if closed > 0 else 0.0
        avg_sl_pct = sum(abs(float(t.get("sl_pct_at_entry", 0.0))) for t in trades) / closed if closed > 0 else 0.0
        cost_bypassed_count = sum(1 for t in trades if t.get("cost_edge_bypassed"))
        avg_pnl = sum(float(t.get("net_pnl_pct", 0.0)) for t in trades) / closed if closed > 0 else 0.0

        # Group by side and regime
        by_side = {}
        by_regime = {}
        for t in trades:
            side_key = t.get("side", "BUY")
            regime_key = t.get("regime", "UNKNOWN")

            for grp, key in [(by_side, side_key), (by_regime, regime_key)]:
                if key not in grp:
                    grp[key] = {"n": 0, "win": 0, "pnl": 0.0}
                grp[key]["n"] += 1
                grp[key]["win"] += int(t.get("outcome") == "WIN")
                grp[key]["pnl"] += float(t.get("net_pnl_pct", 0.0))

        by_side_str = ",".join(
            f"{k}:n={v['n']} wr={v['win']/v['n']:.2f} avg_pnl={v['pnl']/v['n']:.4f}"
            for k, v in sorted(by_side.items())
        )
        by_regime_str = ",".join(
            f"{k}:n={v['n']} wr={v['win']/v['n']:.2f}" for k, v in sorted(by_regime.items())
        )

        log.info(
            "[PAPER_TRAIN_ECON_SUMMARY] window_s=%.0f closed=%d timeout_rate=%.3f near_tp_timeout=%d near_sl_timeout=%d both_touch_rate=%.3f avg_tp_pct=%.4f avg_sl_pct=%.4f avg_pnl=%.4f cost_edge_bypassed=%d by_side=[%s] by_regime=[%s]",
            _PAPER_SUMMARY_INTERVAL,
            closed,
            timeout_rate,
            near_tp,
            near_sl,
            both_touch_rate,
            avg_tp_pct,
            avg_sl_pct,
            avg_pnl,
            cost_bypassed_count,
            by_side_str,
            by_regime_str,
        )
    except Exception as e:
        log.warning("[PAPER_TRAIN_ECON_SUMMARY_ERROR] err=%s", str(e))


def _maybe_log_paper_quality_summary() -> None:
    """Log a summary of paper training quality every 5 minutes."""
    global _PAPER_SUMMARY_LAST_LOG
    now = time.time()
    if now - _PAPER_SUMMARY_LAST_LOG < _PAPER_SUMMARY_INTERVAL:
        return

    with _PAPER_CLOSED_TRADES_LOCK:
        trades = list(_PAPER_CLOSED_TRADES_BUFFER)
        _PAPER_CLOSED_TRADES_BUFFER.clear()

    _PAPER_SUMMARY_LAST_LOG = now

    # P1.1AK: Log economic summary from the same snapshot
    _maybe_log_paper_train_econ_summary(trades)

    try:
        # Count open positions for "opened" metric
        with _POSITION_LOCK:
            opened_count = len(_POSITIONS)

        # Count quality entry logs recorded this window
        with _QUALITY_ENTRY_LOCK:
            zero_entry_logs = len(_QUALITY_ENTRY_LOGGED)  # Total logged this session
            _QUALITY_ENTRY_LOGGED.clear()  # Clear for next window

        # Aggregate closed trade stats
        closed_count = len(trades)
        win_count = sum(1 for t in trades if t.get("outcome") == "WIN")
        loss_count = sum(1 for t in trades if t.get("outcome") == "LOSS")
        flat_count = sum(1 for t in trades if t.get("outcome") == "FLAT")

        wr = (win_count / closed_count) if closed_count > 0 else 0.0
        avg_pnl = sum(t.get("net_pnl_pct", 0.0) for t in trades) / closed_count if closed_count > 0 else 0.0

        # MFE/MAE aggregates
        mfe_values = []
        mae_values = []
        for t in trades:
            entry = t.get("entry_price", 0.0)
            max_seen = t.get("max_seen", entry)
            min_seen = t.get("min_seen", entry)
            side = t.get("side", "BUY")

            if side == "BUY":
                mfe = ((max_seen - entry) / entry * 100.0) if entry > 0 else 0.0
                mae = ((min_seen - entry) / entry * 100.0) if entry > 0 else 0.0
            else:
                mfe = ((entry - min_seen) / entry * 100.0) if entry > 0 else 0.0
                mae = ((entry - max_seen) / entry * 100.0) if entry > 0 else 0.0

            mfe_values.append(mfe)
            mae_values.append(mae)

        avg_mfe = sum(mfe_values) / len(mfe_values) if mfe_values else 0.0
        avg_mae = sum(mae_values) / len(mae_values) if mae_values else 0.0

        # Group by source
        by_source = {}
        for t in trades:
            source = t.get("paper_source", "unknown")
            if source not in by_source:
                by_source[source] = {"n": 0, "wins": 0, "pnls": []}
            by_source[source]["n"] += 1
            if t.get("outcome") == "WIN":
                by_source[source]["wins"] += 1
            by_source[source]["pnls"].append(t.get("net_pnl_pct", 0.0))

        # Group by regime
        by_regime = {}
        for t in trades:
            regime = t.get("regime", "UNKNOWN")
            if regime not in by_regime:
                by_regime[regime] = {"n": 0, "wins": 0, "pnls": []}
            by_regime[regime]["n"] += 1
            if t.get("outcome") == "WIN":
                by_regime[regime]["wins"] += 1
            by_regime[regime]["pnls"].append(t.get("net_pnl_pct", 0.0))

        # Format summary string
        by_source_str = ", ".join(
            f"{src}:n={v['n']} wr={v['wins']/v['n']:.2f}" for src, v in sorted(by_source.items())
        )
        by_regime_str = ", ".join(
            f"{reg}:n={v['n']} wr={v['wins']/v['n']:.2f}" for reg, v in sorted(by_regime.items())
        )

        # P1.1AH: Count recent anomalies (conservative: count from buffer if available)
        anomaly_count = 0  # Would need separate tracking to count anomalies

        log.info(
            "[PAPER_TRAIN_QUALITY_SUMMARY] window_s=%.0f opened=%d closed=%d win=%d loss=%d flat=%d wr=%.4f avg_pnl=%.4f avg_mfe=%.4f avg_mae=%.4f zero_entry_logs=%d anomalies=%d by_source=[%s] by_regime=[%s]",
            _PAPER_SUMMARY_INTERVAL,
            opened_count,
            closed_count,
            win_count,
            loss_count,
            flat_count,
            wr,
            avg_pnl,
            avg_mfe,
            avg_mae,
            zero_entry_logs,
            anomaly_count,
            by_source_str,
            by_regime_str,
        )
    except Exception as e:
        log.warning("[PAPER_TRAIN_QUALITY_SUMMARY_ERROR] err=%s", str(e))


def _log_paper_train_quality_exit(closed_trade: dict, position: dict) -> None:
    """Log exit quality snapshot for paper training positions.

    Args:
        closed_trade: The closed trade dict with exit data
        position: The original position dict with entry data
    """
    try:
        # Extract fields
        trade_id = closed_trade.get("trade_id", "na")
        symbol = closed_trade.get("symbol", "na")
        side = closed_trade.get("side", "na")
        source = closed_trade.get("paper_source", "na")
        entry_regime = position.get("regime", "na")
        # Exit regime would need to come from current market state - use entry regime as fallback
        exit_regime = entry_regime
        training_bucket = closed_trade.get("training_bucket", "na")
        reason = closed_trade.get("exit_reason", "na")
        outcome = closed_trade.get("outcome", "na")

        entry = float(closed_trade.get("entry_price") or 0.0)
        exit_price = float(closed_trade.get("exit_price") or 0.0)
        net_pnl_pct = float(closed_trade.get("net_pnl_pct") or 0.0)

        # Calculate MFE/MAE - use position max_seen/min_seen if available
        max_seen = float(position.get("max_seen") or entry)
        min_seen = float(position.get("min_seen") or entry)

        if side == "BUY":
            mfe_pct = ((max_seen - entry) / entry * 100.0) if entry > 0 else 0.0
            mae_pct = ((min_seen - entry) / entry * 100.0) if entry > 0 else 0.0
        else:  # SELL
            mfe_pct = ((entry - min_seen) / entry * 100.0) if entry > 0 else 0.0
            mae_pct = ((entry - max_seen) / entry * 100.0) if entry > 0 else 0.0

        # Exit efficiency: net_pnl / mfe
        if mfe_pct > 0:
            exit_efficiency = net_pnl_pct / mfe_pct
        else:
            exit_efficiency = 0.0

        duration_s = closed_trade.get("duration_s")
        hold_s = int(duration_s) if duration_s is not None else 0
        hold_limit_s = int(position.get("max_hold_s") or 300)

        # Track if TP/SL were touched
        tp = float(position.get("tp") or 0.0)
        sl = float(position.get("sl") or 0.0)

        if side == "BUY":
            touched_tp = max_seen >= tp if tp > 0 else False
            touched_sl = min_seen <= sl if sl > 0 else False
        else:  # SELL
            touched_tp = min_seen <= tp if tp > 0 else False
            touched_sl = max_seen >= sl if sl > 0 else False

        # P1.1AH: Validate all required fields are present
        missing_fields = []
        if not trade_id or trade_id == "na":
            missing_fields.append("trade_id")
        if not symbol or symbol == "na":
            missing_fields.append("symbol")
        if mfe_pct is None:
            missing_fields.append("mfe_pct")
        if mae_pct is None:
            missing_fields.append("mae_pct")
        if exit_efficiency is None:
            missing_fields.append("exit_efficiency")

        if missing_fields:
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=quality_exit_missing_fields trade_id=%s symbol=%s missing=%s",
                trade_id,
                symbol,
                ",".join(missing_fields),
            )

        # P1.1AI: Validate TP/SL are side-aware at exit
        if entry > 0 and tp > 0 and sl > 0:
            if side == "BUY":
                if not (tp > entry > sl):
                    log.warning(
                        "[PAPER_TRAIN_ANOMALY] type=tp_sl_invalid_at_exit trade_id=%s symbol=%s side=%s entry=%.8f tp=%.8f sl=%.8f",
                        trade_id, symbol, side, entry, tp, sl
                    )
            elif side == "SELL":
                if not (entry > tp and sl > entry):
                    log.warning(
                        "[PAPER_TRAIN_ANOMALY] type=tp_sl_invalid_at_exit trade_id=%s symbol=%s side=%s entry=%.8f tp=%.8f sl=%.8f",
                        trade_id, symbol, side, entry, tp, sl
                    )

        log.info(
            "[PAPER_TRAIN_QUALITY_EXIT] trade_id=%s symbol=%s side=%s source=%s entry_regime=%s exit_regime=%s training_bucket=%s reason=%s outcome=%s entry=%.8f exit=%.8f net_pnl_pct=%.4f mfe_pct=%.4f mae_pct=%.4f hold_s=%d hold_limit_s=%d touched_tp=%s touched_sl=%s exit_efficiency=%.4f",
            trade_id,
            symbol,
            side,
            source,
            entry_regime,
            exit_regime,
            training_bucket,
            reason,
            outcome,
            entry,
            exit_price,
            net_pnl_pct,
            mfe_pct,
            mae_pct,
            hold_s,
            hold_limit_s,
            touched_tp,
            touched_sl,
            exit_efficiency,
        )

        # P1.1AG: Log anomalies detected at exit
        if reason == "TIMEOUT" and mfe_pct >= 0.75 * (tp - entry) / entry * 100.0 if entry > 0 else False:
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=timeout_near_tp symbol=%s mfe_pct=%.3f tp_pct=%.3f net_pnl_pct=%.3f",
                symbol,
                mfe_pct,
                ((tp - entry) / entry * 100.0) if entry > 0 else 0.0,
                net_pnl_pct,
            )

        if reason == "TIMEOUT" and abs(mae_pct) >= 0.75 * abs(sl - entry) / entry * 100.0 if entry > 0 else False:
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=timeout_deep_adverse symbol=%s mae_pct=%.3f sl_pct=%.3f net_pnl_pct=%.3f",
                symbol,
                mae_pct,
                abs((sl - entry) / entry * 100.0) if entry > 0 else 0.0,
                net_pnl_pct,
            )

        if entry_regime != exit_regime and entry_regime != "na" and exit_regime != "na":
            log.warning(
                "[PAPER_TRAIN_ANOMALY] type=regime_flip symbol=%s entry_regime=%s exit_regime=%s outcome=%s",
                symbol,
                entry_regime,
                exit_regime,
                outcome,
            )
    except Exception as e:
        log.warning("[PAPER_TRAIN_QUALITY_EXIT_ERROR] err=%s", str(e))


# P1.1Z2: Startup initialization — load paper state after all functions are defined
_PAPER_STATE_INITIALIZED = False


def _init_paper_state_once() -> None:
    """Initialize paper state once at module load time.

    Called at module bottom after all helper functions are defined.
    Prevents NameError for _reconcile_stale_paper_positions() and other helpers.
    """
    global _PAPER_STATE_INITIALIZED
    if _PAPER_STATE_INITIALIZED:
        return
    _PAPER_STATE_INITIALIZED = True
    try:
        _load_paper_state()
    except Exception as e:
        log.exception("[PAPER_STATE_LOAD_ERROR] source=%s err=%s", _STATE_FILE, e)


# Call startup initializer after all functions are defined
_init_paper_state_once()
