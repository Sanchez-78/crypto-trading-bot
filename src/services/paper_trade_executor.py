"""V10.13u+20: Paper trade executor using real live prices for learning."""
import os
import os.path
import logging
import time
import uuid
import sqlite3
import json
from typing import Optional, Dict, List

# V10.27: Load .env configuration (if python-dotenv available)
# P0.1 (audit 2026-07-16): override=False so a checked-out .env can NEVER silently
# override safety-critical env vars set by systemd/the process manager. The deploy
# environment (systemd Environment= / ExecStart) is the source of truth; .env only
# fills gaps for values NOT already exported.
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # P0.1: never override systemd-provided env vars
except ImportError:
    # Fallback: manual .env loading — also non-overriding (skip keys already in env)
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    if k not in os.environ:  # P0.1: do not override existing systemd env
                        os.environ[k] = v

from src.core.event_bus import subscribe_once
from src.core.trade_metrics_contract import classify_outcome

log = logging.getLogger(__name__)


def _is_truthy_env(value: Optional[str]) -> bool:
    """Return True if an env string looks affirmative (1/true/yes/on)."""
    if value is None:
        return False
    return value.strip().lower() in ("1", "true", "yes", "on", "y", "t")


def _enforce_paper_safe_mode() -> None:
    """P0.1 (audit 2026-07-16): fail-closed re-validation of trading-mode env.

    This module is the PAPER executor and must never run against a real-order
    configuration. If, after .env load, any live indicator is set
    (TRADING_MODE=live_real, or ENABLE_REAL_ORDERS / LIVE_TRADING_CONFIRMED truthy),
    log CRITICAL and force the process back to paper-safe values in os.environ.

    We deliberately do NOT raise: crashing the paper loop is worse than clamping.
    The invariant enforced is only that .env can never *silently promote* this
    paper executor to live.
    """
    trading_mode = os.environ.get("TRADING_MODE", "")
    enable_real = os.environ.get("ENABLE_REAL_ORDERS", "")
    live_confirmed = os.environ.get("LIVE_TRADING_CONFIRMED", "")

    live_indicated = (
        trading_mode.strip().lower() == "live_real"
        or _is_truthy_env(enable_real)
        or _is_truthy_env(live_confirmed)
    )
    if live_indicated:
        log.critical(
            "[PAPER_SAFETY_OVERRIDE] Live trading indicator detected in environment "
            "(TRADING_MODE=%r ENABLE_REAL_ORDERS=%r LIVE_TRADING_CONFIRMED=%r) — "
            "this is the PAPER executor; forcing paper-safe values. .env can never "
            "promote paper -> live.",
            trading_mode, enable_real, live_confirmed,
        )
        # Use a VALID paper mode from runtime_mode.TradingMode (paper_live), not the
        # invalid literal "paper" — get_trading_mode() would coerce "paper" to the
        # default anyway, but keep the env self-consistent (audit re-check 2026-07-16).
        os.environ["TRADING_MODE"] = "paper_live"
        os.environ["ENABLE_REAL_ORDERS"] = "0"
        os.environ["LIVE_TRADING_CONFIRMED"] = "0"


# P0.1: enforce paper-safe precedence immediately at import, after .env is loaded.
_enforce_paper_safe_mode()

# V10.49 CRITICAL: Wire learning system into exit handler
# Learning instance must be imported and available globally
_learning_instance = None
def set_learning_instance(instance):
    """Set the global learning instance (called from bot2/main.py).

    P0.2 (audit 2026-07-16): converge on the SINGLE process-wide learner singleton.
    Previously bot2 constructed a distinct PaperAdaptiveLearning() and passed it here,
    while the canonical close path recorded into get_learner()'s singleton — so every
    eligible close was recorded TWICE (double-counting lifetime_n / rolling windows /
    PF / WR / expectancy). We now ALWAYS bind `_learning_instance` to the get_learner()
    singleton, ignoring any distinct instance, so there is exactly one learner object.
    """
    global _learning_instance
    try:
        from src.services.paper_adaptive_learning import get_learner
        _learning_instance = get_learner()
        if instance is not None and instance is not _learning_instance:
            log.warning(
                "[LEARNING_WIRED] Ignoring distinct PaperAdaptiveLearning instance; "
                "bound to the get_learner() singleton (P0.2 double-learning fix)."
            )
    except Exception as e:
        # Fail-safe: fall back to whatever was passed rather than leaving unwired.
        _learning_instance = instance
        log.error("[LEARNING_WIRED] Could not resolve get_learner() singleton: %s", e)
    log.info("[LEARNING_WIRED] Global learning instance connected to paper_trade_executor")

# Phase 4C: Live PAPER metrics
try:
    from src.services.paper_training_metrics import record_paper_entry
except ImportError:
    record_paper_entry = None

# P0.4 (audit 2026-07-16): The historical import
#     from src.services.learning_integration import on_paper_trade_closed
# targeted a symbol that does NOT exist (learning_integration defines
# `class LearningIntegration` + a `learning` instance, with NO `on_paper_trade_closed`
# function/method). The import therefore ALWAYS failed -> on_paper_trade_closed=None
# -> the downstream `if on_paper_trade_closed:` sink was permanently dead code.
#
# The AUTHORITATIVE cache.sqlite sink for closed trades is
#     src.services.local_persistent_cache.save_closed_trade(...)
# invoked from src/services/trade_executor.py:1662. That path already dedupes on
# trade_id via `INSERT OR REPLACE INTO closed_trades`. The dead import and its
# branch have been removed to eliminate a misleading second "sink" that never ran.
#
# TODO(canonical-handler): a single canonical on_close handler that fans out to
# (adaptive learning + local_persistent_cache + metrics) is desirable, but is a
# larger refactor and intentionally out of scope for this correctness patch.

# P0.3B: Segment EV Gate (Pure logic for strict EV vs evidence collection)
try:
    from src.services.p0_segment_ev_gate import P0SegmentEVGate, SegmentKey
except ImportError:
    P0SegmentEVGate = None
    SegmentKey = None
    log.warning("[P0.3B] Failed to import p0_segment_ev_gate (P0 baseline disabled)")

# Configuration from environment
_INITIAL_EQUITY = float(os.getenv("PAPER_INITIAL_EQUITY_USD", "10000"))
_POSITION_SIZE_BASE = float(os.getenv("PAPER_POSITION_SIZE_USD", "25"))  # Base size for medium-confidence
_FEE_PCT = float(os.getenv("PAPER_FEE_PCT", "0.0015"))  # 0.15% round-trip
_SLIPPAGE_PCT = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.0003"))  # 0.03%
_MAX_OPEN = int(os.getenv("PAPER_MAX_OPEN_POSITIONS", "5"))  # Increased to allow more diversification
_MAX_AGE_S = float(os.getenv("PAPER_MAX_POSITION_AGE_S", "1200"))  # CYCLE 31: Increased to 1200s (20 min) to reach TP in low volatility (was 600s)
# 2026-07-09: the per-tick [TP_SL_EVAL] log.warning ran on the WebSocket receive
# thread at ~325 lines/s, saturating it → Binance dropped the slow consumer every
# ~2 min (feed reconnect churn / near-frozen prices). Gate it behind a debug flag
# (default OFF) so the price feed stays healthy. Set PAPER_DEBUG_TP_SL_EVAL=1 to re-enable.
_DEBUG_TP_SL_EVAL = os.getenv("PAPER_DEBUG_TP_SL_EVAL", "") == "1"
_MIN_EV_THRESHOLD = float(os.getenv("PAPER_MIN_EV_THRESHOLD", "0.01"))  # V10.26 FIX: Block zero-EV trades (was 0.0, allowing random entries)
_MIN_SEGMENT_PF = float(os.getenv("PAPER_MIN_SEGMENT_PF", "0.0"))  # AGGRESSIVE: No segment PF gating
_TIME_BASED_FILTERING = os.getenv("PAPER_TIME_BASED_FILTERING", "false").lower() == "true"  # AGGRESSIVE: No time gating

# V10.25: Per-symbol position caps for diversity (INCREASED for better portfolio)
_SYMBOL_CAPS = {
    "ETHUSDT": 10,     # Increase ETH from 1 to 10 for better position accumulation
    "ADAUSDT": 8,      # Increase ADA from 5 to 8
    "XRPUSDT": 8,      # Increase XRP from 5 to 8
    "BTCUSDT": 8,      # Increase BTC from 4 to 8
    "BNBUSDT": 5,      # Increase BNB from 3 to 5
    "DOTUSDT": 5,      # Increase DOT from 3 to 5
    "LTCUSDT": 5,      # Increase LTC from 3 to 5
    "LINKUSDT": 5,     # Increase LINK from 3 to 5
}

# V10.26: Minimum confidence filter for entries (reject weak signals)
_MIN_ENTRY_CONFIDENCE = float(os.getenv("PAPER_MIN_ENTRY_CONFIDENCE", "0.50"))  # Only open if w_sc >= 0.50

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

# V5 Legacy Bridge integration (Phase 3)
_V5_BRIDGE = None

