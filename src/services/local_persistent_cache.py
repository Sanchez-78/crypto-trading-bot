"""
V10.22: Local-First Persistent Cache Layer

Replaces Firebase-intensive reads with local SQLite + JSON caching.
Only syncs validated learning data back to Firebase (hourly batch).

Architecture:
- All reads: local disk first → Firebase fallback
- All writes: local disk immediately + async Firebase batch sync
- Startup: hydrate from local disk + periodic Firebase resync

Result: ~95% quota reduction (1200 reads/day → 50 reads/day)
"""

import sqlite3
import json
import time
import logging
import os
from typing import Optional, List, Dict, Any
from threading import Lock

from src.core import test_sink_guard as _sink_guard
from src.core.trade_metrics_contract import (
    METRICS_CONTRACT_VERSION,
    classify_outcome,
)

_log = logging.getLogger(__name__)

# Local storage paths.
#
# This was a bare relative constant resolved against the process CWD, with no
# override. pytest runs from the repo root, so every test that closed a paper
# position wrote into the SAME cache.sqlite the dashboard reads. Phase 0
# forensics (2026-09-14) found that had contaminated 116 of 472 rows (24.6%):
# 76 with a fake 1970 clock, 35 TEST/MANUAL exits that are all wins (so they
# inflate every WR read from this file), and 3 SYM0/1/2 rows.
#
# The directory is now resolvable from an env override so a test session can
# redirect the whole sink in one place, and _assert_not_production_sink()
# below makes writing the production sink from a test run fail closed.
SINK_DIR_ENV_VAR = "CRYPTOMASTER_LEARNING_STORAGE_DIR"
# Back-compat alias: the first iteration of this fix exported this name.
STORAGE_DIR_ENV_VAR = SINK_DIR_ENV_VAR

LOCAL_CACHE_DIR = _sink_guard.resolve_dir(SINK_DIR_ENV_VAR, "local_learning_storage")
LOCAL_DB_PATH = f"{LOCAL_CACHE_DIR}/cache.sqlite"
LOCAL_STATE_DIR = f"{LOCAL_CACHE_DIR}/state"

_lock = Lock()


def _assert_not_production_sink():
    """Refuse to write the production cache from inside a test run.

    Per-test monkeypatch discipline is not sufficient on its own: several
    suites already redirect correctly and the contamination happened anyway,
    because the suites that forget are precisely the ones that cause it. This
    is the structural backstop; the rule itself lives in one shared place
    (src.core.test_sink_guard) so the four guarded sinks cannot drift apart.

    Normal production runs are unaffected: PYTEST_CURRENT_TEST is unset there.
    """
    _sink_guard.assert_not_production_sink(LOCAL_DB_PATH)


def _ensure_dirs():
    """Create local cache directories."""
    _assert_not_production_sink()
    os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)
    os.makedirs(LOCAL_STATE_DIR, exist_ok=True)

