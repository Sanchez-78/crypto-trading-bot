"""Canonical paper-close pipeline (audit PR6 / P0.4).

Today a paper close fans out to scattered, individually-guarded side effects
(adaptive learning, bucket metrics, legacy bridge, canonical_state counters,
local SQLite, Firebase) across two files. This module introduces ONE coordinated
entry point plus an immutable event and a transactional effect ledger, so a close
is persisted once and each downstream effect is tracked and retryable.

ROLLOUT IS TWO-PHASE and gated by PAPER_CANONICAL_PIPELINE (default "off"):
  * "off"          — nothing here runs in the live path (behaviour-neutral).
  * "shadow"       — Phase A: build the event, compute the eligibility/effect
                     plan, and LOG a comparison against the existing path.
                     Executes NO side effects (run_shadow).
  * "authoritative"— Phase B (NOT enabled here): persist_closed_paper_trade
                     becomes the single writer and the scattered calls are
                     removed. Left as a separate, explicitly-gated cutover after
                     runtime shadow validation.

This module does NOT change the close math — net/gross/fee/slippage/outcome all
come straight off the already-computed close (golden-locked in PR3).
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from src.core.trade_metrics_contract import TradeOutcome, classify_outcome

log = logging.getLogger(__name__)

# Bump when the eligibility/effect policy definition changes.
CLOSE_PIPELINE_POLICY_VERSION = 1

# Learning sources the CURRENT canonical path admits (paper_source gate at
# paper_trade_executor.py:2700). normal_rde_take / paper_adaptive_recovery are
# deliberately NOT admitted yet — their fill/close data contract must be verified
# before inclusion (audit 10.6), so shadow parity keeps them ineligible.
ELIGIBLE_PAPER_SOURCES = frozenset({"training_sampler", "paper_evidence_collection"})

EFFECT_TYPES = ("adaptive_learning", "bucket_metrics", "legacy_bridge", "firebase_sync")

_MODE_OFF, _MODE_SHADOW, _MODE_AUTHORITATIVE = "off", "shadow", "authoritative"


def pipeline_mode() -> str:
    m = os.getenv("PAPER_CANONICAL_PIPELINE", _MODE_OFF).strip().lower()
    return m if m in (_MODE_OFF, _MODE_SHADOW, _MODE_AUTHORITATIVE) else _MODE_OFF


# ── immutable close event ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PaperCloseEvent:
    trade_id: str
    symbol: str
    side: str
    entry_ts: float
    exit_ts: float
    entry_price: float
    exit_price: float
    exit_reason: str
    regime: str
    size_usd: float
    gross_pnl_pct: float
    fee_pct: float
    slippage_pct: float
    net_pnl_pct: float
    net_pnl_usd: float
    outcome: TradeOutcome
    learning_source: str
    training_bucket: str
    quarantined: bool
    learning_skipped: bool
    readiness_eligible: bool
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def from_closed_trade(closed_trade: Mapping[str, Any]) -> PaperCloseEvent:
    """Normalize the executor's closed_trade dict into the immutable event once.

    paper_source (the eligibility gate key) is carried in metadata because the
    canonical dataclass names only learning_source/training_bucket.
    """
    ct = closed_trade
    outcome_raw = ct.get("outcome")
    try:
        outcome = TradeOutcome(str(outcome_raw).strip().upper()) if outcome_raw else \
            classify_outcome(_f(ct.get("net_pnl_pct", ct.get("pnl_pct", 0.0))))
    except ValueError:
        outcome = classify_outcome(_f(ct.get("net_pnl_pct", ct.get("pnl_pct", 0.0))))
    paper_source = ct.get("paper_source") or ct.get("learning_source") or "unknown"
    bucket = ct.get("training_bucket") or ct.get("bucket") or "unknown"
    net_pct = _f(ct.get("net_pnl_pct", ct.get("pnl_pct", 0.0)))
    return PaperCloseEvent(
        trade_id=str(ct.get("trade_id", "")),
        symbol=str(ct.get("symbol", "")),
        side=str(ct.get("side") or ct.get("action") or "BUY").upper(),
        entry_ts=_f(ct.get("entry_ts")),
        exit_ts=_f(ct.get("exit_ts")),
        entry_price=_f(ct.get("entry_price")),
        exit_price=_f(ct.get("exit_price")),
        exit_reason=str(ct.get("exit_reason", "")),
        regime=str(ct.get("regime", "UNKNOWN")),
        size_usd=_f(ct.get("size_usd")),
        gross_pnl_pct=_f(ct.get("gross_pnl_pct")),
        fee_pct=_f(ct.get("fee_pct")),
        slippage_pct=_f(ct.get("slippage_pct")),
        net_pnl_pct=net_pct,
        net_pnl_usd=_f(ct.get("net_pnl_usd", ct.get("pnl_usd", 0.0))),
        outcome=outcome,
        learning_source=str(ct.get("learning_source", "unknown")),
        training_bucket=str(bucket),
        quarantined=bool(ct.get("quarantined", False)),
        learning_skipped=bool(ct.get("learning_skipped", False)),
        readiness_eligible=bool(ct.get("readiness_eligible", False)),
        metadata={"paper_source": str(paper_source),
                  "bucket": str(ct.get("bucket", "")),
                  "shadow_only": bool(ct.get("shadow_only") or ct.get("learning_shadow_skip"))},
    )


# ── canonical learning eligibility ────────────────────────────────────────────

@dataclass(frozen=True)
class EligibilityDecision:
    eligible: bool
    reason: str
    policy_version: int = CLOSE_PIPELINE_POLICY_VERSION


def canonical_learning_eligibility(event: PaperCloseEvent) -> EligibilityDecision:
    """Mirror the current eligibility decision, plus two safe-superset guards.

    The legacy predicate (_is_eligible_canonical_paper_learning_trade) checks
    D_NEG / quarantined / TIMEOUT_NO_PRICE / shadow_only, and the call site adds
    the paper_source gate. This reproduces all of those, and additionally
    excludes `learning_skipped` and non-positive prices (`invalid_prices`).

    Those two additions do NOT diverge on any real close reaching this point:
    `learning_skipped` is set only on the TIMEOUT_NO_PRICE branch (which never
    reaches close_paper_position), and a genuine fill always has positive prices.
    They are defense-in-depth for Phase B, where record_close's own guards are
    bypassed — so shadow-mode agreement stays ~100% and any disagreement flags
    genuinely corrupt data. Exclusions run before the positive source check so a
    bad close can never be admitted on the strength of its source.
    """
    def no(reason):
        return EligibilityDecision(False, reason)

    if event.learning_skipped:
        return no("learning_skipped")
    if event.quarantined:
        return no("position_quarantined")
    if event.exit_reason == "TIMEOUT_NO_PRICE":
        return no("timeout_no_price_invalid")
    if event.metadata.get("shadow_only"):
        return no("shadow_only_excluded")
    if event.training_bucket == "D_NEG_EV_CONTROL" or event.metadata.get("bucket") == "D_NEG_EV_CONTROL":
        return no("d_neg_control_shadow_excluded")
    # stale / corrupt close (invalid prices) — cannot learn from a non-fill
    if event.entry_price <= 0 or event.exit_price <= 0:
        return no("invalid_prices")
    paper_source = event.metadata.get("paper_source", "unknown")
    if paper_source not in ELIGIBLE_PAPER_SOURCES:
        return no(f"source_not_in_canonical_set:{paper_source}")
    return EligibilityDecision(True, "eligible")


def plan_effects(event: PaperCloseEvent) -> dict[str, bool]:
    """Which downstream effects a close would enqueue (the effect plan)."""
    elig = canonical_learning_eligibility(event)
    return {
        "adaptive_learning": elig.eligible,
        "bucket_metrics": True,     # current path updates buckets unconditionally
        "legacy_bridge": True,      # attempted whenever the bridge exists
        "firebase_sync": True,      # attempted whenever a db handle exists
    }


# ── durable persistence (Phase B mechanism; unit-tested, not yet wired live) ──

@dataclass(frozen=True)
class ClosePipelineResult:
    trade_id: str
    status: str                       # "inserted" | "noop" | "conflict" | "error"
    persisted: bool
    eligibility: EligibilityDecision
    effects: dict
    conflict: bool = False
    error: Optional[str] = None


# Immutable identity of a close: if any of these differ for the same trade_id it
# is a critical conflict, not a legitimate re-close.
_IMMUTABLE_FIELDS = ("side", "entry_ts", "exit_ts", "entry_price", "exit_price",
                     "net_pnl_pct", "outcome")


def _ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_canonical_closes (
            trade_id TEXT PRIMARY KEY,
            symbol TEXT, side TEXT,
            entry_ts REAL, exit_ts REAL, entry_price REAL, exit_price REAL,
            exit_reason TEXT, regime TEXT, size_usd REAL,
            gross_pnl_pct REAL, fee_pct REAL, slippage_pct REAL,
            net_pnl_pct REAL, net_pnl_usd REAL, outcome TEXT,
            learning_source TEXT, training_bucket TEXT,
            quarantined INTEGER, learning_skipped INTEGER,
            policy_version INTEGER, created_at REAL,
            conflict INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS paper_close_effects (
            trade_id TEXT NOT NULL,
            effect_type TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (trade_id, effect_type)
        )
    """)