# V10.15l: SQLite logging for dashboard
def _log_trade_to_sqlite(closed_trade: dict) -> None:
    """Log closed PAPER trade to local SQLite database for dashboard."""
    try:
        # V10.27 FIX: Use relative path in dev mode, absolute on Hetzner
        if os.path.exists('/opt/cryptomaster'):
            db_path = '/opt/cryptomaster/local_learning_storage/learning_database.sqlite'
        else:
            db_path = 'local_learning_storage/learning_database.sqlite'

        # Ensure directory exists
        db_dir = os.path.dirname(db_path) or '.'
        os.makedirs(db_dir, exist_ok=True)

        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute('''
            INSERT OR REPLACE INTO trades
            (trade_id, symbol, side, entry_price, exit_price, pnl_usd, pnl_pct,
             exit_reason, regime, entry_ts, exit_ts, hold_s, mfe_pct, mae_pct,
             size_usd, cost_edge_ok, learning_source, mode, trade_environment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            closed_trade.get('trade_id'),
            closed_trade.get('symbol'),
            closed_trade.get('side'),
            float(closed_trade.get('entry_price', 0)),
            float(closed_trade.get('exit_price', 0)),
            float(closed_trade.get('weighted_pnl', 0)),  # Use weighted_pnl which is USD amount
            float(closed_trade.get('net_pnl_pct', 0)),
            closed_trade.get('exit_reason'),
            closed_trade.get('regime', 'UNKNOWN'),
            float(closed_trade.get('entry_ts', 0)),
            float(closed_trade.get('exit_ts', time.time())),
            float(closed_trade.get('duration_s', 0)),
            float(closed_trade.get('mfe', 0)),  # May not have MFE/MAE in PAPER trades
            float(closed_trade.get('mae', 0)),
            float(closed_trade.get('size_usd', 0)),
            1,  # cost_edge_ok=True for paper trades
            'paper_training_sampler',
            'PAPER',
            os.getenv("PAPER_TRADE_ENV", "paper_train"),
        ))
        conn.commit()
        conn.close()
        log.info(f"[SQLITE_LOG_OK] trade_id={closed_trade.get('trade_id')} saved to {db_path}")
    except Exception as e:
        log.error(f"[SQLITE_LOG_ERROR] Failed to log paper trade: {e}", exc_info=True)
_V5_BRIDGE_LOCK = __import__("threading").RLock()


def _get_v5_bridge():
    """Lazy initialize V5 bridge singleton."""
    global _V5_BRIDGE
    if _V5_BRIDGE is None:
        with _V5_BRIDGE_LOCK:
            if _V5_BRIDGE is None:
                try:
                    from src.services.v5_legacy_bridge import V5LegacyBridge
                    # Get legacy Firebase client if available
                    firebase_client = None
                    try:
                        from src.services import firebase_client as fb_module
                        if hasattr(fb_module, 'db') and fb_module.db:
                            firebase_client = fb_module.db
                            log.info("[V5_BRIDGE_FIREBASE] Using legacy Firebase client")
                    except Exception as e:
                        log.debug(f"[V5_BRIDGE_FIREBASE] Legacy Firebase unavailable: {e}")

                    _V5_BRIDGE = V5LegacyBridge(firebase_client=firebase_client)
                    log.info(
                        "[V5_BRIDGE_INIT] enabled=true real_orders_allowed=false "
                        f"firebase_connected={firebase_client is not None} service=cryptomaster.service"
                    )
                except Exception as e:
                    log.error(f"[V5_BRIDGE_INIT_FAILED] {e}")
                    _V5_BRIDGE = False  # Mark as failed to avoid retry loop
    return _V5_BRIDGE if _V5_BRIDGE is not False else None


def _effective_paper_bucket(pos: dict, pnl_data: dict | None = None) -> str:
    """P1.1AP-J2: Resolve effective diagnostic bucket from position fields.

    Checks training_bucket first (training sampler), then explore_bucket (exploration),
    then computed bucket field, with fallback to A_STRICT_TAKE.
    """
    pnl_data = pnl_data or {}
    return (
        pos.get("training_bucket")
        or pos.get("explore_bucket")
        or pos.get("bucket")
        or pnl_data.get("training_bucket")
        or pnl_data.get("explore_bucket")
        or pnl_data.get("bucket")
        or "A_STRICT_TAKE"
    )


def _is_training_position(pos: dict) -> bool:
    """Check if position is a paper training position using broader gate.

    Matches the is_training check at line ~208-211.
    """
    return (
        pos.get("training_bucket") == "C_WEAK_EV_TRAIN"
        or pos.get("paper_source") == "training_sampler"
        or _effective_paper_bucket(pos) == "B_RECOVERY_READY"
    )


def _get_learner_state():
    """Get current learning state from paper_adaptive_learning singleton."""
    try:
        from src.services.paper_adaptive_learning import LEARNER
        return LEARNER
    except (ImportError, AttributeError, NameError):
        return None


def _get_segment_pf(symbol: str, regime: str, side: str) -> float:
    """Get profit factor for a specific segment (symbol:regime:side)."""
    learner = _get_learner_state()
    if not learner:
        return 1.0  # Default to trading if learner unavailable

    segment_key = f"{symbol}:{regime}:{side}"

    # Compute PF for this segment from rolling100
    segment_trades = [(e[0], e[1]) for e in learner.rolling100 if e[2] == segment_key]
    if not segment_trades:
        return 1.0  # No data yet, default to trade

    return learner._compute_pf(segment_trades)


def _calculate_dynamic_position_size(signal: dict) -> float:
    """Calculate position size based on signal confidence/EV.

    High-confidence (EV > 10%): $50-75 (2-3x base)
    Medium (EV 5-10%): $25 (1x base)
    Low (EV 3-5%): $10-15 (0.4-0.6x base)
    """
    ev = float(signal.get("ev") or 0.0)

    if ev >= 0.10:
        return _POSITION_SIZE_BASE * 2.5  # High confidence: 2.5x
    elif ev >= 0.07:
        return _POSITION_SIZE_BASE * 2.0  # Good confidence: 2x
    elif ev >= 0.05:
        return _POSITION_SIZE_BASE * 1.0  # Medium: 1x (base)
    elif ev >= 0.03:
        return _POSITION_SIZE_BASE * 0.5  # Low: 0.5x
    else:
        return _POSITION_SIZE_BASE * 0.3  # Very low: 0.3x


def _can_admit_paper_evidence_collection(symbol: str, regime: str) -> tuple[bool, str]:
    """P0.3C: Check if signal is allowed in evidence collection scope.

    Evidence collection scope (first restart):
    - ETHUSDT only
    - BULL_TREND only (optionally BEAR_TREND if safe)
    - Controlled caps

    Returns: (is_allowed, reason)
    """
    # Allowed symbols for evidence collection (V10.26: opened to all major pairs for trading diversity)
    EVIDENCE_SYMBOLS = {"ETHUSDT", "BTCUSDT", "BNBUSDT", "ADAUSDT", "XRPUSDT", "SOLUSDT", "DOTUSDT", "LTCUSDT", "LINKUSDT"}
    # Allowed regimes for evidence collection (V10.26: enabled both BULL and BEAR for full market coverage)
    EVIDENCE_REGIMES = {"BULL_TREND", "BEAR_TREND"}  # Full regime coverage for hedge/short opportunities

    if symbol not in EVIDENCE_SYMBOLS:
        return False, f"symbol_not_in_evidence_scope:{symbol}"

    if regime not in EVIDENCE_REGIMES:
        return False, f"regime_not_in_evidence_scope:{regime}"

    return True, "allowed_for_evidence_collection"


def _should_skip_segment_p0_strict_ev(
    symbol: str, side: str, regime: str, source: str, tp_sl_profile: str,
    closed_trades: Optional[list] = None
) -> tuple[bool, dict]:
    """P0.3B: Segment EV Gate — Decide if strict EV is allowed.

    Returns: (should_reject, decision_dict)
    where decision_dict contains:
        - strict_ev_allowed: bool
        - reason: str
        - readiness_eligible: bool
    """
    if P0SegmentEVGate is None:
        # P0.3B not available — fall through (no strict gate)
        return False, {
            "strict_ev_allowed": False,
            "reason": "p0_gate_unavailable",
            "readiness_eligible": False,
        }

    # Use closed trades from global state if not provided
    if closed_trades is None:
        try:
            import sqlite3
            db_path = '/opt/cryptomaster/local_learning_storage/cache.sqlite'
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute('SELECT * FROM closed_trades')
            cols = [desc[0] for desc in c.description]
            closed_trades = []
            for row in c.fetchall():
                closed_trades.append(dict(zip(cols, row)))
            conn.close()
        except Exception as e:
            log.warning(f"[P0_SEGMENT_GATE] Failed to load closed trades: {e}")
            closed_trades = []

    # Call P0 gate
    decision = P0SegmentEVGate.decide_segment_gate(
        symbol=symbol,
        side=side,
        regime=regime,
        source=source,
        tp_sl_profile=tp_sl_profile,
        closed_trades=closed_trades,
    )

    # Log decision
    throttle_key = (symbol, regime, source, "p0_gate")
    now_ts = time.time()
    last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
    if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
        log.info(
            "[P0_SEGMENT_GATE] symbol=%s side=%s regime=%s source=%s "
            "tp_sl_profile=%s segment_n=%s avg_pnl_usd=%s pf=%s timeout_rate=%s "
            "strict_ev_allowed=%s reason=%s readiness_eligible=%s",
            symbol, side, regime, source, tp_sl_profile,
            decision.stats.n if decision.stats else 0,
            f"{decision.stats.avg_pnl_usd:.8f}" if decision.stats else None,
            f"{decision.stats.profit_factor:.2f}" if decision.stats else None,
            f"{decision.stats.timeout_rate:.1%}" if decision.stats else None,
            decision.strict_ev_allowed,
            decision.reason,
            decision.readiness_eligible,
        )
        _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts

    # Return: (should_reject, decision)
    # Only reject if quarantined or explicitly blocked by gate
    should_reject = not decision.strict_ev_allowed
    return should_reject, {
        "strict_ev_allowed": decision.strict_ev_allowed,
        "reason": decision.reason,
        "readiness_eligible": decision.readiness_eligible,
        "stats": decision.stats,
    }


def _should_skip_segment_by_profitability(symbol: str, regime: str, side: str) -> tuple[bool, str]:
    """Check if segment should be skipped due to poor profitability.

    Returns: (should_skip, reason)
    """
    if not _MIN_SEGMENT_PF or _MIN_SEGMENT_PF <= 1.0:
        return False, ""  # Gating disabled

    segment_pf = _get_segment_pf(symbol, regime, side)
    if segment_pf < _MIN_SEGMENT_PF:
        return True, f"segment_pf_too_low={segment_pf:.2f}x"

    return False, ""


def _should_skip_time_of_day() -> tuple[bool, str]:
    """Check if current time-of-day should be skipped (poor historical performance).

    Returns: (should_skip, reason)
    """
    if not _TIME_BASED_FILTERING:
        return False, ""

    import datetime
    now = datetime.datetime.utcnow()
    hour = now.hour

    # Bad hours (0-2 UTC, 12-14 UTC typically see lower activity)
    # Adjust based on actual data from rolling metrics
    bad_hours = [0, 1, 2, 12, 13, 14]
    if hour in bad_hours:
        return True, f"bad_hour_of_day={hour}"

    return False, ""


# P1.1AP-D: Stale position quarantine thresholds (refined to exclude normal TP/SL)
_PAPER_MAX_PRICE_DEVIATION_PCT = 5.0  # Max price deviation % (entry/exit price difference)
_PAPER_MAX_PNL_PCT_EXTREME = 5.0  # Max abs(net_pnl_pct) for extreme corruption cases


def _is_stale_paper_position(pnl_data: dict, entry_price: float, exit_price: float, position: dict) -> tuple[bool, str]:
    """Check if paper position is stale/corrupt and should be quarantined.

    Detects positions with impossible price movements or extreme P&L that indicate
    data corruption (e.g., from file restore or price sync errors). Normal TP/SL
    exits around +/-2% are allowed.

    Returns:
        (is_stale, reason_string)
    """
    net_pnl_pct = pnl_data.get("net_pnl_pct", 0.0)

    # Check for impossible price movement (primary stale indicator)
    # If entry/exit prices differ by >5%, data is likely corrupt (restored or synced incorrectly)
    if entry_price > 0 and exit_price > 0:
        price_deviation_pct = abs(exit_price - entry_price) / entry_price * 100.0
        if price_deviation_pct > _PAPER_MAX_PRICE_DEVIATION_PCT:
            return True, f"price_deviation_pct={price_deviation_pct:.2f}"

    # Check for extreme P&L (only >5%, to allow normal TP/SL around +/-2%)
    # This catches cases like restored positions with corrupt prices
    if abs(net_pnl_pct) > _PAPER_MAX_PNL_PCT_EXTREME:
        return True, f"extreme_pnl_pct={net_pnl_pct:.4f}"

    return False, ""


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
        pos["max_hold_s"] = 600  # V10.27 CYCLE 24: Increased from 300 to 600 (need full window)
    elif bucket == "E_NO_PATTERN":
        pos["max_hold_s"] = 600  # V10.27 CYCLE 24: Increased from 300 to 600 (need full window)
    else:
        # Default safe value for unknown/A_STRICT_TAKE
        pos["max_hold_s"] = _MAX_AGE_S

    return pos


def _normalize_position_for_loading(pos: dict) -> dict:
    """P1.1AP-G: Normalize legacy position to ensure all required fields exist.

    Provides safe defaults for missing fields that would cause errors downstream.
    """
    # Ensure size_usd exists (needed for PnL calculation)
    if "size_usd" not in pos:
        pos["size_usd"] = pos.get("final_size_usd") or pos.get("size") or 10.0

    # Ensure entry_ts exists (needed for stale detection)
    if "entry_ts" not in pos:
        pos["entry_ts"] = pos.get("created_at") or pos.get("opened_at_ts") or time.time()

    # Ensure entry_price exists (needed for PnL calculation)
    if "entry_price" not in pos:
        pos["entry_price"] = pos.get("entry") or pos.get("price") or 0.0

    # Ensure side exists (needed for PnL calculation)
    if "side" not in pos:
        pos["side"] = pos.get("action") or "BUY"

    # Ensure symbol exists
    if "symbol" not in pos:
        pos["symbol"] = "UNKNOWN"

    # P1.1AV: Ensure tp/sl exist — missing tp/sl causes evaluation gate at line 1987 to fail (skip TP/SL, timeout only)
    # FIX: Load positions from JSON lack tp/sl fields (None), causing gate: if pos.get("tp") and pos["tp"] > 0 and pos.get("sl") and pos["sl"] > 0 to fail
    # This skips entire TP/SL block → ALL positions timeout. Add safe defaults.
    if "tp" not in pos or pos.get("tp") is None or pos.get("tp") == 0:
        # Calculate TP default from entry_price + tp_zone_bps (35 bps default)
        entry_price = pos.get("entry_price", 0.0)
        side = pos.get("side", "BUY")
        tp_zone_bps = int(os.getenv("PAPER_TP_ZONE_BPS", "35"))
        tp_pct = 1.0 + tp_zone_bps / 10000 if side == "BUY" else 1.0 - tp_zone_bps / 10000
        pos["tp"] = entry_price * tp_pct if entry_price > 0 else 0.0
        log.warning(f"[TP_DEFAULT] {pos.get('symbol', 'UNKNOWN')} side={side} entry={entry_price:.8f} tp_zone_bps={tp_zone_bps} → tp={pos['tp']:.8f}")

    if "sl" not in pos or pos.get("sl") is None or pos.get("sl") == 0:
        # Calculate SL default from entry_price - sl_zone_bps (30 bps default)
        entry_price = pos.get("entry_price", 0.0)
        side = pos.get("side", "BUY")
        sl_zone_bps = int(os.getenv("PAPER_SL_ZONE_BPS", "30"))
        sl_pct = 1.0 - sl_zone_bps / 10000 if side == "BUY" else 1.0 + sl_zone_bps / 10000
        pos["sl"] = entry_price * sl_pct if entry_price > 0 else 0.0
        log.warning(f"[SL_DEFAULT] {pos.get('symbol', 'UNKNOWN')} side={side} entry={entry_price:.8f} sl_zone_bps={sl_zone_bps} → sl={pos['sl']:.8f}")

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
        # P1.1AP-G: Normalize missing required fields before conversion
        pos = _normalize_position_for_loading(pos)

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

    Supports wrapper schema {"positions": {}}, canonical dict, and legacy list formats.
    Automatically converts and saves back in canonical format.
    """
    try:
        import json
        if not os.path.exists(_STATE_FILE):
            log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s missing=true", _STATE_FILE)
            return

        with open(_STATE_FILE, "r") as f:
            raw_data = json.load(f)

        # Handle empty state
        if not raw_data:
            log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s", _STATE_FILE)
            return

        # HOTFIX: Support wrapper schema {"positions": {}}
        positions_data = raw_data
        if isinstance(raw_data, dict) and "positions" in raw_data and isinstance(raw_data.get("positions"), dict):
            positions_data = raw_data["positions"]
            if not positions_data:
                log.info("[PAPER_STATE_LOAD] open_positions=0 source=%s wrapper_format=true", _STATE_FILE)
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
        # HOTFIX: Validate and normalize records before migration (skip invalid/metadata)
        migrated_count = 0
        validated_positions = {}
        for trade_id, pos in positions_data.items():
            # Skip invalid records: metadata keys, non-dict values
            if not isinstance(pos, dict):
                log.debug("[PAPER_STATE_SKIP_INVALID] trade_id=%s reason=not_dict type=%s", trade_id, type(pos).__name__)
                continue
            if trade_id in ("positions", "metadata"):
                log.debug("[PAPER_STATE_SKIP_INVALID] trade_id=%s reason=metadata_key", trade_id)
                continue

            # Valid position: normalize + migrate if needed
            pos = _normalize_position_for_loading(pos)  # Ensure required fields exist
            if "max_hold_s" not in pos:
                validated_positions[trade_id] = _migrate_legacy_position(pos)
                migrated_count += 1
            else:
                validated_positions[trade_id] = pos

        positions_data = validated_positions

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

                # Normalize timeout to effective hold time (max 600s for training)
                max_hold = _safe_float(pos.get("max_hold_s"), _MAX_AGE_S)
                timeout = _safe_float(pos.get("timeout_s"), max_hold)
                effective_timeout = min(max_hold or _MAX_AGE_S, timeout or _MAX_AGE_S, _MAX_AGE_S)

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

    P1.1AP-G: For exploration positions (explore_bucket set), respect explicit max_hold_s.
    - Training positions: capped at 300s
    - Exploration positions: use explicit max_hold_s if provided
    - Non-exploration: use configured timeout_s

    Args:
        pos: Position dict with training_bucket, max_hold_s, timeout_s, etc.

    Returns:
        Effective hold time in seconds
    """
    if not isinstance(pos, dict):
        return 300.0

    bucket = str(pos.get("training_bucket") or pos.get("bucket") or pos.get("explore_bucket") or "")
    source = str(pos.get("paper_source") or pos.get("mode") or "")
    explore_bucket = str(pos.get("explore_bucket") or "")

    is_training = (
        bucket == "C_WEAK_EV_TRAIN"
        or source == "training_sampler"
    )

    max_hold = _safe_float(pos.get("max_hold_s"), _MAX_AGE_S)
    timeout = _safe_float(pos.get("timeout_s"), max_hold)

    if is_training:
        # Training positions: effective hold is min of max_hold and timeout, capped at _MAX_AGE_S (V10.27 FIX: use config not hardcoded 300s)
        result = min(max_hold or _MAX_AGE_S, timeout or _MAX_AGE_S, _MAX_AGE_S)
        log.debug(
            f"[EFFECTIVE_HOLD_TRAINING] bucket={bucket} source={source} "
            f"max_hold={max_hold:.0f} timeout={timeout:.0f} result={result:.0f}"
        )
        return result

    # Non-training: P1.1AP-G - respect max_hold_s for exploration positions
    # (those with explicit explore_bucket like C_WEAK_EV)
    if explore_bucket and max_hold and max_hold > 30.0:
        log.debug(
            f"[EFFECTIVE_HOLD_EXPLORATION] bucket={bucket} explore_bucket={explore_bucket} "
            f"max_hold={max_hold:.0f} returning={max_hold:.0f}"
        )
        return float(max_hold)

    # Non-exploration: use configured timeout or default (V10.26 fix: was max(30.0,...) causing 30s closeout)
    result = timeout or _MAX_AGE_S
    log.debug(
        f"[EFFECTIVE_HOLD_NONTRAIN] bucket={bucket} explore_bucket={explore_bucket} "
        f"timeout={timeout:.0f} _MAX_AGE_S={_MAX_AGE_S:.0f} result={result:.0f}"
    )
    return result


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

    # Outcome based on net PnL after costs (not exit reason). Classified via the
    # single canonical ±0.05pp deadband in trade_metrics_contract — behaviour is
    # identical to the previous inline >0.05 / <-0.05 branch. Pass the UNROUNDED
    # net so the boundary comparison matches the historical result exactly.
    outcome = classify_outcome(net_pnl_pct).value

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


def evaluate_paper_tp_sl_exits(price_by_symbol: Optional[dict] = None, now: Optional[float] = None) -> dict:
    """Evaluate and close PAPER positions that hit TP or SL targets.

    This is the CRITICAL missing function that evaluates TP/SL exits before timeout.
    Should be called every price tick or at least every 1-5 seconds.

    Args:
        price_by_symbol: Dict of current prices by symbol (uses last_price from positions if not provided)
        now: Current timestamp (default: time.time())

    Returns:
        dict with counts: {"tp_exits": N, "sl_exits": N, "total_closed": N}
    """
    if price_by_symbol is None:
        price_by_symbol = {}
    if now is None:
        now = time.time()

    tp_exits = 0
    sl_exits = 0
    positions_to_close = []

    with _POSITION_LOCK:
        for trade_id, pos in list(_POSITIONS.items()):
            symbol = pos.get("symbol", "UNKNOWN")
            side = pos.get("side", "BUY")
            entry_price = _safe_float(pos.get("entry_price"), 0.0)
            tp_price = _safe_float(pos.get("tp"), 0.0)
            sl_price = _safe_float(pos.get("sl"), 0.0)

            # Use provided price or fall back to last_price from position
            last_price = _safe_float(price_by_symbol.get(symbol), 0.0)
            if last_price <= 0:
                last_price = _safe_float(pos.get("last_price"), 0.0)

            if entry_price <= 0 or last_price <= 0 or tp_price <= 0 or sl_price <= 0:
                continue

            # Check TP hit (before SL to prioritize profit)
            if side == "BUY" and last_price >= tp_price:
                positions_to_close.append((trade_id, pos, last_price, "TP"))
                tp_exits += 1
            elif side == "SELL" and last_price <= tp_price:
                positions_to_close.append((trade_id, pos, last_price, "TP"))
                tp_exits += 1

            # Check SL hit (only if TP not already marked)
            elif side == "BUY" and last_price <= sl_price:
                positions_to_close.append((trade_id, pos, last_price, "SL"))
                sl_exits += 1
            elif side == "SELL" and last_price >= sl_price:
                positions_to_close.append((trade_id, pos, last_price, "SL"))
                sl_exits += 1

    # Close positions outside lock
    for trade_id, pos, exit_price, reason in positions_to_close:
        try:
            close_paper_position(
                position_id=trade_id,
                price=exit_price,
                ts=now,
                reason=reason,
            )
            log.info(
                "[PAPER_TP_SL_EXIT] trade_id=%s symbol=%s reason=%s exit_price=%.2f",
                trade_id,
                pos.get("symbol", "UNKNOWN"),
                reason,
                exit_price,
            )
        except Exception as e:
            log.warning(f"[PAPER_TP_SL_EXIT_ERROR] trade_id={trade_id} err={e}")

    return {
        "tp_exits": tp_exits,
        "sl_exits": sl_exits,
        "total_closed": tp_exits + sl_exits,
    }


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
    # V10.16: SELL ENFORCEMENT - balance BUY/SELL ratio for diversification
    side_raw = signal.get("action", signal.get("side", "BUY"))
    now_ts = time.time()  # V10.27: define before any early branch; peak-check (2d4aa48) reads it on the price-valid path
    with _POSITION_LOCK:
        buy_count = sum(1 for p in _POSITIONS.values() if p.get("side") == "BUY")
        sell_count = sum(1 for p in _POSITIONS.values() if p.get("side") == "SELL")
        total = buy_count + sell_count

    if total >= 3:  # Enforce even with small samples
        buy_ratio = buy_count / max(total, 1)
        # Force 40/60 minimum for minority side
        if buy_ratio > 0.65 and side_raw == "BUY":
            # Too many BUY, REJECT to force SELL
            return {"status": "blocked", "reason": "buy_enforcement", "detail": f"BUY={buy_ratio:.0%}"}
        elif buy_ratio < 0.35 and side_raw == "SELL":
            # Too many SELL, REJECT to force BUY
            return {"status": "blocked", "reason": "sell_enforcement", "detail": f"SELL={1-buy_ratio:.0%}"}

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

    # V10.26 NEW: Skip entries at market peaks (avoids -0.2% immediate loss)
    # Check if entry price is within 1% of recent peak = likely at resistance
    symbol = signal.get("symbol", "UNKNOWN")
    with _POSITION_LOCK:
        symbol_positions = [p for p in _POSITIONS.values() if p.get("symbol") == symbol and not _is_position_stale(p, now_ts)]
        if symbol_positions:
            # Use recent entries for this symbol as peak reference
            recent_prices = [p.get("entry_price", 0) for p in symbol_positions[-5:]]
            peak_price = max(recent_prices) if recent_prices else price
            price_from_peak_pct = abs(price - peak_price) / peak_price * 100 if peak_price > 0 else 0

            pass  # Removed entry_at_peak check for BUY — in uptrends all prices are near recent peak

    symbol = signal.get("symbol", "UNKNOWN")
    # P1.1AF: Ensure bucket field is set (primary is training_bucket, fallback to explore_bucket)
    training_bucket = extra.get("training_bucket") if extra else None
    explore_bucket = extra.get("explore_bucket") if extra else None
    bucket = training_bucket or explore_bucket  # Primary: training_bucket, fallback: explore_bucket
    paper_source = extra.get("paper_source") if extra else None

    # PROFITABILITY FIX: Reject weak signals with low expected value (V10.26: apply to ALL entries)
    ev = float(signal.get("ev") or 0.0)
    if ev < _MIN_EV_THRESHOLD:  # V10.26: Changed from "and bucket == C_WEAK_EV_TRAIN" to ALL trades
        throttle_key = (symbol, bucket, "weak_ev_rejected")
        now_ts = time.time()
        last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
        if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
            log.warning(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=weak_ev ev=%.4f threshold=%.4f bucket=%s",
                symbol, ev, _MIN_EV_THRESHOLD, bucket
            )
            _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
        return {"status": "blocked", "reason": f"weak_ev_below_{_MIN_EV_THRESHOLD}"}

    # P0.3B: SEGMENT EV GATE - Strict EV approval requires segment evidence
    regime = signal.get("regime", "NEUTRAL")
    side_raw = signal.get("action", signal.get("side", "BUY"))
    side_normalized, _ = _normalize_side(side_raw)

    # Call P0.3B gate
    tp_sl_profile = extra.get("tp_sl_profile", "unknown") if extra else "unknown"
    source = paper_source or "rde_take"

    reject_p0, p0_decision = _should_skip_segment_p0_strict_ev(
        symbol=symbol,
        side=side_normalized,
        regime=regime,
        source=source,
        tp_sl_profile=tp_sl_profile,
    )

    if reject_p0:
        # P0.3C: Strict EV blocked → Route to evidence collection if allowed
        can_admit_evidence, evidence_reason = _can_admit_paper_evidence_collection(symbol, regime)

        if can_admit_evidence:
            # P0.3C: Route to evidence collection with EXPLICIT metadata
            log.info(
                "[P0_EVIDENCE_COLLECTION_ADMIT] symbol=%s regime=%s "
                "strict_ev_allowed=false reason=%s evidence_reason=%s",
                symbol, regime,
                p0_decision.get("reason", "unknown"),
                evidence_reason,
            )

            # Set metadata BEFORE opening position
            signal["strict_ev"] = False
            signal["readiness_eligible"] = False
            signal["learning_source"] = "paper_evidence_collection"
            signal["p0_gate_reason"] = p0_decision.get("reason", "p0_rejected")
            signal["segment_key"] = f"{symbol}_{side_normalized}_{regime}_{source}_{tp_sl_profile}"

            # Update paper_source for tracking
            if extra is None:
                signal["extra"] = {}
            else:
                signal["extra"] = extra

            signal["extra"]["paper_source"] = "paper_evidence_collection"
            signal["extra"]["p0_gate_reason"] = p0_decision.get("reason", "unknown")
            signal["extra"]["segment_key"] = signal["segment_key"]

            # Continue to position opening with evidence metadata set
            log.debug(
                "[P0_EVIDENCE_COLLECTION_METADATA] signal_id=%s source=paper_evidence_collection "
                "strict_ev=false readiness_eligible=false segment_key=%s",
                signal.get("trade_id", "unknown"),
                signal["segment_key"],
            )

        else:
            # Not allowed in evidence collection scope → Block
            throttle_key = (symbol, "p0_gate", evidence_reason)
            now_ts = time.time()
            last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
            if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
                log.info(
                    "[PAPER_ENTRY_P0_REJECTED] symbol=%s regime=%s "
                    "strict_ev_reason=%s evidence_reason=%s",
                    symbol, regime,
                    p0_decision.get("reason", "unknown"),
                    evidence_reason,
                )
                _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts

            return {"status": "blocked", "reason": f"p0_gate:{evidence_reason}"}

    # Optional: Old segment profitability gate (for backwards compatibility if needed)
    skip_segment, skip_reason = _should_skip_segment_by_profitability(symbol, regime, side_normalized)
    if skip_segment:
        throttle_key = (symbol, "segment_gate", skip_reason)
        now_ts = time.time()
        last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
        if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
            log.warning(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=segment_unprofitable %s",
                symbol, skip_reason
            )
            _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
        return {"status": "blocked", "reason": f"segment_gate:{skip_reason}"}

    # TIME-OF-DAY FILTERING: Skip poor hours
    skip_time, skip_time_reason = _should_skip_time_of_day()
    if skip_time:
        throttle_key = (symbol, "time_gate", skip_time_reason)
        now_ts = time.time()
        last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
        if now_ts - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
            log.debug(
                "[PAPER_ENTRY_BLOCKED] symbol=%s reason=time_of_day_poor %s",
                symbol, skip_time_reason
            )
            _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now_ts
        return {"status": "blocked", "reason": f"time_gate:{skip_time_reason}"}

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

        # Check per-symbol cap first (V10.25: enforce symbol diversity)
        now = time.time()
        alive_positions = [p for p in _POSITIONS.values() if not _is_position_stale(p, now)]
        symbol_cap = _SYMBOL_CAPS.get(symbol, 999)  # Use hardcoded caps dict
        alive_for_symbol = [p for p in alive_positions if p.get("symbol") == symbol]
        if len(alive_for_symbol) >= symbol_cap:
            throttle_key = (symbol, "symbol_cap", "exceeded")
            last_log = _PAPER_ENTRY_BLOCKED_THROTTLE.get(throttle_key, 0.0)
            if now - last_log >= _PAPER_ENTRY_BLOCKED_TTL:
                log.info(
                    "[PAPER_ENTRY_BLOCKED] symbol=%s reason=symbol_cap_exceeded cap=%d open=%d",
                    symbol, symbol_cap, len(alive_for_symbol)
                )
                _PAPER_ENTRY_BLOCKED_THROTTLE[throttle_key] = now
            return {"status": "blocked", "reason": f"symbol_cap_exceeded"}

        # Then check total paper position cap (P1.1Z: exclude stale positions)
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

    # Apply exploration sizing if provided; otherwise use dynamic position size based on confidence
    size_usd = _calculate_dynamic_position_size(signal)
    if extra and "final_size_usd" in extra:
        size_usd = extra["final_size_usd"]

    # V10.27 CYCLE 7 FIX: Wire PAPER_TP_ZONE_BPS/SL_ZONE_BPS as AUTHORITATIVE override
    # Evidence: Cycles #5-6 revealed env-var wiring was in unreachable code; tp_from_executor
    # ATR bands (~40bps) always override. Compute env-var bands FIRST, use them to override.
    # CYCLE 28 FIX: ATR-based dynamic TP sizing (static TP unreachable vs realized vol)
    # V10.28: Prioritize explicit env var over dynamic calculation
    # Get ATR for logging regardless of calculation path
    atr_v = float(signal.get("atr") or 0.0)
    regime = signal.get("regime", "UNKNOWN")  # Get regime from signal for learning lookup

    # V10.55 DISABLED: Stagnation gate blocked all trades (ATR permanently < threshold)
    # Finding: Market too flat for any gating strategy in current regime
    # Revert to profitable baseline: accept TIMEOUT-only exits, let learning system adapt
    # Entry quality will improve via learning feedback loop as trades accumulate data

    # V10.52 CRITICAL: Try to use learned TP from learning system first (autonomous adaptation)
    learned_tp_pct = None
    if _learning_instance and regime != "UNKNOWN":
        try:
            atr_pct = atr_v / price if atr_v > 0 and price > 0 else 0.01
            learned_tp_pct = _learning_instance.get_regime_tp_target(regime, atr_pct)
            if learned_tp_pct and learned_tp_pct > 0:
                tp_zone_bps_learned = int(learned_tp_pct * 100)  # learned_tp_pct is already %, convert to bps (0.18% = 18 bps)
                log.info(f"[LEARNING_TP_USED] symbol={symbol} regime={regime} learned_tp={learned_tp_pct*100:.3f}% ({tp_zone_bps_learned}bps)")
        except Exception as e:
            log.warning(f"[LEARNING_TP_ERROR] Failed to get learned TP: {e}")

    if os.getenv("PAPER_TP_ZONE_BPS"):
        # Env var explicitly set — use it for ALL positions (symmetric, reproducible)
        tp_zone_bps = int(os.getenv("PAPER_TP_ZONE_BPS"))
    elif learned_tp_pct and learned_tp_pct > 0:
        # V10.52: Use learned TP if available (enables bot self-improvement)
        # FIX: learned_tp_pct is already in percentage (0.18 = 0.18%), not decimal (0.0018)
        tp_zone_bps = int(learned_tp_pct * 100)  # Convert 0.18% to 18 bps (not 1800)
        log.info(f"[LEARNING_ADAPTATION] Using learned TP {tp_zone_bps}bps ({learned_tp_pct*100:.2f}%) for {symbol}")
    else:
        # Fallback: Env var not set and no learned TP — use dynamic calculation
        # V10.55 CYCLE 52+ FIX: Increase baseline TP to 50bps (was 35bps, too aggressive)
        # Evidence: 39.83% WR with 0.18-0.36% learned TP exiting at losses
        # Solution: Wider TP bands allow market to move more before exit → more profits
        tp_zone_bps_static = int(os.getenv("PAPER_TP_ZONE_BPS", "50"))  # 0.50% = baseline for wider targets
        if atr_v > 0 and price:
            atr_pct = atr_v / price
            dynamic_tp_bps = max(40, int(atr_pct * 10000 * 0.8))  # ATR floor raised to 40bps, multiplier 0.8
            tp_zone_bps = min(dynamic_tp_bps, 100)  # Cap at 1.0% to avoid runaway
        else:
            tp_zone_bps = tp_zone_bps_static
    sl_zone_bps = int(os.getenv("PAPER_SL_ZONE_BPS", "40"))  # Increased from 30bps to 40bps for breathing room
    tp_pct_env = 1.0 + tp_zone_bps / 10000 if side == "BUY" else 1.0 - tp_zone_bps / 10000
    sl_pct_env = 1.0 - sl_zone_bps / 10000 if side == "BUY" else 1.0 + sl_zone_bps / 10000
    tp_price_env = price * tp_pct_env
    sl_price_env = price * sl_pct_env

    # V10.22 CRITICAL: Use TP/SL from trade_executor if provided (computed with full context)
    # Otherwise fall back to local computation with responsive percentages
    tp_price = None
    sl_price = None
    tp_sl = None  # Initialize BEFORE conditional

    # Try to use pre-computed TP/SL from trade_executor
    if extra and "tp_from_executor" in extra and "sl_from_executor" in extra:
        tp_price = extra["tp_from_executor"]
        sl_price = extra["sl_from_executor"]
        tp_sl = normalize_paper_tp_sl(side, price, tp_price, sl_price)
        if tp_sl:
            log.info(f"[PAPER_TP_SL_FROM_EXECUTOR] symbol={symbol} side={side} tp={tp_price:.8f} sl={sl_price:.8f}")
        else:
            log.warning(f"[PAPER_TP_SL_VALIDATION_FAILED] symbol={symbol} side={side} tp={tp_price:.8f} sl={sl_price:.8f} - fallback to local")
            tp_sl = None  # Will fall back to local computation

    # V10.27 CYCLE 7: If PAPER_TP_ZONE_BPS is explicitly set (not default), override with env bands
    if os.getenv("PAPER_TP_ZONE_BPS"):  # If explicitly configured
        tp_price = tp_price_env
        sl_price = sl_price_env
        tp_sl = normalize_paper_tp_sl(side, price, tp_price_env, sl_price_env)
        if tp_sl:
            log.info(f"[PAPER_TP_SL_ENV_OVERRIDE] symbol={symbol} tp_bps={tp_zone_bps} sl_bps={sl_zone_bps} tp={tp_price:.8f} sl={sl_price:.8f}")

    # Fallback: compute locally with responsive percentages (if neither executor nor env override worked)
    tp_pct = tp_pct_env if os.getenv("PAPER_TP_ZONE_BPS") else (1.004 if side == "BUY" else 0.996)
    sl_pct = sl_pct_env if os.getenv("PAPER_SL_ZONE_BPS") else (0.997 if side == "BUY" else 1.003)
    if not tp_sl:
        # V10.24 CYCLE 2: AGGRESSIVE - Match market reality (small frequent moves)
        # Cycle 1 evidence: 6% TP all TIMEOUT at 180s; only 0.008-0.39% moves observed
        # Root cause: Market doesn't move 6% in 180s; positions reverse-to-loss
        # New strategy: Small TP + fast exits = catch the real moves before reversal
        # V10.27: TP=0.4%, SL=0.3% — 2.5%/2% bands were unreachable in 180s (price
        # moves only 0.00-0.12% in the window -> 100% TIMEOUT). 0.4% TP clears the
        # ~0.15% round-trip cost; matches compute_tp_sl floors in trade_executor.
        tp_sl = normalize_paper_tp_sl(side, price, price * tp_pct, price * sl_pct)
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

    # P1.1AN: Calibrate TP/SL for paper training with C_WEAK_EV_TRAIN bucket
    mode = "paper_train" if paper_source == "training_sampler" else "paper_live"
    expected_move = extra.get("expected_move_pct", 0.0) if extra else 0.0
    tp_sl_calibrated = calibrate_paper_training_geometry(
        mode=mode,
        source=paper_source or "normal_rde_take",
        training_bucket=training_bucket or "",
        side=side,
        entry=price,
        tp_sl=tp_sl,
        expected_move_pct=expected_move,
        fee_drag_pct=_FEE_PCT * 100.0,  # Convert to %
    )
    if tp_sl_calibrated:
        tp_sl = tp_sl_calibrated

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
        # CYCLE 28: Persist ATR-scaled entry band so sync path reuses it (no clobber)
        "tp_zone_bps_at_entry": tp_zone_bps,
        "sl_zone_bps_at_entry": sl_zone_bps,
        "atr_at_entry": atr_v,
        # P0.3D: Metadata for audit trail
        "strict_ev": signal.get("strict_ev", True),  # P0 gate decision
        "readiness_eligible": signal.get("readiness_eligible", True),  # Readiness claim eligibility
        "learning_source": signal.get("learning_source", "strict_ev"),  # paper_evidence_collection or strict_ev
        "segment_key": signal.get("segment_key", f"{symbol}_unknown"),  # For segment analytics
        "p0_gate_reason": signal.get("p0_gate_reason", None),  # Why P0 gate decided
        # P1.1AN: Calibration metadata
        "geometry_calibrated": tp_sl.get("calibrated", False),
        "tp_pct_before_calibration": tp_sl.get("tp_pct_before", tp_sl.get("tp_pct", 0.0)),
        "sl_pct_before_calibration": tp_sl.get("sl_pct_before", tp_sl.get("sl_pct", 0.0)),
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
        # P1.1AP-N2A: Preserve recovery admission metadata through lifecycle
        # NOTE: learning_source ALREADY SET ABOVE at line 1452 from signal (P0.3D)
        # DO NOT override here — P0 metadata must not be lost
        "recovery_admission": extra.get("recovery_admission", False) if extra else False,  # P1.1AP-N2C
        "admission_reason": extra.get("admission_reason") if extra else None,
        "historical_health": extra.get("historical_health") if extra else None,
        "expected_move_src": extra.get("expected_move_src") if extra else None,
    }

    # P0.3F GUARD: Fail-closed check — all positions MUST have P0 metadata
    if "learning_source" not in position or position["learning_source"] is None:
        log.error(
            "[P0_METADATA_BLOCK] trade_id=%s symbol=%s reason=missing_learning_source "
            "strict_ev=%s readiness_eligible=%s — entry BLOCKED",
            trade_id, symbol,
            position.get("strict_ev", "UNKNOWN"),
            position.get("readiness_eligible", "UNKNOWN"),
        )
        return {"status": "blocked", "reason": "p0_metadata_missing"}

    if position.get("strict_ev") is None or position.get("readiness_eligible") is None:
        log.error(
            "[P0_METADATA_BLOCK] trade_id=%s symbol=%s reason=missing_strict_ev_or_readiness "
            "learning_source=%s — entry BLOCKED",
            trade_id, symbol,
            position.get("learning_source", "UNKNOWN"),
        )
        return {"status": "blocked", "reason": "p0_metadata_incomplete"}

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

    # Phase 4C: Record PAPER entry metric
    if record_paper_entry:
        try:
            record_paper_entry(symbol, side, paper_source or reason)
        except Exception as e:
            log.debug("[PAPER_METRICS_RECORD_FAIL] entry symbol=%s err=%s", symbol, str(e))

    # V5 Legacy Bridge: Record paper entry (Phase 3 hook)
    try:
        v5_bridge = _get_v5_bridge()
        if v5_bridge:
            from src.services.v5_legacy_bridge.event_models import LegacyPaperOpenEvent
            open_event = LegacyPaperOpenEvent(
                trade_id=trade_id,
                symbol=symbol,
                side=side,
                strategy_id=paper_source or "normal_rde_take",
                regime=position.get("regime", "NEUTRAL"),
                entry_ts=ts,
                entry_price=price,
                size=size_usd,
                bucket=bucket or training_bucket or "UNKNOWN",
                expected_move_bps=int((position.get("expected_move_pct", 0.0) or 0.0) * 10000),
                required_move_bps=int((position.get("required_move_pct", 0.23) or 0.23) * 10000),
                cost_edge_ok=position.get("cost_edge_ok", True),
                real_orders_allowed=False,
                metadata={"paper_source": paper_source or "normal_rde_take"},
            )
            v5_bridge.record_open(open_event)
    except Exception as e:
        log.error(f"[V5_BRIDGE] Paper entry hook failed: {e}")

    # P1.1AG: Add entry quality diagnostics for paper training
    if paper_source == "training_sampler":
        _log_paper_train_quality_entry(position, signal)

    # Persist state after opening position
    _save_paper_state()

    # P1.1AT: Commit rate-cap slot ONLY after successful entry creation and persistence
    # This ensures rate-cap accounting reflects real paper training entries, not phantom attempts
    if paper_source == "training_sampler":
        try:
            from src.services.paper_training_sampler import commit_training_sampler_rate_slot
            commit_training_sampler_rate_slot(now=ts)
        except Exception as e:
            log.warning("[PAPER_TRAIN_RATE_SLOT_COMMIT_ERROR] trade_id=%s err=%s", trade_id, str(e))

    # Persist state after opening new position
    _save_paper_state()

    return {
        "status": "opened",
        "trade_id": trade_id,
        "symbol": symbol,
        "entry_price": price,
    }


_LAST_KNOWN_PRICE_MAX_AGE_S = float(os.getenv("PAPER_LAST_PRICE_MAX_AGE_S", "120"))


_LAST_TIMEOUT_CHECK = 0.0  # V10.16: Track last timeout check for periodic evaluation


def check_and_close_timeout_positions(now: Optional[float] = None) -> List[dict]:
    """P1.1AA+V3.1+V10.16: Scan all open positions and close those that exceed effective hold time.

    Runs independently of price updates so timeout closes happen even when a symbol
    stops receiving price ticks. Called periodically (every 5-10s) to ensure timeouts
    don't get stuck when prices stop flowing for a symbol.

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
        # Check only in-memory positions to avoid race condition with disk stale state
        # update_paper_positions() already handles TP/SL closes before this function is called
        all_positions = dict(_POSITIONS)

        for trade_id, pos in list(all_positions.items()):
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
            for pos in all_positions.values():
                entry_ts = _safe_float(pos.get("entry_ts") or pos.get("created_at"), 0.0)
                if entry_ts > 0:
                    remaining_s = max(0.0, _effective_paper_hold_s(pos) - (now - entry_ts))
                    if next_expiry_s is None or remaining_s < next_expiry_s:
                        next_expiry_s = remaining_s
        log.info(
            "[PAPER_TIMEOUT_SCAN] open=%d expired=%d alive=%d next_expiry_s=%.1f",
            len(all_positions),
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
                "hold_s": age_s,  # V10.48: Add hold_s field for dashboard (was missing)
                "gross_pnl_pct": 0.0,
                "net_pnl_pct": 0.0,
                "outcome": "FLAT",
                "unit_pnl": 0.0,
                "weighted_pnl": 0.0,
                "learning_skipped": True,
            }

            # P1.1AP-G: Emit [PAPER_EXIT] for observability (before quality exit log)
            canonical_bucket = pos.get("bucket") or pos.get("training_bucket") or pos.get("explore_bucket") or "A_STRICT_TAKE"
            log.warning(
                "[PAPER_EXIT] trade_id=%s symbol=%s reason=TIMEOUT_NO_PRICE entry=%.8f exit=%.8f net_pnl_pct=%.4f outcome=%s hold_s=%d bucket=%s training_bucket=%s",
                trade_id,
                symbol,
                pos.get("entry_price", 0.0),
                0.0,  # exit_price
                0.0,  # net_pnl_pct for TIMEOUT_NO_PRICE
                "FLAT",
                int(age_s),
                canonical_bucket,
                pos.get("training_bucket", ""),
            )

            # P1.1AJ: Emit quality exit for TIMEOUT_NO_PRICE (idempotent, all training positions)
            _log_quality_exit_once(closed_trade, pos, path="timeout_no_price")

            # P0.2 regression fix (audit review 2026-07-16): do NOT feed
            # TIMEOUT_NO_PRICE into canonical learning. These are quarantined
            # FLAT non-trades (learning_skipped=True, no real fill price); the
            # eligibility gate rejects them as "timeout_no_price_invalid" and the
            # qualification path excludes them. Before P0.2, _learning_instance was
            # a throwaway object so this call was harmless; now it is the get_learner()
            # singleton, so recording here would inflate lifetime_n / rolling windows
            # with FLAT non-trades (worst during WS slow-consumer bursts). Skip it.
            if _learning_instance and not closed_trade.get("learning_skipped") \
                    and closed_trade.get("exit_reason") != "TIMEOUT_NO_PRICE":
                try:
                    # record_close expects the full closed_trade dict
                    _learning_instance.record_close(closed_trade)
                    log.debug(f"[LEARNING_RECORD_CLOSE] trade_id={trade_id} symbol={symbol} reason={closed_trade.get('exit_reason')}")
                except Exception as e:
                    log.warning(f"[LEARNING_RECORD_CLOSE_ERROR] trade_id={trade_id} err={str(e)[:100]}")
            elif _learning_instance:
                log.debug(f"[LEARNING_RECORD_CLOSE_SKIP] trade_id={trade_id} reason=TIMEOUT_NO_PRICE quarantined (not canonical-learned)")
            else:
                log.error(f"[LEARNING_NOT_WIRED_TIMEOUT_PATH] _learning_instance is None for {trade_id}! Learning disabled.")

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

    # V10.18 DEBUG: Log call frequency
    if not hasattr(update_paper_positions, '_call_count'):
        update_paper_positions._call_count = 0
        update_paper_positions._last_log = ts
    update_paper_positions._call_count += 1
    if ts - update_paper_positions._last_log >= 10:
        log.info(f"[UPDATE_PAPER_DEBUG] Called {update_paper_positions._call_count}x in last 10s, prices={len(symbol_prices)}")
        update_paper_positions._call_count = 0
        update_paper_positions._last_log = ts

    with _POSITION_LOCK:
        # V10.18 FIX: Load orphaned positions from JSON if _POSITIONS is empty
        # This handles bot restarts where positions persist in JSON but not in memory
        if not _POSITIONS and _STATE_FILE and os.path.exists(_STATE_FILE):
            try:
                with open(_STATE_FILE, 'r') as f:
                    orphaned = json.load(f)
                    for pos_id, pos_data in orphaned.items():
                        _POSITIONS[pos_id] = pos_data
                    log.info(f"[V10.18_ORPHAN_LOAD] Loaded {len(orphaned)} positions from JSON")
            except Exception as e:
                log.warning(f"[V10.18_ORPHAN_LOAD_ERROR] {e}")

        # CYCLE#15 FIX: Sync TP/SL bands on every tick with current env override
        # V10.27 CYCLE 24 FIX: Shrink to 40/30 bps (0.4%/0.3%) — reachable in 600s hold window
        # Commit c4b03ba: "Shrink TP/SL floors to fit 180s hold window (0.4%/0.3%)"
        # CYCLE 28 FIX (blocker #1): Reuse each position's ATR-scaled entry band instead
        # of recomputing from the global env-var. Recomputing here clobbered the
        # entry-time ATR scaling on every tick (reviewer blocker). Legacy positions
        # without a stored band fall back to the env default so behavior is preserved.
        # REMOVED: CYCLE#15_SYNC caused revert of calibrated TP/SL to uncalibrated env values every tick
        # TP/SL are correctly set at entry by calibrate_paper_training_geometry() and should not be mutated
        # This sync was overwriting calibrated values with raw env vars, making TP unreachable

        positions_to_check = list(_POSITIONS.items())

    for trade_id, pos in positions_to_check:
        symbol = pos["symbol"]
        # Use current price if available, otherwise fall back to last known price
        # CYCLE#11 FIX: learning_event._last_prices stores (price, prev) TUPLES,
        # so get_metrics()["last_prices"][sym] is a tuple, not a scalar. Unwrap
        # element [0] before use — otherwise `current_price <= 0` raised TypeError,
        # aborting update_paper_positions every tick → on-tick TP/SL never ran → 100% TIMEOUT.
        _raw_price = symbol_prices.get(symbol)
        if isinstance(_raw_price, (tuple, list)):
            _raw_price = _raw_price[0] if _raw_price else None
        current_price = _safe_float(_raw_price, 0.0) or _safe_float(pos.get("last_price"), 0.0)

        if not current_price or current_price <= 0:
            log.debug(f"[PRICE_SKIP] {symbol} current_price={current_price} raw={_raw_price} symbol_prices.has={symbol in symbol_prices}")
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

        # V10.19 FIX: Use timeout_s directly for timeout decisions
        # timeout_s respects PAPER_MAX_POSITION_AGE_S env var (600s)
        # max_hold_s is legacy training cap and should NOT control timeout
        timeout_s = pos.get("timeout_s", _MAX_AGE_S)

        # V10.46 CRITICAL FIX: Validate TP/SL prices before evaluation
        # Blocks cases where pos["tp"]/pos["sl"] are None/0/invalid (would always evaluate to False)
        exit_reason = None
        if pos.get("tp") and pos["tp"] > 0 and pos.get("sl") and pos["sl"] > 0:
            # P1.1AI: Side-aware TP/SL check (TP/SL prices valid)
            if side == "BUY":
                tp_hit = current_price >= pos["tp"]
                sl_hit = current_price <= pos["sl"]
                if _DEBUG_TP_SL_EVAL:
                    log.warning(f"[TP_SL_EVAL_BUY] {symbol} curr={current_price:.8f} >= tp={pos['tp']:.8f}? {tp_hit} | curr <= sl={pos['sl']:.8f}? {sl_hit}")
            else:  # SELL
                tp_hit = current_price <= pos["tp"]
                sl_hit = current_price >= pos["sl"]
                if _DEBUG_TP_SL_EVAL:
                    log.warning(f"[TP_SL_EVAL_SELL] {symbol} curr={current_price:.8f} <= tp={pos['tp']:.8f}? {tp_hit} | curr >= sl={pos['sl']:.8f}? {sl_hit}")

            if tp_hit or sl_hit:
                log.info(f"[TP_SL_HIT] {symbol} side={side} tp_hit={tp_hit} sl_hit={sl_hit}")

            if tp_hit:
                exit_reason = "TP"
            elif sl_hit:
                exit_reason = "SL"
        else:
            # TP/SL prices invalid/missing - log and skip to timeout
            log.warning(f"[TP_SL_INVALID] {symbol} tp={pos.get('tp', 'MISSING')} sl={pos.get('sl', 'MISSING')} → skip evaluation, timeout only")

        if not exit_reason and age_s >= timeout_s:
            exit_reason = "TIMEOUT"
            log.warning(f"[TIMEOUT_EVAL] {symbol} age={age_s:.0f}s >= timeout={timeout_s:.0f}s, closing")

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


def _is_d_neg_control_trade(trade: dict) -> bool:
    """P1.1AP-I: Check if trade is D_NEG_EV_CONTROL (diagnostic control bucket, not canonical learning)."""
    bucket = trade.get("bucket")
    training_bucket = trade.get("training_bucket")
    return bucket == "D_NEG_EV_CONTROL" or training_bucket == "D_NEG_EV_CONTROL"


def _is_eligible_canonical_paper_learning_trade(pos: dict, pnl_data: dict, closed_trade: dict) -> tuple[bool, str]:
    """P1.1AP-N1: Authoritative predicate for canonical + adaptive learning eligibility.

    Returns (eligible: bool, reason: str) where reason is empty string if eligible,
    or diagnostic reason if ineligible.
    """
    # D_NEG must never mutate canonical/rolling/adaptive metrics
    if _is_d_neg_control_trade(closed_trade):
        return False, "d_neg_control_shadow_excluded"

    # Quarantined trades excluded
    if closed_trade.get("quarantined"):
        return False, "position_quarantined"

    # Invalid/stale/no-price outcomes excluded
    if closed_trade.get("exit_reason") == "TIMEOUT_NO_PRICE":
        return False, "timeout_no_price_invalid"

    # Shadow-only trades excluded
    if closed_trade.get("learning_shadow_skip") or closed_trade.get("shadow_only"):
        return False, "shadow_only_excluded"

    # All checks passed
    return True, ""


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

    # P1.1AP-I: Skip canonical learning for D_NEG_EV_CONTROL (diagnostic control bucket)
    # but log explicit skip and continue with bucket metrics
    if _is_d_neg_control_trade(canon):
        # P1.1AP-I2: Extract trade_id with fallback chain to avoid UNKNOWN in logs
        trade_id = (
            canon.get("trade_id")
            or canon.get("id")
            or pos.get("trade_id")
            or pos.get("id")
            or pos.get("paper_trade_id")
            or pnl_data.get("trade_id")
            or pnl_data.get("id")
            or "UNKNOWN"
        )

        log.warning(
            "[PAPER_LEARNING_SHADOW_SKIP] trade_id=%s symbol=%s bucket=%s training_bucket=%s outcome=%s net_pnl_pct=%.4f reason=%s",
            trade_id,
            canon["symbol"],
            canon["bucket"],
            canon.get("training_bucket", "UNKNOWN"),
            canon["outcome"],
            canon["net_pnl_pct"],
            "d_neg_ev_control_shadow_only",
        )

        # P1.1AP-I2: Propagate shadow-only flags back to original dicts for downstream detection
        for target in (pos, pnl_data):
            target["trade_id"] = trade_id
            target["learning_shadow_only"] = True
            target["learning_skipped"] = True
            target["learning_skip_reason"] = "d_neg_ev_control_shadow_only"

        canon["trade_id"] = trade_id
        canon["learning_shadow_only"] = True
        canon["learning_skipped"] = True
        canon["learning_skip_reason"] = "d_neg_ev_control_shadow_only"
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
        record_training_closed(
            bucket=canon["bucket"],
            outcome=canon["outcome"],
            net_pnl_pct=canon.get("net_pnl_pct", 0.0),
            symbol=canon.get("symbol", ""),
            regime=canon.get("regime", ""),
            side=canon.get("side", "")
        )
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


def _record_adaptive_learning_close(closed_trade: dict, pos: dict, pnl_data: dict) -> None:
    """P1.1AP-N: Record canonical paper trade close for adaptive learning.

    Updates rolling metrics (20/50/100), adapts policy weights, and gates REAL_READY.
    Never raises; logs errors and continues.

    Args:
        closed_trade: Complete closed trade dict from close_paper_position
        pos: Original position dict
        pnl_data: PnL breakdown dict
    """
    try:
        from src.services.paper_adaptive_learning import get_learner

        # Calculate MFE/MAE from tracked extremes
        side = pos.get("side", "BUY")
        entry_price = _safe_float(pos.get("entry_price"), 0.0)
        max_seen = _safe_float(pos.get("max_seen"), entry_price)
        min_seen = _safe_float(pos.get("min_seen"), entry_price)

        if side == "BUY":
            mfe_pct = ((max_seen - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0
            mae_pct = ((min_seen - entry_price) / entry_price * 100.0) if entry_price > 0 else 0.0
        else:  # SELL
            mfe_pct = ((entry_price - min_seen) / entry_price * 100.0) if entry_price > 0 else 0.0
            mae_pct = ((entry_price - max_seen) / entry_price * 100.0) if entry_price > 0 else 0.0

        # Build trade dict for adaptive learning
        trade_data = {
            "trade_id": closed_trade.get("trade_id", ""),
            "symbol": closed_trade.get("symbol", "UNKNOWN"),
            "regime": closed_trade.get("regime", "UNKNOWN"),
            "side": closed_trade.get("side", "BUY"),
            "net_pnl_pct": _safe_float(closed_trade.get("net_pnl_pct"), 0.0),
            "outcome": closed_trade.get("outcome", "FLAT"),
            "learning_source": closed_trade.get("learning_source", "paper_training_sampler"),
            "mfe_pct": mfe_pct,
            "mae_pct": mae_pct,
            "exit_reason": closed_trade.get("exit_reason", "UNKNOWN"),
            "training_bucket": pos.get("training_bucket", ""),
        }

        learner = get_learner()
        learner.record_close(trade_data)

    except Exception as e:
        log.warning(
            "[PAPER_ADAPTIVE_LEARNING_RECORD_ERROR] trade_id=%s symbol=%s err=%s",
            closed_trade.get("trade_id", "UNKNOWN"),
            closed_trade.get("symbol", "UNKNOWN"),
            str(e),
        )


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

    # P0 FIX #2: Dedup check FIRST (before any processing)
    # Must check BEFORE accessing position to fail fast on duplicate close attempts
    with _CLOSED_TRADES_LOCK:
        if position_id in _CLOSED_TRADES_THIS_SESSION:
            log.debug(f"[PAPER_CLOSE_DEDUPE] trade_id={position_id} already processed, skipping")
            return None
        # Mark as being processed (added back to set after position read succeeds)

    # P0 FIX #1: Do NOT pop position yet - read-only access first
    # Position removal must happen AFTER all processing succeeds to prevent loss on exception
    with _POSITION_LOCK:
        if position_id not in _POSITIONS:
            return None
        pos = _POSITIONS[position_id]  # Read-only, do not pop yet

    # V10.26 FIX: Mark as closed IMMEDIATELY after position read to prevent race conditions
    # This prevents concurrent close_paper_position calls from processing same position twice
    with _CLOSED_TRADES_LOCK:
        _CLOSED_TRADES_THIS_SESSION.add(position_id)

    log.info(
        "[PAPER_CLOSE_PATH] trade_id=%s symbol=%s reason=%s",
        position_id,
        pos["symbol"],
        reason,
    )

    # P1.1AP-G: Ensure all required fields for PnL calculation exist
    # Normalize legacy positions that may be missing these fields
    side = pos.get("side") or pos.get("action") or "BUY"
    entry_price = _safe_float(pos.get("entry_price") or pos.get("entry"), 0.0)
    size_usd = _safe_float(pos.get("size_usd") or pos.get("final_size_usd"), 10.0)

    # Calculate PnL
    pnl_data = _calculate_pnl(
        side=side,
        entry_price=entry_price,
        exit_price=price,
        size_usd=size_usd,
    )

    duration_s = ts - _safe_float(pos.get("entry_ts"), ts)

    # V10.22: Calculate net PnL in USD for caching
    net_pnl_usd = (pnl_data["net_pnl_pct"] / 100.0) * size_usd

    closed_trade = {
        **pos,
        "trade_id": position_id,  # V10.15l: Explicit trade ID for logging
        "side": side,  # C8 (dashboard_audit 2026-07-14): normalized direction for persistence
        "exit_price": price,
        "exit_ts": ts,
        "exit_reason": reason,
        "duration_s": duration_s,
        "hold_s": duration_s,  # V10.48: Add hold_s field for dashboard (was missing, causing 0 display)
        "pnl_pct": pnl_data["net_pnl_pct"],  # C8: alias so save_closed_trade persists side-aware net pnl_pct (column was NULL)
        "gross_pnl_pct": pnl_data["gross_pnl_pct"],
        "fee_pct": pnl_data["fee_pct"],
        "slippage_pct": pnl_data["slippage_pct"],
        "net_pnl_pct": pnl_data["net_pnl_pct"],
        "net_pnl_usd": net_pnl_usd,  # V10.22: For cache/dashboard
        "pnl_usd": net_pnl_usd,      # V10.22: Alias for compatibility
        "outcome": pnl_data["outcome"],
        "unit_pnl": net_pnl_usd,
        "weighted_pnl": net_pnl_usd,
        "win": 1 if net_pnl_usd > 0 else 0,  # V10.22: For cache
    }

    # P1.1AP-E: Stale position quarantine — check BEFORE all quality/econ/learning logs
    is_stale, stale_reason = _is_stale_paper_position(pnl_data, pos["entry_price"], price, pos)
    if is_stale:
        log.warning(
            "[PAPER_POSITION_QUARANTINED] trade_id=%s symbol=%s side=%s entry=%.8f exit=%.8f net_pnl_pct=%.4f reason=%s",
            position_id,
            pos["symbol"],
            pos["side"],
            pos["entry_price"],
            price,
            pnl_data["net_pnl_pct"],
            stale_reason,
        )
        # Mark trade as quarantined so downstream handlers (e.g., _save_paper_trade_closed) skip learning updates
        closed_trade["quarantined"] = True
        # Skip all quality/econ/learning logs and return early
        _save_paper_state()
        return closed_trade

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

    # V10.15l: SQLite logging delegated to learning_integration.on_paper_trade_closed()
    # All trade data is persisted via LocalLearningStorage (uses network share if available)

    # V5 Legacy Bridge: Record paper close (Phase 3 hook) — BEFORE deduplication
    close_event = None  # Initialize to prevent undefined variable in except block
    try:
        v5_bridge = _get_v5_bridge()
        if v5_bridge:
            from src.services.v5_legacy_bridge.event_models import LegacyPaperCloseEvent
            size_usd = _safe_float(pos.get("size_usd") or pos.get("final_size_usd"), 10.0)
            net_pnl = (pnl_data["net_pnl_pct"] / 100.0) * size_usd
            close_event = LegacyPaperCloseEvent(
                trade_id=position_id,
                symbol=pos["symbol"],
                side=pos.get("side", "BUY"),
                exit_ts=ts,
                exit_price=price,
                exit_reason=reason,
                gross_pnl=(pnl_data.get("gross_pnl_pct", 0.0) / 100.0) * size_usd,
                fees=(pnl_data.get("fee_pct", 0.0) / 100.0) * size_usd,
                spread=(pnl_data.get("slippage_pct", 0.0) / 100.0) * size_usd,
                net_pnl=net_pnl,
                net_pnl_pct=pnl_data.get("net_pnl_pct", 0.0),
                duration_seconds=int(duration_s),
                learning_eligible=not pos.get("quarantined", False),
                readiness_eligible=False,  # Will be determined by learning bridge
                real_orders_allowed=False,
                metadata={"paper_source": pos.get("paper_source", "unknown")},
            )
            v5_bridge.record_close(close_event)
    except Exception as e:
        # P0 FIX #3: On V5 bridge failure, enqueue for retry instead of silently continuing
        log.error(f"[V5_BRIDGE_CLOSE_FAILED] trade_id={position_id} enqueuing to outbox: {e}")
        try:
            from src.services.v5_legacy_bridge.outbox import get_durable_outbox
            outbox = get_durable_outbox()
            if outbox:
                outbox.enqueue(
                    "paper_close",
                    close_event.to_dict() if hasattr(close_event, 'to_dict') else {
                        "trade_id": position_id,
                        "symbol": pos.get("symbol", "N/A"),
                        "exit_reason": reason,
                        "exit_price": price,
                        "exit_ts": ts,
                        "net_pnl_pct": pnl_data.get("net_pnl_pct", 0.0),
                    },
                    idempotency_key=position_id,
                )
                log.info(f"[V5_BRIDGE_CLOSE_ENQUEUED] trade_id={position_id} for retry")
        except Exception as outbox_e:
            log.error(f"[V5_BRIDGE_OUTBOX_ENQUEUE_FAILED] trade_id={position_id} error={outbox_e}")

    # P1.1AJ: Log exit quality (idempotent, all training positions)
    _log_quality_exit_once(closed_trade, pos, path="close_paper_position")

    # V10.26: Dedup marking moved to line 2268 (immediately after position read)
    # REMOVED duplicate add from here to prevent race conditions

    # P1.1L Phase 6: Call learning update for training trades
    # P1.1Q: Use safe adapter with canonical normalization
    # FIX(2026-07-15): P0.3C routing rewrites paper_source -> "paper_evidence_collection"
    # for all gated (cold-state) admits, which orphaned these hooks. Widen to both labels.
    # NOTE: strict-EV "normal_rde_take" / "paper_adaptive_recovery" closes are still NOT
    # covered here — revisit when segments graduate to strict EV (see review follow-up).
    if pos.get("paper_source") in ("training_sampler", "paper_evidence_collection"):
        _safe_learning_update_for_paper_trade(pos, pnl_data)

    # P1.1AP-N: Record canonical close for adaptive learning (rolling metrics + policy adaptation)
    # P1.1AP-N1: Use authoritative eligibility predicate to exclude D_NEG and other ineligible rows
    if pos.get("paper_source") in ("training_sampler", "paper_evidence_collection"):
        eligible, skip_reason = _is_eligible_canonical_paper_learning_trade(pos, pnl_data, closed_trade)
        if eligible:
            _record_adaptive_learning_close(closed_trade, pos, pnl_data)
        elif skip_reason == "d_neg_control_shadow_excluded":
            # Debug log only for D_NEG (non-spammy, control diagnostics allowed)
            log.debug(
                "[PAPER_ADAPTIVE_LEARNING_SKIP] trade_id=%s bucket=%s reason=%s",
                closed_trade.get("trade_id", ""),
                closed_trade.get("bucket", "UNKNOWN"),
                skip_reason,
            )

    # P1.1Q: Update bucket metrics with safe adapter
    _safe_bucket_metrics_update_for_paper_trade(closed_trade)

    # Audit PR6 (P0.4) Phase-A shadow: log-only comparison of the canonical
    # pipeline's eligibility decision vs this path. Gated by
    # PAPER_CANONICAL_PIPELINE=shadow (default off) — executes NO side effects,
    # never disturbs the live close. Cheap getenv short-circuits when off.
    if os.getenv("PAPER_CANONICAL_PIPELINE", "off").strip().lower() == "shadow":
        try:
            from src.services.paper_close_pipeline import run_shadow
            if pos.get("paper_source") in ("training_sampler", "paper_evidence_collection"):
                _old_elig, _old_reason = _is_eligible_canonical_paper_learning_trade(
                    pos, pnl_data, closed_trade)
            else:
                _old_elig, _old_reason = False, "paper_source_not_admitted"
            run_shadow(closed_trade, _old_elig, _old_reason)
        except Exception:
            pass  # shadow must never affect the live path

    # P1.1AG: Add to closed trades buffer for summary aggregation
    with _PAPER_CLOSED_TRADES_LOCK:
        _PAPER_CLOSED_TRADES_BUFFER.append(closed_trade)

    # P0.4 (audit 2026-07-16): the former `if on_paper_trade_closed:` local-learning
    # sink was DEAD CODE (import always failed — see module header) and has been
    # removed. The authoritative cache.sqlite sink is
    # local_persistent_cache.save_closed_trade(...) (called from
    # trade_executor.py:1662, deduped via INSERT OR REPLACE on trade_id). No
    # behavior change: this branch never executed.

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

    # P0 FIX #1: Remove position from active ONLY after all processing succeeds
    # This ensures position survives any exception and can be retried
    with _POSITION_LOCK:
        _POSITIONS.pop(position_id, None)

    # V10.17 FIX: Persist state after removal so JSON file reflects actual open positions
    _save_paper_state()

    # V10.27: Update canonical_state with win/loss count for persistent WR calculation
    try:
        from src.services.canonical_state import increment_trades_won, increment_trades_lost
        if net_pnl_usd >= 0.0001:
            increment_trades_won()
        else:
            increment_trades_lost()
    except Exception as e:
        log.error(f"[CANONICAL_UPDATE_ERROR] Failed to update trade counts: {e}")

    # P0.2 (audit 2026-07-16): the former second record path here
    #     _learning_instance.record_close(closed_trade)
    # double-counted every eligible close. The canonical, eligibility-gated recorder
    # is `_record_adaptive_learning_close(...)` above (which routes through the
    # get_learner() singleton and correctly excludes D_NEG control shadows). Recording
    # a second time — especially the raw, ungated closed_trade — corrupted lifetime_n /
    # rolling windows / PF / WR / expectancy, so this redundant path is removed.
    # record_close() also now dedupes by trade_id as a defense-in-depth safety net.

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


def get_open_positions():
    """Return dict of all open paper trading positions with full internal state (includes entry_ts).

    This is used by bot2/main.py for timeout and monitoring logic.
    Includes entry_ts field which is essential for position age calculations.

    Returns: dict mapping position_id -> position_dict (with entry_ts, created_at, etc.)
    """
    with _POSITION_LOCK:
        return dict(_POSITIONS)


def calibrate_paper_training_geometry(
    *,
    mode: str,
    source: str,
    training_bucket: str,
    side: str,
    entry: float,
    tp_sl: dict,
    expected_move_pct: float = 0.0,
    fee_drag_pct: float = 0.18,
) -> dict:
    """P1.1AN: Calibrate TP/SL for paper training to match realistic short-horizon window.

    Paper training positions have a 300-second max hold. Current TP (1.2%) is unreachable
    in this window due to fee drag (0.18%) and typical MFE (0.02-0.15%). This helper
    adjusts TP/SL for realistic learning signal:
    - TP floor: fee_drag + 0.03 ≈ 0.21%
    - TP target: expected_move * 0.8 (if available)
    - TP cap: 0.45% (cold-start safe limit)
    - SL range: 0.35–0.60% (suggested 0.45%)

    Only applies to: mode==paper_train AND source==training_sampler AND training_bucket==C_WEAK_EV_TRAIN

    Args:
        mode: Trading mode (paper_train, paper_live, live, real)
        source: Entry source (training_sampler, normal_rde_take, etc.)
        training_bucket: Bucket name (C_WEAK_EV_TRAIN, C_NEG_EV_PROBE, etc.)
        side: BUY or SELL
        entry: Entry price
        tp_sl: Dict from normalize_paper_tp_sl() with tp, sl, tp_pct, sl_pct, rr
        expected_move_pct: Expected move from signal (optional, in %)
        fee_drag_pct: Fee drag in % (default 0.18)

    Returns:
        dict: Original or calibrated TP/SL result. Always includes calibration metadata.
    """
    if tp_sl is None:
        return None

    # Apply calibration to both paper_train (original) and paper_live (new)
    # For paper_train: C_WEAK_EV_TRAIN bucket only
    # For paper_live: all signals (broader calibration)
    is_training = (mode == "paper_train" and source == "training_sampler" and training_bucket == "C_WEAK_EV_TRAIN")
    is_paper_live_all = (mode == "paper_live")  # Apply to all paper_live signals

    if not (is_training or is_paper_live_all):
        return tp_sl

    original_tp_pct = tp_sl.get("tp_pct", 0.0)
    original_sl_pct = tp_sl.get("sl_pct", 0.0)

    # V10.21: Calibrate TP for paper trading
    # For paper_live: respect configured PAPER_TP_ZONE_BPS, don't override with hardcoded floor
    if mode == "paper_live":
        tp_zone_bps = int(os.getenv("PAPER_TP_ZONE_BPS", "60"))  # V10.47: Reachable floor 60 bps (0.60%) — matches open_paper_position logic
        # V10.29 ROOT-CAUSE FIX: bps -> PERCENT (not fraction). Downstream computes
        # new_tp = entry * (1 + new_tp_pct/100.0), so tp_floor_pct must be a percent
        # to be consistent with the paper_train branch (floor = fee_drag+0.03 ≈ 0.21%).
        # Prior /10000.0 made 35 bps -> 0.0035, then /100 again -> 0.35 bps effective TP
        # (~0.008% in logs) => every TP exit net-negative after 36bps round-trip cost.
        # Evidence: 38/38 TP exits losses, WR 0%, P&L -$6.45 (30-min window 2026-06-22).
        tp_floor_pct = tp_zone_bps / 100.0  # e.g. 35 bps → 0.35%
        tp_cap_pct = 1.50      # Maximum 1.5% (vs 0.45% for training)
        # 2026-07-07: env-drive SL so PAPER_SL_ZONE_BPS actually takes effect for
        # paper_live positions (was hardcoded 0.80, which silently ignored the env
        # band and made the swing-horizon experiment run TP70/SL80 instead of 70/50).
        # Default 80 preserves prior behaviour when the env var is unset.
        sl_default_pct = int(os.getenv("PAPER_SL_ZONE_BPS", "80")) / 100.0
    else:  # paper_train
        tp_floor_pct = fee_drag_pct + 0.03  # ~0.21%
        tp_cap_pct = 2.50      # V10.21: Increased from 0.45% to allow 2.5% TP targets
        sl_default_pct = 2.00  # V10.21: Increased from 0.45% to match TP width

    # V10.27 SENIOR FIX: Calibrate TP/SL to ACTUAL market volatility (expected_move_pct)
    # Root cause: 80/50 bps targets unreachable in 600s flat market (price only moves 1-7 bps)
    # Solution: Shrink targets proportional to observed volatility
    if expected_move_pct > 0.15:
        # Market has real volatility - can afford wider targets
        tp_target_pct = min(expected_move_pct * 0.75, tp_cap_pct)  # 75% of observed move
    else:
        # FLAT MARKET (0-0.15% movement): Use configured floor (respect tp_floor_pct, don't hardcode)
        tp_target_pct = tp_floor_pct

    # V10.44: Ensure calibrated TP respects MIN_TP_PCT global floor
    # This prevents calibration logic from overriding the TP floor change deployed in trade_executor.py
    try:
        from src.services.trade_executor import MIN_TP_PCT
        min_tp_pct = MIN_TP_PCT * 100.0  # Convert fraction to percent
        tp_floor_pct = max(tp_floor_pct, min_tp_pct)
    except (ImportError, AttributeError):
        pass  # Fallback to configured tp_floor_pct if import fails

    # V10.27: CRITICAL - always use calibrated TP, not max(original, calibrated)
    # This allows shrinking in flat markets while keeping wide targets in volatile markets
    # Enforce final bounds
    new_tp_pct = max(tp_floor_pct, min(tp_target_pct, tp_cap_pct))

    # Compute new price levels from percentages
    if side == "BUY":
        new_tp = entry * (1.0 + new_tp_pct / 100.0)
        new_sl = entry * (1.0 - sl_default_pct / 100.0)
    else:  # SELL
        new_tp = entry * (1.0 - new_tp_pct / 100.0)
        new_sl = entry * (1.0 + sl_default_pct / 100.0)

    # Compute new RR
    new_rr = new_tp_pct / sl_default_pct if sl_default_pct > 0 else 0.0

    return {
        "tp": new_tp,
        "sl": new_sl,
        "tp_pct": new_tp_pct,
        "sl_pct": sl_default_pct,
        "rr": new_rr,
        "repaired": tp_sl.get("repaired", False),
        "repair_reason": tp_sl.get("repair_reason"),
        "calibrated": True,
        "calibration_reason": f"paper_train:{training_bucket}",
        "tp_pct_before": original_tp_pct,
        "sl_pct_before": original_sl_pct,
    }


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
        # P1.1AP-N2B: For recovery trades, use learning_source to identify origin
        learning_source = position.get("learning_source", "paper_training_sampler")
        source = "paper_adaptive_recovery" if learning_source == "paper_adaptive_recovery" else position.get("paper_source", "na")
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
        # P1.1AP-K: Skip correction if already normalized from paper_exploration
        atr = float(signal.get("atr") or 0.0)
        expected_move_src = position.get("expected_move_src", "position")

        if expected_move_src != "atr_abs_price_normalized" and expected_move_pct > 2.0 and atr > 0 and abs(expected_move_pct - atr) < 0.1:
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

        # P1.1AN: Calibration metadata
        geometry_calibrated = position.get("geometry_calibrated", False)
        tp_pct_before = position.get("tp_pct_before_calibration", tp_pct)
        sl_pct_before = position.get("sl_pct_before_calibration", sl_pct)

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
        hold_limit_s = int(position.get("max_hold_s") or _MAX_AGE_S)

        # Format score fields for logging
        score_raw_str = f"{score_raw:.3f}" if score_raw is not None else "na"
        score_final_str = f"{score_final:.3f}" if score_final is not None else "na"

        # P1.1AK: Extract bypass context fields
        cost_edge_bypassed = position.get("cost_edge_bypassed", False)
        cost_edge_bypass_reason = position.get("cost_edge_bypass_reason", "none")

        log.info(
            "[PAPER_TRAIN_QUALITY_ENTRY] trade_id=%s symbol=%s side=%s source=%s bucket=%s training_bucket=%s regime=%s ev=%.4f p=%.3f score_raw=%s score_final=%s score_missing=%s coh=%.3f expected_move_pct=%.3f expected_move_src=%s cost_edge_ok=%s cost_edge_bypassed=%s bypass_reason=%s entry=%.8f tp=%.8f sl=%.8f tp_pct=%.3f sl_pct=%.3f rr=%.3f atr=%.8f spread=%.8f hold_limit_s=%d geometry_calibrated=%s tp_pct_before=%.3f sl_pct_before=%.3f",
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
            geometry_calibrated,
            tp_pct_before,
            sl_pct_before,
        )

        # P1.1AK: Anomaly detection — cost_edge_ok=False but not bypassed
        # P1.1AP-N2B: Skip anomaly for intentional recovery samples (recovery admissions intentionally have cost_edge_ok=False)
        is_recovery = learning_source == "paper_adaptive_recovery"
        if cost_edge_ok is False and cost_edge_bypassed is False and not is_recovery:
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
                    mfe = (max_seen - entry) / entry * 100.0
                    mae = (entry - min_seen) / entry * 100.0
                else:
                    mfe = (entry - min_seen) / entry * 100.0
                    mae = (max_seen - entry) / entry * 100.0
            else:
                mfe = 0.0
                mae = 0.0

            # Near-TP for TIMEOUT positions (tp_pct stored as percent, mfe now in percent too)
            if "TIMEOUT" in t.get("exit_reason", "") and tp_pct > 0 and mfe / tp_pct >= 0.7:
                near_tp += 1
            # Near-SL for TIMEOUT positions
            if "TIMEOUT" in t.get("exit_reason", "") and sl_pct > 0 and mae / sl_pct >= 0.7:
                near_sl += 1
            # Both TP and SL touched (mfe/mae now in percent, tp_pct/sl_pct in percent)
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

        # P1.1AM: Attribution breakdown
        by_attrib = {}
        mfe_to_tp_ratios = []
        mae_to_sl_ratios = []
        bypass_n = bypass_win = cost_ok_n = cost_ok_win = 0

        for t in trades:
            entry = float(t.get("entry_price", 0))
            max_seen = float(t.get("max_seen", entry))
            min_seen = float(t.get("min_seen", entry))
            side = t.get("side", "BUY")
            tp_pct = abs(float(t.get("tp_pct_at_entry", 0)))
            sl_pct = abs(float(t.get("sl_pct_at_entry", 0)))
            gross_pnl_pct = float(t.get("gross_pnl_pct", 0))
            net_pnl_pct_t = float(t.get("net_pnl_pct", 0))
            outcome = t.get("outcome", "FLAT")
            exit_reason = t.get("exit_reason", "")
            cost_edge_bypassed = bool(t.get("cost_edge_bypassed"))
            cost_edge_ok = bool(t.get("cost_edge_ok"))
            tp_abs = float(t.get("tp", 0))
            sl_abs = float(t.get("sl", 0))

            if entry > 0:
                if side == "BUY":
                    mfe = (max_seen - entry) / entry * 100.0
                    mae = (entry - min_seen) / entry * 100.0
                    t_touched_tp = max_seen >= tp_abs if tp_abs > 0 else False
                    t_touched_sl = min_seen <= sl_abs if sl_abs > 0 else False
                else:
                    mfe = (entry - min_seen) / entry * 100.0
                    mae = (max_seen - entry) / entry * 100.0
                    t_touched_tp = min_seen <= tp_abs if tp_abs > 0 else False
                    t_touched_sl = max_seen >= sl_abs if sl_abs > 0 else False
            else:
                mfe = mae = 0.0
                t_touched_tp = t_touched_sl = False

            attr = _compute_econ_attribution(
                gross_pnl_pct, mfe, abs(mae), tp_pct, sl_pct,
                t_touched_tp, t_touched_sl, net_pnl_pct_t, cost_edge_bypassed, outcome,
                "TIMEOUT" in exit_reason
            )
            if attr not in by_attrib:
                by_attrib[attr] = {"n": 0, "win": 0, "pnl": 0.0}
            by_attrib[attr]["n"] += 1
            by_attrib[attr]["win"] += int(outcome == "WIN")
            by_attrib[attr]["pnl"] += net_pnl_pct_t

            if tp_pct > 0: mfe_to_tp_ratios.append(mfe / tp_pct)
            if sl_pct > 0: mae_to_sl_ratios.append(abs(mae) / sl_pct)

            if cost_edge_bypassed:
                bypass_n += 1
                bypass_win += int(outcome == "WIN")
            if cost_edge_ok:
                cost_ok_n += 1
                cost_ok_win += int(outcome == "WIN")

        avg_mfe_to_tp_ratio = sum(mfe_to_tp_ratios) / len(mfe_to_tp_ratios) if mfe_to_tp_ratios else 0.0
        avg_mae_to_sl_ratio = sum(mae_to_sl_ratios) / len(mae_to_sl_ratios) if mae_to_sl_ratios else 0.0
        bypass_wr = bypass_win / bypass_n if bypass_n > 0 else 0.0
        cost_ok_wr = cost_ok_win / cost_ok_n if cost_ok_n > 0 else 0.0

        by_attrib_str = ",".join(
            f"{k}:n={v['n']} wr={v['win']/v['n']:.2f} avg_pnl={v['pnl']/v['n']:.4f}"
            for k, v in sorted(by_attrib.items())
        )

        log.info(
            "[PAPER_TRAIN_ECON_SUMMARY] window_s=%.0f closed=%d timeout_rate=%.3f near_tp_timeout=%d near_sl_timeout=%d both_touch_rate=%.3f avg_tp_pct=%.4f avg_sl_pct=%.4f avg_pnl=%.4f avg_mfe_to_tp_ratio=%.3f avg_mae_to_sl_ratio=%.3f cost_edge_bypassed_n=%d cost_edge_bypassed_wr=%.2f cost_edge_ok_n=%d cost_edge_ok_wr=%.2f by_side=[%s] by_regime=[%s] by_attribution=[%s]",
            _PAPER_SUMMARY_INTERVAL,
            closed,
            timeout_rate,
            near_tp,
            near_sl,
            both_touch_rate,
            avg_tp_pct,
            avg_sl_pct,
            avg_pnl,
            avg_mfe_to_tp_ratio,
            avg_mae_to_sl_ratio,
            cost_bypassed_count,
            bypass_wr,
            cost_ok_n,
            cost_ok_wr,
            by_side_str,
            by_regime_str,
            by_attrib_str,
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


def _compute_econ_attribution(
    gross_move_pct: float,
    mfe_pct: float,
    mae_pct: float,
    tp_pct: float,
    sl_pct: float,
    touched_tp: bool,
    touched_sl: bool,
    net_pnl_pct: float,
    cost_edge_bypassed: bool,
    outcome: str,
    timeout: bool,
) -> str:
    """P1.1AM: Determine primary economic reason for paper trade outcome.

    Priority order from spec: BOTH_TOUCH → NEAR_TP/SL → COST_EDGE_LOSS → FEE_DOM →
    WRONG_DIR → TP_TOO_FAR → LOW_VOL_TIMEOUT → NORMAL_*.
    """
    mfe_to_tp = mfe_pct / tp_pct if tp_pct > 0 else 0.0
    mae_to_sl = mae_pct / sl_pct if sl_pct > 0 else 0.0

    if touched_tp and touched_sl:
        return "BOTH_TOUCH_AMBIGUOUS"
    if timeout and mfe_to_tp >= 0.7:
        return "NEAR_TP_TIMEOUT"
    if timeout and mae_to_sl >= 0.7:
        return "NEAR_SL_TIMEOUT"
    if cost_edge_bypassed and outcome == "LOSS":
        return "COST_EDGE_BYPASS_LOSS"
    if gross_move_pct > 0 and net_pnl_pct <= 0:
        return "FEE_DOMINATED_MOVE"
    if gross_move_pct < 0 and outcome == "LOSS":
        return "WRONG_DIRECTION"
    if timeout and mfe_to_tp < 0.25:
        return "TP_TOO_FAR_FOR_MFE"
    if timeout:
        return "LOW_VOL_TIMEOUT"
    if outcome == "WIN":
        return "NORMAL_WIN"
    if outcome == "LOSS":
        return "NORMAL_LOSS"
    return "FLAT_NO_SIGNAL"


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
        hold_limit_s = int(position.get("max_hold_s") or _MAX_AGE_S)

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

        # P1.1AM: Economic attribution for training bucket exits
        if training_bucket == "C_WEAK_EV_TRAIN":
            tp_pct = abs(float(position.get("tp_pct_at_entry") or 0.0))
            sl_pct = abs(float(position.get("sl_pct_at_entry") or 0.0))
            gross_pnl_pct = float(closed_trade.get("gross_pnl_pct") or 0.0)
            fee_drag_pct = (float(closed_trade.get("fee_pct") or 0.0) + float(closed_trade.get("slippage_pct") or 0.0))
            timeout = "TIMEOUT" in reason
            cost_edge_bypassed = bool(position.get("cost_edge_bypassed"))
            cost_edge_ok = bool(position.get("cost_edge_ok"))
            bypass_reason = position.get("cost_edge_bypass_reason", "none")
            mfe_to_tp_ratio = mfe_pct / tp_pct if tp_pct > 0 else 0.0
            mae_to_sl_ratio = abs(mae_pct) / sl_pct if sl_pct > 0 else 0.0
            near_tp = timeout and mfe_to_tp_ratio >= 0.7
            near_sl = timeout and mae_to_sl_ratio >= 0.7

            attribution = _compute_econ_attribution(
                gross_pnl_pct, mfe_pct, abs(mae_pct), tp_pct, sl_pct,
                touched_tp, touched_sl, net_pnl_pct, cost_edge_bypassed, outcome, timeout
            )

            log.info(
                "[PAPER_TRAIN_ECON_ATTRIB] trade_id=%s symbol=%s side=%s entry_regime=%s exit_regime=%s "
                "source=%s training_bucket=%s cost_edge_ok=%s cost_edge_bypassed=%s bypass_reason=%s "
                "entry=%.8f exit=%.8f net_pnl_pct=%.4f gross_move_pct=%.4f fee_drag_pct=%.4f "
                "mfe_pct=%.4f mae_pct=%.4f tp_pct=%.4f sl_pct=%.4f mfe_to_tp_ratio=%.3f mae_to_sl_ratio=%.3f "
                "touched_tp=%s touched_sl=%s near_tp=%s near_sl=%s hold_s=%d hold_limit_s=%d timeout=%s outcome=%s attribution=%s",
                trade_id, symbol, side, entry_regime, exit_regime,
                source, training_bucket, cost_edge_ok, cost_edge_bypassed, bypass_reason,
                entry, exit_price, net_pnl_pct, gross_pnl_pct, fee_drag_pct,
                mfe_pct, abs(mae_pct), tp_pct, sl_pct, mfe_to_tp_ratio, mae_to_sl_ratio,
                touched_tp, touched_sl, near_tp, near_sl, hold_s, hold_limit_s, timeout, outcome, attribution,
            )

        # P1.1AP-J2: Add diagnostic attribution for B_RECOVERY_READY explore bucket exits
        # Use effective bucket to handle both training_bucket and explore_bucket cases
        effective_bucket = _effective_paper_bucket(position)
        if effective_bucket == "B_RECOVERY_READY":
            tp_pct = abs(float(position.get("tp_pct_at_entry") or 0.0))
            sl_pct = abs(float(position.get("sl_pct_at_entry") or 0.0))
            gross_pnl_pct = float(closed_trade.get("gross_pnl_pct") or 0.0)
            fee_drag_pct = (float(closed_trade.get("fee_pct") or 0.0) + float(closed_trade.get("slippage_pct") or 0.0))
            timeout = "TIMEOUT" in reason
            mfe_to_tp_ratio = mfe_pct / tp_pct if tp_pct > 0 else 0.0
            mae_to_sl_ratio = abs(mae_pct) / sl_pct if sl_pct > 0 else 0.0

            log.info(
                "[PAPER_TRAIN_ECON_ATTRIB] trade_id=%s symbol=%s side=%s entry_regime=%s exit_regime=%s "
                "source=%s bucket=%s training_bucket=%s "
                "entry=%.8f exit=%.8f net_pnl_pct=%.4f gross_move_pct=%.4f fee_drag_pct=%.4f "
                "mfe_pct=%.4f mae_pct=%.4f tp_pct=%.4f sl_pct=%.4f mfe_to_tp_ratio=%.3f mae_to_sl_ratio=%.3f "
                "touched_tp=%s touched_sl=%s hold_s=%d hold_limit_s=%d timeout=%s outcome=%s",
                trade_id, symbol, side, entry_regime, exit_regime,
                source, effective_bucket, training_bucket,
                entry, exit_price, net_pnl_pct, gross_pnl_pct, fee_drag_pct,
                mfe_pct, abs(mae_pct), tp_pct, sl_pct, mfe_to_tp_ratio, mae_to_sl_ratio,
                touched_tp, touched_sl, hold_s, hold_limit_s, timeout, outcome,
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
    log.info("[INIT_PAPER_STATE_CALLED] _PAPER_STATE_INITIALIZED=%s", _PAPER_STATE_INITIALIZED)
    if _PAPER_STATE_INITIALIZED:
        return
    _PAPER_STATE_INITIALIZED = True
    try:
        log.info("[INIT_PAPER_STATE_LOADING] About to call _load_paper_state()")
        _load_paper_state()
    except Exception as e:
        log.exception("[PAPER_STATE_LOAD_ERROR] source=%s err=%s", _STATE_FILE, e)


# P0.6 FIX: Wire signal_created event to P0 gate
# Previously signals were published but no subscriber existed,
# so P0 gate was NEVER invoked and trades never opened.
def _on_signal_created(signal: dict) -> None:
    """Handle signal_created event from signal_generator."""
    if not signal or signal.get("action") == "HOLD":
        return

    symbol = signal.get("symbol", "")
    action = signal.get("action", "HOLD")

    try:
        from src.services.p0_segment_ev_gate import P0SegmentEVGate

        regime = signal.get("regime", "RANGING")
        price = signal.get("price", 0)
        ts = signal.get("ts", time.time())

        decision = P0SegmentEVGate.decide_segment_gate(
            symbol=symbol,
            side=action,
            regime=regime,
            source=signal.get("learning_source", "signal_engine"),
            tp_sl_profile=signal.get("edge", "unknown"),
            closed_trades=[]
        )

        log.info("[SIGNAL_ROUTED] %s %s %s: %s", symbol, action, regime, decision.reason)

        # Open position if: strict_ev OR NOT blocked (insufficient history = evidence_collection)
        # Blocked = quarantined, not_in_evidence_scope, or regime_quarantined
        is_blocked = ("quarantined" in decision.reason.lower() or "not_in_evidence_scope" in decision.reason.lower())

        if decision.strict_ev_allowed or not is_blocked:
            log.info("[SIGNAL_OPENING] %s %s price=%s ts=%s", symbol, action, price, ts)
            open_paper_position(
                signal=signal,
                price=price,
                ts=ts,
                reason="P0_GATE",
                extra={"p0_decision": decision.reason}
            )
            # Mark signal as handled by paper to prevent RDE double-processing
            signal["__paper_handled"] = True
            log.info("[SIGNAL_OPENED] %s %s SUCCESS", symbol, action)
    except Exception as e:
        log.exception("[SIGNAL_HANDLER_ERROR] %s %s: %s", symbol, action, e)


# Subscribe to signal_created events
subscribe_once("signal_created", _on_signal_created)

# Call startup initializer after all functions are defined
try:
    print('[BEFORE_INIT_CALL] About to call _init_paper_state_once()', flush=True)
    _init_paper_state_once()
    print('[AFTER_INIT_CALL] Successfully initialized paper state', flush=True)
except Exception as e:
    print(f'[MODULE_INIT_ERROR] Failed: {e}', flush=True)
    import traceback
    traceback.print_exc()

print('[MODULE_LOAD_COMPLETE] paper_trade_executor module fully initialized', flush=True)

# MARKER: Module loaded successfully
log.info('[MODULE_LOAD_COMPLETE] paper_trade_executor module fully initialized')