def _init_db():
    """Initialize local SQLite database schema."""
    _ensure_dirs()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=5)
    cursor = conn.cursor()

    # Closed trades (permanent record)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY,
            trade_id TEXT UNIQUE,
            symbol TEXT,
            entry_ts REAL,
            exit_ts REAL,
            entry_price REAL,
            exit_price REAL,
            pnl_usd REAL,
            pnl_pct REAL,
            win INTEGER,
            exit_reason TEXT,
            regime TEXT,
            mfe REAL,
            mae REAL,
            created_at REAL DEFAULT CURRENT_TIMESTAMP,
            synced_to_firebase INTEGER DEFAULT 0
        )
    """)

    # C8 migration (dashboard_audit 2026-07-14): legacy cache.sqlite lacks the
    # side column, so trade direction was lost at persistence time and the
    # dashboard hardcoded side='BUY' (inverting displayed pnl_pct for shorts).
    try:
        cursor.execute("ALTER TABLE closed_trades ADD COLUMN side TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists

    # PR3 migration (audit 2026-07-16): persist the canonical outcome
    # (WIN/LOSS/FLAT, ±0.05pp net deadband) and the contract version that
    # classified it, so readers use the stored outcome instead of re-deriving
    # it with a divergent pnl_usd>0 rule. Additive + idempotent; legacy rows
    # keep NULL and are classified at read time via the canonical classifier.
    # F8 migration (audit 2026-07-17): explicit-unit gross MFE/MAE excursion +
    # extreme-ordering timestamps, so an offline TP/SL counterfactual is honest
    # (the legacy `mfe`/`mae` columns have no explicit unit). Additive + idempotent.
    _f8_cols = (
        ("outcome", "outcome TEXT"),
        ("metrics_contract_version", "metrics_contract_version INTEGER"),
        ("mfe_gross_pct", "mfe_gross_pct REAL"),
        ("mae_gross_pct", "mae_gross_pct REAL"),
        ("mfe_gross_bps", "mfe_gross_bps REAL"),
        ("mae_gross_bps", "mae_gross_bps REAL"),
        ("time_to_mfe_ms", "time_to_mfe_ms INTEGER"),
        ("time_to_mae_ms", "time_to_mae_ms INTEGER"),
        ("excursion_policy_version", "excursion_policy_version INTEGER"),
    )
    for _col, _decl in _f8_cols:
        try:
            cursor.execute(f"ALTER TABLE closed_trades ADD COLUMN {_decl}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # 2026-08-18 (_workspace/39_closed_trade_attribution_write_bug.md):
    # found the deployed cache.sqlite already HAS these attribution
    # columns (bucket/source/paper_source/learning_source/etc. -- added
    # to the live DB at some earlier, untracked point, per this project's
    # well-documented history of ad-hoc schema drift), but save_closed_trade()
    # below never wrote to them -- every trade closed since at least
    # 2026-08-18 06:48 UTC lost this attribution on the way to SQLite even
    # though it was correctly present on the in-memory position at open
    # time (confirmed via the [PAPER_TRAIN_QUALITY_ENTRY] log line).
    # Declared here too (idempotent, same ADD-COLUMN-if-missing pattern as
    # the F8 migration above) so a fresh/local/test database also gets
    # them -- this fix must not assume the column already exists.
    _attribution_cols = (
        ("source", "source TEXT"),
        ("tp_sl_profile", "tp_sl_profile TEXT"),
        ("bucket", "bucket TEXT"),
        ("training_bucket", "training_bucket TEXT"),
        ("explore_bucket", "explore_bucket TEXT"),
        ("paper_source", "paper_source TEXT"),
        ("learning_source", "learning_source TEXT"),
        ("readiness_eligible", "readiness_eligible INTEGER"),
        ("real_readiness_eligible", "real_readiness_eligible INTEGER"),
        ("paper_learning_only", "paper_learning_only INTEGER"),
        ("learning_shadow_only", "learning_shadow_only INTEGER"),
        ("tags_json", "tags_json TEXT"),
    )
    for _col, _decl in _attribution_cols:
        try:
            cursor.execute(f"ALTER TABLE closed_trades ADD COLUMN {_decl}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Phase 2 canonical-admission attribution (2026-09-14). canonical_admit()
    # stamps all six of these onto the position at open time, but the schema
    # had no columns for them, so they were dropped at persistence -- the same
    # class of bug as the 2026-08-18 attribution write bug above.
    #
    # These are what make a cohort *versionable*: without code_version /
    # config_version there is no way to separate a post-fix cohort from the
    # mixed history, and no WR claim computed over the blend can be trusted.
    # Additive + idempotent, same ADD-COLUMN-if-missing pattern; legacy rows
    # keep NULL and are treated as UNQUALIFIED, never back-filled by estimate.
    _canonical_admission_cols = (
        ("code_version", "code_version TEXT"),
        ("config_version", "config_version TEXT"),
        ("segment_key", "segment_key TEXT"),
        ("admission_route", "admission_route TEXT"),
        ("admission_reason", "admission_reason TEXT"),
        ("effective_hold_s", "effective_hold_s REAL"),
    )
    for _col, _decl in _canonical_admission_cols:
        try:
            cursor.execute(f"ALTER TABLE closed_trades ADD COLUMN {_decl}")
        except sqlite3.OperationalError:
            pass  # column already exists

    # Learning metrics (cumulative)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS learning_metrics (
            id INTEGER PRIMARY KEY,
            timestamp REAL,
            total_trades INTEGER,
            wins INTEGER,
            losses INTEGER,
            profit_factor REAL,
            expectancy REAL,
            win_rate REAL,
            net_pnl REAL,
            learning_version TEXT,
            synced_to_firebase INTEGER DEFAULT 0
        )
    """)

    # Auditor state snapshot (cached from Firebase)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auditor_state_cache (
            id INTEGER PRIMARY KEY,
            data TEXT,
            timestamp REAL,
            source TEXT
        )
    """)

    # Model weights (cached)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_weights_cache (
            id INTEGER PRIMARY KEY,
            data TEXT,
            timestamp REAL,
            version TEXT
        )
    """)

    # Calibration state (for trade calibration learning)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calibration_state (
            id INTEGER PRIMARY KEY,
            data TEXT,
            timestamp REAL,
            version TEXT
        )
    """)

    conn.commit()
    conn.close()
    _log.info("[LOCAL_CACHE] SQLite initialized")

_init_db()

# ─── READ OPERATIONS (Local First) ────────────────────────────────────

def get_auditor_state() -> Dict[str, Any]:
    """Get auditor state from local cache (300s TTL), fallback to Firebase."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT data, timestamp FROM auditor_state_cache
                ORDER BY timestamp DESC LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                data, ts = row
                age = time.time() - ts
                if age < 300:  # 5 min TTL
                    _log.debug(f"[LOCAL_CACHE] auditor_state hit (age={age:.0f}s)")
                    return json.loads(data)
                else:
                    _log.debug(f"[LOCAL_CACHE] auditor_state stale (age={age:.0f}s)")
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] auditor_state read error: {e}")

    # Fallback: caller will load from Firebase if needed
    return {}

