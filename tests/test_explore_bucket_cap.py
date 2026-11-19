"""PAPER_EXPLORE_MAX_OPEN_PER_BUCKET: executor fallback and strict deploy validation."""
import sys
from pathlib import Path

import pytest

from src.services import paper_trade_executor as ex

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "research_eval"))
import deploy_env_check as dec  # noqa: E402

BASE = {"TRADING_MODE": "paper_train", "ENABLE_REAL_ORDERS": "false", "LIVE_TRADING_CONFIRMED": "false"}


@pytest.mark.parametrize("raw,expected", [
    (None, 2), ("", 2), ("1", 1), ("2", 2), ("7", 7),
    ("0", 2), ("8", 2), ("-3", 2), ("3.5", 2), ("abc", 2), (" 5 ", 5), ("٣", 2),
])
def test_executor_cap_falls_back_to_default(raw, expected):
    env = {} if raw is None else {"PAPER_EXPLORE_MAX_OPEN_PER_BUCKET": raw}
    assert ex.exploration_bucket_cap(env) == expected


@pytest.mark.parametrize("raw", ["1", "5", "7"])
def test_deploy_check_accepts_range(raw):
    dec.check_invariants({**BASE, "PAPER_EXPLORE_MAX_OPEN_PER_BUCKET": raw})


@pytest.mark.parametrize("raw", ["0", "8", "", "five", "3.0", "-1", " 5"])
def test_deploy_check_refuses_bad_values(raw):
    with pytest.raises(dec.Refused):
        dec.check_invariants({**BASE, "PAPER_EXPLORE_MAX_OPEN_PER_BUCKET": raw})


def test_unset_is_allowed_by_deploy_check():
    dec.check_invariants(dict(BASE))


def _pos(symbol, bucket="P0_8_PLUS_EVIDENCE_COLLECTION"):
    return {"symbol": symbol, "explore_bucket": bucket, "training_bucket": bucket,
            "entry_ts": __import__("time").time(), "opened_at": __import__("time").time()}


def test_bucket_cap_uses_env(monkeypatch):
    positions = {f"p{i}": _pos(s) for i, s in enumerate(["BTCUSDT", "ETHUSDT"])}
    monkeypatch.setattr(ex, "_POSITIONS", positions)
    monkeypatch.setattr(ex, "_is_position_stale", lambda p, now: False)
    monkeypatch.delenv("PAPER_EXPLORE_MAX_OPEN_PER_BUCKET", raising=False)
    blocked = ex._check_exploration_exposure_caps("SOLUSDT", "P0_8_PLUS_EVIDENCE_COLLECTION")
    assert blocked and blocked["reason"] == "max_open_per_bucket"
    monkeypatch.setenv("PAPER_EXPLORE_MAX_OPEN_PER_BUCKET", "3")
    assert ex._check_exploration_exposure_caps("SOLUSDT", "P0_8_PLUS_EVIDENCE_COLLECTION") is None
    # max_open_per_symbol = 1 is unchanged by the bucket cap
    assert ex._check_exploration_exposure_caps("BTCUSDT", "P0_8_PLUS_EVIDENCE_COLLECTION")["reason"] == \
        "max_open_per_symbol"
