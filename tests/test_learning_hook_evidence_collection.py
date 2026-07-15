"""Regression tests for the 2026-07-15 learning-hook fix (reviewer condition #1).

Root cause: close-path learning gates tested paper_source == "training_sampler",
but P0.3C routing rewrites paper_source to "paper_evidence_collection" for all
gated admits — so no production trade ever reached update_from_paper_trade
(LEARNING_UPDATE ok=True stayed 0 forever while trades kept closing).

These tests lock the fixed behavior:
1. A closed evidence-collection trade calls learning_monitor.update_from_paper_trade
   exactly once and logs a LEARNING_UPDATE outcome.
2. A D_NEG_EV_CONTROL evidence-collection trade still routes to SHADOW_SKIP —
   the widened source gate must not weaken D_NEG isolation.
"""

import time
from pathlib import Path
from unittest.mock import patch
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.services import paper_trade_executor as pte


@pytest.fixture
def clean_positions(monkeypatch, tmp_path):
    """Isolate paper state from the host machine and other tests."""
    monkeypatch.setattr(pte, "_POSITIONS", {}, raising=False)
    monkeypatch.setattr(pte, "_STATE_FILE", str(tmp_path / "paper_open_positions.json"), raising=False)
    yield


def _close_with_source(paper_source: str, bucket: str = "C_WEAK_EV_TRAIN"):
    """Open + close one paper position carrying the given paper_source label.

    Returns the MagicMock that replaced learning_monitor.update_from_paper_trade.
    """
    signal = {
        "symbol": "ETHUSDT",
        "action": "BUY",
        "ev": 0.05,
        "score": 0.25,
        "regime": "BULL_TREND",
    }
    result = pte.open_paper_position(
        signal, 2000.0, time.time(), "RDE_TAKE",
        extra={"paper_source": paper_source, "training_bucket": bucket},
    )
    assert result["status"] == "opened", f"entry blocked: {result.get('reason')}"
    trade_id = result["trade_id"]

    # The stored position must carry the (possibly rewritten) source label we test.
    pos = pte._POSITIONS[trade_id]
    pos["paper_source"] = paper_source
    pos["training_bucket"] = bucket
    pos["bucket"] = bucket

    with patch("src.services.learning_monitor.update_from_paper_trade", return_value=True) as mock_update:
        closed = pte.close_paper_position(trade_id, 2002.0, time.time(), "TIMEOUT")
    assert closed is not None
    return mock_update


def test_evidence_collection_close_triggers_learning_update(clean_positions):
    """FIX 2026-07-15: paper_evidence_collection closes must feed learning."""
    mock_update = _close_with_source("paper_evidence_collection")
    assert mock_update.call_count == 1, (
        "update_from_paper_trade must be called exactly once for an "
        "evidence-collection close (was dead code before the gate widening)"
    )
    canon = mock_update.call_args[0][0]
    assert canon["symbol"] == "ETHUSDT"


def test_training_sampler_close_still_triggers_learning_update(clean_positions):
    """Legacy label keeps working after the widening."""
    mock_update = _close_with_source("training_sampler")
    assert mock_update.call_count == 1


def test_d_neg_control_evidence_trade_stays_shadow_skipped(clean_positions):
    """Widened source gate must NOT weaken D_NEG shadow isolation."""
    mock_update = _close_with_source("paper_evidence_collection", bucket="D_NEG_EV_CONTROL")
    assert mock_update.call_count == 0, (
        "D_NEG_EV_CONTROL trades are shadow-only and must never reach "
        "update_from_paper_trade, regardless of paper_source label"
    )


def test_unrelated_source_does_not_trigger_learning_update(clean_positions):
    """Sources outside the allowlist (e.g. normal_rde_take) remain unlearned —
    documented latent gap, revisit at strict-EV graduation (review follow-up)."""
    mock_update = _close_with_source("normal_rde_take")
    assert mock_update.call_count == 0