def get_closed_trades(limit: int = 100) -> List[Dict]:
    """Get recent closed trades from local disk (zero Firebase reads!)."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_id, symbol, entry_ts, exit_ts, entry_price, exit_price,
                       pnl_usd, pnl_pct, win, exit_reason, regime
                FROM closed_trades
                ORDER BY exit_ts DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            conn.close()

            trades = []
            for row in rows:
                trades.append({
                    "trade_id": row[0],
                    "symbol": row[1],
                    "entry_ts": row[2],
                    "exit_ts": row[3],
                    "entry_price": row[4],
                    "exit_price": row[5],
                    "pnl_usd": row[6],
                    "pnl_pct": row[7],
                    "win": row[8],
                    "exit_reason": row[9],
                    "regime": row[10],
                })

            _log.debug(f"[LOCAL_CACHE] closed_trades: {len(trades)} records")
            return trades
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] closed_trades read error: {e}")
            return []

def get_learning_metrics() -> Optional[Dict]:
    """Get latest learning metrics from local disk."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT total_trades, wins, losses, profit_factor, expectancy,
                       win_rate, net_pnl, timestamp, learning_version
                FROM learning_metrics
                ORDER BY timestamp DESC LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                return {
                    "total_trades": row[0],
                    "wins": row[1],
                    "losses": row[2],
                    "profit_factor": row[3],
                    "expectancy": row[4],
                    "win_rate": row[5],
                    "net_pnl": row[6],
                    "timestamp": row[7],
                    "version": row[8],
                }
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] learning_metrics read error: {e}")

    return None

# ─── WRITE OPERATIONS (Local Immediate) ────────────────────────────────

