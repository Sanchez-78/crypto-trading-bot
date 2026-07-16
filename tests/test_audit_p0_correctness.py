"""Regression tests for the external audit P0 correctness/safety fixes (2026-07-16).

Covers four confirmed P0 defects in the PAPER bot:

  P0.1  .env must NOT override systemd env; fail-closed re-validation clamps any
        live-trading indicator back to paper-safe (this is the PAPER executor).
  P0.2  A single close must be learned exactly once (no double-count of
        lifetime_n / rolling windows), with persistent trade_id dedupe, and the
        wired learning instance must converge on the get_learner() singleton.
  P0.3  get_segment_metrics must parse the current 6-tuple rolling entries
        (not the old 4-tuple), returning correct WIN counts instead of None.
  P0.4  The dead/misleading local-learning import path is gone; the authoritative
        cache.sqlite sink (local_persistent_cache.save_closed_trade) exists.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services import paper_trade_executor as pte
from src.services import paper_adaptive_learning as pal


@pytest.fixture(autouse=True)
def _no_firebase(monkeypatch):
    """Isolate learning state from any shared Firebase mirror so per-test tmp
    state files are the only source of truth (deterministic assertions)."""
    monkeypatch.setattr(pal, "_firebase_available", False, raising=False)
    yield


def _fresh_learner(state_file):
    """A PaperAdaptiveLearning with a clean slate.

    The constructor restores persisted state (local JSON / Firebase mirror), so we
    zero the in-memory windows and dedupe ledger to make per-test assertions
    deterministic regardless of the host machine's learning history.
    """
    learner = pal.PaperAdaptiveLearning(state_file=str(state_file))
    learner.rolling20.clear()
    learner.rolling50.clear()
    learner.rolling100.clear()
    learner.lifetime_n = 0
    learner._recorded_trade_ids.clear()
    learner._recorded_trade_ids_set.clear()
    return learner


def _trade(trade_id, outcome="WIN", net_pnl_pct=0.20, symbol="BTCUSDT",
           regime="RANGING", side="BUY"):
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "regime": regime,
        "side": side,
        "net_pnl_pct": net_pnl_pct,
        "outcome": outcome,
        "learning_source": "paper_evidence_collection",
        "training_bucket": "C_WEAK_EV_TRAIN",
        "mfe_pct": 0.3,
        "mae_pct": -0.1,
    }


# --------------------------------------------------------------------------- #
# P0.1 — .env must not override systemd env; fail-closed paper-safe clamp
# --------------------------------------------------------------------------- #

def test_p0_1_truthy_env_helper():
    for v in ("1", "true", "TRUE", "Yes", "on", "t", "y"):
        assert pte._is_truthy_env(v) is True, v
    for v in (None, "", "0", "false", "no", "off", "paper"):
        assert pte._is_truthy_env(v) is False, v


def test_p0_1_live_flag_clamped_to_paper_safe(monkeypatch):
    """A live indicator arriving via env (e.g. leaked from .env) must be clamped."""
    monkeypatch.setenv("TRADING_MODE", "live_real")
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "1")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", "true")

    # Must NOT raise (crashing the paper loop is worse than clamping).
    pte._enforce_paper_safe_mode()

    import os
    assert os.environ["TRADING_MODE"] == "paper_live"  # valid TradingMode, not the invalid "paper"
    assert os.environ["ENABLE_REAL_ORDERS"] == "0"
    assert os.environ["LIVE_TRADING_CONFIRMED"] == "0"


def test_p0_1_paper_env_left_untouched(monkeypatch):
    """When no live indicator is present, enforcement must not mutate the env."""
    monkeypatch.setenv("TRADING_MODE", "paper_live")
    monkeypatch.delenv("ENABLE_REAL_ORDERS", raising=False)
    monkeypatch.delenv("LIVE_TRADING_CONFIRMED", raising=False)

    pte._enforce_paper_safe_mode()

    import os
    assert os.environ["TRADING_MODE"] == "paper_live"
    # enforcement only writes when clamping, so these stay absent
    assert "ENABLE_REAL_ORDERS" not in os.environ
    assert "LIVE_TRADING_CONFIRMED" not in os.environ


def test_p0_1_dotenv_loaded_non_overriding():
    """The module must load .env with override=False (systemd env is source of truth)."""
    src = Path(pte.__file__).read_text()
    assert "load_dotenv(override=False)" in src
    assert "load_dotenv(override=True)" not in src


# --------------------------------------------------------------------------- #
# P0.2 — single close learned exactly once + persistent dedupe + singleton
# --------------------------------------------------------------------------- #

def test_p0_2_single_close_records_lifetime_n_once(tmp_path):
    learner = _fresh_learner(tmp_path / "state.json")

    learner.record_close(_trade("T1"))
    assert learner.lifetime_n == 1
    assert len(learner.rolling100) == 1


def test_p0_2_repeated_trade_id_is_deduped(tmp_path):
    learner = _fresh_learner(tmp_path / "state.json")

    learner.record_close(_trade("DUP"))
    n_after_first = learner.lifetime_n
    len_after_first = len(learner.rolling100)

    # Same trade_id again — must be skipped (double-learning guard).
    learner.record_close(_trade("DUP"))
    assert learner.lifetime_n == n_after_first
    assert len(learner.rolling100) == len_after_first

    # A distinct trade_id still records.
    learner.record_close(_trade("OTHER"))
    assert learner.lifetime_n == n_after_first + 1


def test_p0_2_dedupe_persists_across_restart(tmp_path):
    state = str(tmp_path / "state.json")
    learner = _fresh_learner(state)
    learner.record_close(_trade("PERSIST"))
    n = learner.lifetime_n

    # New instance loads persisted ledger; the same trade_id must not re-learn.
    reloaded = pal.PaperAdaptiveLearning(state_file=state)
    assert "PERSIST" in reloaded._recorded_trade_ids_set
    reloaded.record_close(_trade("PERSIST"))
    assert reloaded.lifetime_n == n


def test_p0_2_empty_trade_id_not_deduped(tmp_path):
    """Empty/missing trade_ids have no key to dedupe on and must always record."""
    learner = _fresh_learner(tmp_path / "state.json")
    learner.record_close(_trade(""))
    learner.record_close(_trade(""))
    assert learner.lifetime_n == 2


def test_p0_2_set_learning_instance_binds_to_singleton(tmp_path, monkeypatch):
    """The executor must ignore a distinct instance and use the get_learner() singleton."""
    singleton = pal.PaperAdaptiveLearning(state_file=str(tmp_path / "singleton.json"))
    monkeypatch.setattr(pal, "_learner", singleton, raising=False)

    distinct = pal.PaperAdaptiveLearning(state_file=str(tmp_path / "distinct.json"))
    assert distinct is not singleton

    pte.set_learning_instance(distinct)
    assert pte._learning_instance is singleton
    assert pte._learning_instance is pal.get_learner()


# --------------------------------------------------------------------------- #
# P0.3 — get_segment_metrics must handle 6-tuple rolling entries
# --------------------------------------------------------------------------- #

def test_p0_3_segment_metrics_counts_wins_for_6tuples(tmp_path, monkeypatch):
    import time
    learner = _fresh_learner(tmp_path / "seg.json")
    monkeypatch.setattr(pal, "_learner", learner, raising=False)

    seg = "ETHUSDT:RANGING:BUY"
    ts = time.time()
    # 6-tuples: (net_pnl_pct, outcome, segment_key, ts, learning_source, admission_bucket)
    entries = [
        (0.30, "WIN", seg, ts, "paper_evidence_collection", "C_WEAK_EV_TRAIN"),
        (0.25, "WIN", seg, ts, "paper_evidence_collection", "C_WEAK_EV_TRAIN"),
        (-0.20, "LOSS", seg, ts, "paper_evidence_collection", "C_WEAK_EV_TRAIN"),
    ]
    for e in entries:
        learner.rolling100.append(e)

    metrics = pal.get_segment_metrics("ETHUSDT", "RANGING", "BUY")
    assert metrics is not None, "6-tuple unpack regression: must not return None"
    assert metrics["n"] == 3
    # PF = (0.30 + 0.25) / 0.20 = 2.75
    assert metrics["pf"] == pytest.approx(0.55 / 0.20)
    # expectancy = (0.30 + 0.25 - 0.20) / 3
    assert metrics["expectancy"] == pytest.approx(0.35 / 3)


def test_p0_3_segment_metrics_via_record_close(tmp_path, monkeypatch):
    """End-to-end: record_close writes 6-tuples; segment metrics must read them."""
    learner = _fresh_learner(tmp_path / "seg2.json")
    monkeypatch.setattr(pal, "_learner", learner, raising=False)

    learner.record_close(_trade("W1", outcome="WIN", net_pnl_pct=0.4,
                                symbol="SOLUSDT", regime="BULL_TREND", side="BUY"))
    learner.record_close(_trade("L1", outcome="LOSS", net_pnl_pct=-0.2,
                                symbol="SOLUSDT", regime="BULL_TREND", side="BUY"))

    metrics = pal.get_segment_metrics("SOLUSDT", "BULL_TREND", "BUY")
    assert metrics is not None
    assert metrics["n"] == 2


# --------------------------------------------------------------------------- #
# P0.4 — dead import removed; authoritative sink exists
# --------------------------------------------------------------------------- #

def test_p0_4_dead_import_symbol_removed():
    """learning_integration never defined on_paper_trade_closed; import path removed."""
    from src.services import learning_integration
    assert not hasattr(learning_integration, "on_paper_trade_closed")
    # The executor must no longer carry the dead module-level symbol.
    assert not hasattr(pte, "on_paper_trade_closed")


def test_p0_4_authoritative_cache_sink_exists():
    from src.services import local_persistent_cache
    assert callable(local_persistent_cache.save_closed_trade)


# --------------------------------------------------------------------------- #
# P0.2 regression (audit review 2026-07-16) — TIMEOUT_NO_PRICE must NOT be
# canonical-learned after the singleton rebind.
# --------------------------------------------------------------------------- #

def test_timeout_no_price_not_canonical_learned(tmp_path):
    """A quarantined TIMEOUT_NO_PRICE close must not increment lifetime_n or rolling."""
    learner = _fresh_learner(tmp_path)
    t = _trade("TNP1", outcome="FLAT", net_pnl_pct=0.0)
    t["exit_reason"] = "TIMEOUT_NO_PRICE"
    t["learning_skipped"] = True
    learner.record_close(t)
    assert learner.lifetime_n == 0
    assert len(learner.rolling100) == 0


def test_learning_skipped_flag_alone_quarantines(tmp_path):
    """learning_skipped=True (without the exit_reason) is also excluded."""
    learner = _fresh_learner(tmp_path)
    t = _trade("SK1", outcome="FLAT", net_pnl_pct=0.0)
    t["learning_skipped"] = True
    learner.record_close(t)
    assert learner.lifetime_n == 0


def test_normal_close_still_records_after_quarantine_guard(tmp_path):
    """A normal close (no quarantine flags) still records exactly once."""
    learner = _fresh_learner(tmp_path)
    learner.record_close(_trade("OK1", outcome="WIN", net_pnl_pct=0.3))
    assert learner.lifetime_n == 1