def _immutable_matches(row_map, event) -> bool:
    def close(a, b):
        try:
            return abs(float(a) - float(b)) <= 1e-6
        except (TypeError, ValueError):
            return str(a) == str(b)
    return (
        str(row_map["side"]) == event.side
        and close(row_map["entry_ts"], event.entry_ts)
        and close(row_map["exit_ts"], event.exit_ts)
        and close(row_map["entry_price"], event.entry_price)
        and close(row_map["exit_price"], event.exit_price)
        and close(row_map["net_pnl_pct"], event.net_pnl_pct)
        and str(row_map["outcome"]) == event.outcome.value
    )


def persist_closed_paper_trade(event: PaperCloseEvent, db_path: str,
                               now: Optional[float] = None) -> ClosePipelineResult:
    """Idempotent, transactional canonical persistence + effect-ledger seeding.

    Contract (audit 10.3/10.4):
      * new trade_id                     -> insert close + pending effect rows
      * same trade_id, same immutable    -> no-op (already persisted)
      * same trade_id, different immutable-> critical conflict + quarantine mark
    Never raises: a locked/failed DB returns status="error" so the caller can
    retry (the close is never silently lost).
    """
    now = time.time() if now is None else now
    elig = canonical_learning_eligibility(event)
    effects = plan_effects(event)
    if not event.trade_id:
        return ClosePipelineResult(event.trade_id, "error", False, elig, effects,
                                   error="empty_trade_id")
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=5, isolation_level=None)
        _ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "SELECT side, entry_ts, exit_ts, entry_price, exit_price, net_pnl_pct, outcome "
            "FROM paper_canonical_closes WHERE trade_id=?", (event.trade_id,))
        existing = cur.fetchone()
        if existing is not None:
            row_map = dict(zip(_IMMUTABLE_FIELDS, existing))
            if _immutable_matches(row_map, event):
                conn.execute("COMMIT")
                return ClosePipelineResult(event.trade_id, "noop", True, elig, effects)
            # conflict: do NOT overwrite the original; flag it for quarantine.
            conn.execute("UPDATE paper_canonical_closes SET conflict=1 WHERE trade_id=?",
                         (event.trade_id,))
            conn.execute("COMMIT")
            log.critical("[CANONICAL_CLOSE_CONFLICT] trade_id=%s differs from persisted immutable close",
                         event.trade_id)
            return ClosePipelineResult(event.trade_id, "conflict", True, elig, effects,
                                       conflict=True, error="immutable_conflict")

        conn.execute(
            "INSERT INTO paper_canonical_closes (trade_id, symbol, side, entry_ts, exit_ts, "
            "entry_price, exit_price, exit_reason, regime, size_usd, gross_pnl_pct, fee_pct, "
            "slippage_pct, net_pnl_pct, net_pnl_usd, outcome, learning_source, training_bucket, "
            "quarantined, learning_skipped, policy_version, created_at, conflict) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (event.trade_id, event.symbol, event.side, event.entry_ts, event.exit_ts,
             event.entry_price, event.exit_price, event.exit_reason, event.regime, event.size_usd,
             event.gross_pnl_pct, event.fee_pct, event.slippage_pct, event.net_pnl_pct,
             event.net_pnl_usd, event.outcome.value, event.learning_source, event.training_bucket,
             int(event.quarantined), int(event.learning_skipped),
             CLOSE_PIPELINE_POLICY_VERSION, now))
        for effect_type, planned in effects.items():
            if planned:
                conn.execute(
                    "INSERT OR IGNORE INTO paper_close_effects "
                    "(trade_id, effect_type, status, attempts, created_at, updated_at) "
                    "VALUES (?,?,?,0,?,?)", (event.trade_id, effect_type, "pending", now, now))
        conn.execute("COMMIT")
        return ClosePipelineResult(event.trade_id, "inserted", True, elig, effects)
    except (sqlite3.Error, TypeError, ValueError, OSError) as e:
        # TypeError/ValueError/OSError guard against a bad db_path (config, not
        # data) so the "never raises" contract holds even before Phase B.
        if conn is not None:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
        # bounded structured error; the close is not lost — caller retries.
        log.warning("[CANONICAL_CLOSE_PERSIST_ERROR] trade_id=%s err=%s",
                    event.trade_id, type(e).__name__)
        return ClosePipelineResult(event.trade_id, "error", False, elig, effects,
                                   error=type(e).__name__)
    finally:
        if conn is not None:
            conn.close()