def save_closed_trade(trade: Dict[str, Any]):
    """Save closed trade to local disk immediately (syncs to Firebase later)."""
    # Guard OUTSIDE the try: a production-sink violation must propagate and
    # fail the offending test, not be swallowed by the except below (which
    # exists to keep a cache hiccup from killing a live close).
    _assert_not_production_sink()
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            # PR3: net_pnl_pct is the canonical (side-aware, cost-inclusive) value.
            net_pct = trade.get("pnl_pct") if trade.get("pnl_pct") is not None else trade.get("net_pnl_pct")
            # Prefer the outcome the executor already classified; only derive from
            # net_pct as a fallback so the stored value is always canonical.
            outcome = trade.get("outcome")
            if outcome is None and net_pct is not None:
                outcome = classify_outcome(net_pct).value
            # 2026-08-18 (_workspace/39_closed_trade_attribution_write_bug.md):
            # bucket/source/paper_source/learning_source/etc. were computed
            # correctly and present on the in-memory position at open time
            # (confirmed live via [PAPER_TRAIN_QUALITY_ENTRY]) but this
            # INSERT never wrote them -- every trade lost this attribution
            # on the way to persistent storage. `bucket` itself prefers the
            # canonical field with a training/explore fallback, matching
            # the same precedence trade_executor.py's own readers already
            # use elsewhere (`bucket or training_bucket or explore_bucket`).
            _bucket = trade.get("bucket") or trade.get("training_bucket") or trade.get("explore_bucket")

            def _bool_to_int(v):
                return None if v is None else (1 if v else 0)

            _tags = trade.get("tags")
            _tags_json = json.dumps(_tags) if _tags else None

            cursor.execute("""
                INSERT OR REPLACE INTO closed_trades
                (trade_id, symbol, side, entry_ts, exit_ts, entry_price, exit_price,
                 pnl_usd, pnl_pct, win, exit_reason, regime, mfe, mae,
                 outcome, metrics_contract_version,
                 mfe_gross_pct, mae_gross_pct, mfe_gross_bps, mae_gross_bps,
                 time_to_mfe_ms, time_to_mae_ms, excursion_policy_version,
                 source, tp_sl_profile, bucket, training_bucket, explore_bucket,
                 paper_source, learning_source, readiness_eligible,
                 real_readiness_eligible, paper_learning_only, learning_shadow_only,
                 tags_json,
                 code_version, config_version, segment_key,
                 admission_route, admission_reason, effective_hold_s,
                 synced_to_firebase)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, 0)
            """, (
                trade.get("trade_id"),
                trade.get("symbol"),
                trade.get("side") or trade.get("action") or "BUY",
                trade.get("entry_ts"),
                trade.get("exit_ts"),
                trade.get("entry_price"),
                trade.get("exit_price"),
                trade.get("pnl_usd"),
                # C8: executor emits net_pnl_pct (side-aware, cost-inclusive);
                # a bare pnl_pct key historically did not exist -> column was NULL
                net_pct,
                # NULL-preserving: `1 if trade.get("win") else 0` turned an
                # UNKNOWN outcome into a recorded loss. A VOID close (no fill
                # price) has no win/loss value, and writing 0 there is what
                # made 106 stale-feed non-events read as 106 defeats.
                (None if trade.get("win") is None else (1 if trade.get("win") else 0)),
                trade.get("exit_reason"),
                trade.get("regime"),
                trade.get("mfe"),
                trade.get("mae"),
                outcome,
                METRICS_CONTRACT_VERSION if outcome is not None else None,
                # F8: explicit-unit gross excursion + extreme-ordering timestamps
                trade.get("mfe_gross_pct"),
                trade.get("mae_gross_pct"),
                trade.get("mfe_gross_bps"),
                trade.get("mae_gross_bps"),
                trade.get("time_to_mfe_ms"),
                trade.get("time_to_mae_ms"),
                trade.get("excursion_policy_version"),
                trade.get("source"),
                trade.get("tp_sl_profile"),
                _bucket,
                trade.get("training_bucket"),
                trade.get("explore_bucket"),
                trade.get("paper_source"),
                trade.get("learning_source"),
                _bool_to_int(trade.get("readiness_eligible")),
                _bool_to_int(trade.get("real_readiness_eligible")),
                _bool_to_int(trade.get("paper_learning_only")),
                _bool_to_int(trade.get("learning_shadow_only")),
                _tags_json,
                # Phase 2 canonical-admission attribution. Written verbatim:
                # a missing value stays NULL (UNQUALIFIED) rather than being
                # defaulted to the current build, which would silently credit
                # legacy rows to a code version that never produced them.
                trade.get("code_version"),
                trade.get("config_version"),
                trade.get("segment_key"),
                trade.get("admission_route"),
                trade.get("admission_reason"),
                trade.get("effective_hold_s"),
            ))
            conn.commit()
            conn.close()
            _log.debug(f"[LOCAL_CACHE] saved trade: {trade.get('trade_id')}")
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] save_closed_trade error: {e}")

def save_learning_metrics(metrics: Dict[str, Any]):
    """Save learning metrics to local disk."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO learning_metrics
                (timestamp, total_trades, wins, losses, profit_factor, expectancy,
                 win_rate, net_pnl, learning_version, synced_to_firebase)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                time.time(),
                metrics.get("total_trades"),
                metrics.get("wins"),
                metrics.get("losses"),
                metrics.get("profit_factor"),
                metrics.get("expectancy"),
                metrics.get("win_rate"),
                metrics.get("net_pnl"),
                metrics.get("version"),
            ))
            conn.commit()
            conn.close()
            _log.debug("[LOCAL_CACHE] saved learning metrics")
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] save_learning_metrics error: {e}")

def cache_auditor_state(state: Dict[str, Any], source: str = "firebase"):
    """Cache auditor state locally (300s TTL)."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            # Keep only latest
            cursor.execute("DELETE FROM auditor_state_cache")
            cursor.execute("""
                INSERT INTO auditor_state_cache (data, timestamp, source)
                VALUES (?, ?, ?)
            """, (json.dumps(state), time.time(), source))
            conn.commit()
            conn.close()
            _log.debug(f"[LOCAL_CACHE] cached auditor_state (source={source})")
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] cache_auditor_state error: {e}")

# ─── FIREBASE SYNC (Hourly Batch) ────────────────────────────────────

def get_unsynced_trades(limit: int = 100) -> List[Dict]:
    """Get trades waiting to sync to Firebase."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT trade_id, symbol, entry_ts, exit_ts, entry_price, exit_price,
                       pnl_usd, pnl_pct, win, exit_reason, regime, mfe, mae, id
                FROM closed_trades
                WHERE synced_to_firebase = 0
                ORDER BY exit_ts DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            conn.close()

            trades = []
            for row in rows:
                trades.append({
                    "trade_id": row[0],
                    "symbol": row[1],
                    "entry_ts": row[2],
                    "exit_ts": row[3],
                    "entry_price": row[4],
                    "exit_price": row[5],
                    "pnl_usd": row[6],
                    "pnl_pct": row[7],
                    "win": row[8],
                    "exit_reason": row[9],
                    "regime": row[10],
                    "mfe": row[11],
                    "mae": row[12],
                    "_row_id": row[13],
                })

            return trades
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] get_unsynced_trades error: {e}")
            return []

def mark_trades_synced(row_ids: List[int]):
    """Mark trades as synced to Firebase."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()
            for row_id in row_ids:
                cursor.execute("""
                    UPDATE closed_trades SET synced_to_firebase = 1 WHERE id = ?
                """, (row_id,))
            conn.commit()
            conn.close()
            _log.debug(f"[LOCAL_CACHE] marked {len(row_ids)} trades as synced")
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] mark_trades_synced error: {e}")

def get_cache_health() -> Dict[str, Any]:
    """Get cache health stats."""
    with _lock:
        try:
            conn = sqlite3.connect(LOCAL_DB_PATH, timeout=2)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM closed_trades")
            total_trades = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM closed_trades WHERE synced_to_firebase = 0")
            unsynced_trades = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM learning_metrics")
            total_metrics = cursor.fetchone()[0]

            conn.close()

            return {
                "total_trades": total_trades,
                "unsynced_trades": unsynced_trades,
                "total_metrics": total_metrics,
                "db_path": LOCAL_DB_PATH,
                "db_size_mb": os.path.getsize(LOCAL_DB_PATH) / (1024*1024) if os.path.exists(LOCAL_DB_PATH) else 0,
            }
        except Exception as e:
            _log.warning(f"[LOCAL_CACHE] get_cache_health error: {e}")
            return {}

_log.info("[LOCAL_CACHE] Module initialized - local-first architecture ready")