def mark_effect(db_path: str, trade_id: str, effect_type: str, status: str,
                error: Optional[str] = None, now: Optional[float] = None) -> bool:
    """Transition a ledger effect (done/failed) idempotently. Never raises."""
    now = time.time() if now is None else now
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            _ensure_schema(conn)
            conn.execute(
                "UPDATE paper_close_effects SET status=?, attempts=attempts+1, "
                "last_error=?, updated_at=? WHERE trade_id=? AND effect_type=?",
                (status, error, now, trade_id, effect_type))
            conn.commit()
            return True
        finally:
            conn.close()
    except (sqlite3.Error, TypeError, ValueError, OSError):
        return False


# ── Phase A shadow hook ───────────────────────────────────────────────────────

def run_shadow(closed_trade: Mapping[str, Any], old_eligible: bool,
               old_reason: str = "") -> Optional[EligibilityDecision]:
    """Log-only comparison of the canonical decision vs the existing path.

    Executes NO side effects. Returns the canonical decision (or None if the
    pipeline is not in shadow mode). Never raises into the caller.
    """
    if pipeline_mode() != _MODE_SHADOW:
        return None
    try:
        event = from_closed_trade(closed_trade)
        decision = canonical_learning_eligibility(event)
        agree = (decision.eligible == bool(old_eligible))
        log.info("[CANONICAL_PIPELINE_SHADOW] trade_id=%s canonical_eligible=%s "
                 "canonical_reason=%s old_eligible=%s old_reason=%s agree=%s effects=%s",
                 event.trade_id, decision.eligible, decision.reason,
                 bool(old_eligible), old_reason, agree, plan_effects(event))
        return decision
    except Exception as e:  # shadow must never disturb the live close
        log.warning("[CANONICAL_PIPELINE_SHADOW_ERROR] %s", type(e).__name__)
        return None
