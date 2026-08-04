import json

from src.services.learning_archive import LearningArchive
from src.services.paper_exploration_agent import PaperExplorationAgent
from src.services.trade_review_agent import TradeReviewAgent


class Clock:
    def __init__(self, value=1_800_000_000.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


def _trade(index, pnl, **overrides):
    outcome = "WIN" if pnl > 0.05 else "LOSS" if pnl < -0.05 else "FLAT"
    value = {
        "trade_id": f"trade-{index:04d}",
        "symbol": "BTCUSDT" if index % 2 else "ETHUSDT",
        "side": "BUY" if index % 2 else "SELL",
        "entry_ts": 1_700_000_000 + index * 60,
        "exit_ts": 1_700_000_030 + index * 60,
        "pnl_pct": pnl,
        "net_pnl_pct": pnl,
        "outcome": outcome,
        "exit_reason": "TIMEOUT",
        "regime": "RANGING",
        "paper_source": "training_sampler",
        "learning_source": "paper_training_sampler",
        "readiness_eligible": True,
        "real_readiness_eligible": True,
        "paper_learning_only": False,
        "learning_shadow_only": False,
    }
    value.update(overrides)
    return value


def _review(trades, quota=1.0):
    return TradeReviewAgent().analyze(
        trades,
        current_policy={"paper_entry_quota_multiplier": quota},
        learning_snapshot={"lifetime_n": 1000},
        now=1_800_000_000,
    )


def test_archive_duplicate_is_idempotent(tmp_path):
    archive = LearningArchive(tmp_path / "archive.sqlite")
    first = archive.append("paper_trade_closed", {"trade_id": "t1"}, event_id="e1")
    second = archive.append("paper_trade_closed", {"trade_id": "t1"}, event_id="e1")

    assert first["accepted"] is True
    assert second["duplicate"] is True
    assert archive.status()["total_events"] == 1


def test_archive_same_id_with_different_payload_fails_closed(tmp_path):
    archive = LearningArchive(tmp_path / "archive.sqlite")
    archive.append("paper_trade_closed", {"pnl": 1}, event_id="e1")

    conflict = archive.append("paper_trade_closed", {"pnl": -1}, event_id="e1")

    assert conflict["accepted"] is False
    assert conflict["duplicate"] is False
    assert conflict["reason"] == "event_id_payload_conflict"


def test_archive_marks_only_confirmed_events_synced(tmp_path):
    archive = LearningArchive(tmp_path / "archive.sqlite")
    archive.append("one", {"n": 1}, event_id="e1")
    archive.append("two", {"n": 2}, event_id="e2")

    result = archive.flush(writer=lambda events: ["e1"])

    assert result["sent"] == 1
    assert archive.status()["pending_events"] == 1


def test_archive_failure_preserves_outbox(tmp_path):
    archive = LearningArchive(tmp_path / "archive.sqlite")
    archive.append("one", {"n": 1}, event_id="e1")

    def fail(_events):
        raise TimeoutError("firebase unavailable")

    result = archive.flush(writer=fail)

    assert result["flush"] == "failed"
    assert archive.status()["pending_events"] == 1
    assert archive.pending()[0]["attempts"] == 1


def test_archive_bounded_hydration_is_idempotent(tmp_path):
    archive = LearningArchive(tmp_path / "archive.sqlite")
    remote = [
        {
            "event_id": "remote-1",
            "event_type": "adaptive_learning_checkpoint",
            "created_at": 100,
            "payload": {"lifetime_metrics": {"trades_closed": 200}},
        }
    ]

    assert archive.hydrate(loader=lambda limit: remote) == 1
    assert archive.hydrate(loader=lambda limit: remote) == 0
    assert archive.recent("adaptive_learning_checkpoint")[0]["synced"] is True


def test_trade_review_uses_pnl_magnitude_for_profit_factor():
    report = _review([_trade(i, 0.10 if i % 2 else -0.20) for i in range(200)])

    metrics = report["metrics"]["canonical"]["all"]
    assert metrics["wins"] == 100
    assert metrics["losses"] == 100
    assert metrics["profit_factor"] == 0.5


def test_trade_review_two_weak_windows_recommends_quota_075():
    pnl = [0.10] * 100 + [0.10, -0.15] * 50
    report = _review([_trade(i, value) for i, value in enumerate(pnl)])

    recommendation = report["recommendation"]
    assert report["status"] == "ready"
    assert recommendation["code"] == "GLOBAL_QUOTA_075"
    assert recommendation["target_entry_quota_multiplier"] == 0.75
    assert recommendation["auto_applicable"] is True


def test_trade_review_critical_recent_and_weak_previous_recommends_050():
    pnl = [0.10] * 100 + [0.10, -0.15] * 25 + [-0.20] * 50
    report = _review([_trade(i, value) for i, value in enumerate(pnl)])

    assert report["recommendation"]["code"] == "GLOBAL_QUOTA_050"
    assert report["recommendation"]["target_entry_quota_multiplier"] == 0.50


def test_trade_review_reduces_only_stably_weak_canonical_symbol():
    strong = [
        _trade(index, 0.20, symbol="ETHUSDT")
        for index in range(140)
    ]
    weak = [
        _trade(
            140 + index,
            0.10 if index % 2 else -0.20,
            symbol="ADAUSDT",
        )
        for index in range(60)
    ]

    report = _review(strong + weak)

    assert report["symbol_policy"] == {
        "code": "APPLY_CANONICAL_SYMBOL_QUOTAS",
        "auto_applicable": True,
        "current_canonical_quota_multipliers": {},
        "target_canonical_quota_multipliers": {"ADAUSDT": 0.10},
        "minimum_evidence_per_symbol": 60,
    }
    advisory = next(
        item
        for item in report["advisories"]
        if item["code"] == "CANONICAL_SYMBOL_QUOTA_REDUCE"
    )
    assert advisory["symbol"] == "ADAUSDT"
    assert advisory["previous30"]["profit_factor"] == 0.5
    assert advisory["recent30"]["profit_factor"] == 0.5


def test_trade_review_does_not_reduce_symbol_after_one_weak_window():
    other = [
        _trade(index, 0.20, symbol="ETHUSDT")
        for index in range(140)
    ]
    recovering = [
        _trade(140 + index, 0.20, symbol="ADAUSDT")
        for index in range(30)
    ] + [
        _trade(
            170 + index,
            0.10 if index % 2 else -0.20,
            symbol="ADAUSDT",
        )
        for index in range(30)
    ]

    report = _review(other + recovering)

    assert report["symbol_policy"]["auto_applicable"] is False
    assert report["symbol_policy"]["target_canonical_quota_multipliers"] == {}


def test_exploration_outcomes_never_drive_canonical_recommendation():
    canonical = [_trade(i, 0.10) for i in range(150)]
    exploration = [
        _trade(
            1000 + i,
            1.0,
            bucket="D_NEG_EV_CONTROL",
            training_bucket="D_NEG_EV_CONTROL",
            readiness_eligible=False,
            real_readiness_eligible=False,
            paper_learning_only=True,
            learning_shadow_only=True,
        )
        for i in range(50)
    ]
    report = _review(canonical + exploration)

    assert report["window"]["exploration_n"] == 50
    assert report["metrics"]["exploration"]["all"]["profit_factor"] == 999.0
    assert report["recommendation"]["auto_applicable"] is False


def test_exploration_volume_does_not_starve_canonical_review_window():
    pnl = [0.10] * 100 + [0.10, -0.15] * 50
    canonical = [_trade(i, value) for i, value in enumerate(pnl)]
    exploration = [
        _trade(
            1000 + index,
            1.0,
            bucket="D_NEG_EV_CONTROL",
            training_bucket="D_NEG_EV_CONTROL",
            readiness_eligible=False,
            real_readiness_eligible=False,
            paper_learning_only=True,
            learning_shadow_only=True,
        )
        for index in range(200)
    ]

    report = _review(canonical + exploration)

    assert report["status"] == "ready"
    assert report["window"] == {
        "requested_n": 200,
        "scan_limit_n": 400,
        "raw_n": 400,
        "canonical_n": 200,
        "exploration_n": 200,
        "scanned_canonical_n": 200,
        "scanned_exploration_n": 200,
        "unknown_provenance_n": 0,
    }
    assert report["recommendation"]["code"] == "GLOBAL_QUOTA_075"


def test_trade_review_separates_post_policy_evidence():
    trades = [_trade(index, 0.10) for index in range(180)] + [
        _trade(index, -0.20) for index in range(180, 200)
    ]
    applied_at = trades[180]["exit_ts"]

    report = TradeReviewAgent().analyze(
        trades,
        current_policy={
            "revision": 3,
            "applied_at": applied_at,
            "paper_entry_quota_multiplier": 0.75,
        },
        learning_snapshot={"lifetime_n": 1000},
        now=1_800_000_000,
    )

    assert report["post_policy"]["status"] == "review_required"
    assert report["post_policy"]["next_action"] == "review_post_policy_edge"
    assert report["post_policy"]["canonical"]["n"] == 20
    assert report["post_policy"]["canonical"]["net_pnl_pct_points"] == -4.0


def test_trade_review_waits_for_minimum_post_policy_sample():
    trades = [_trade(index, 0.10) for index in range(181)] + [
        _trade(index, -0.20) for index in range(181, 200)
    ]

    report = TradeReviewAgent().analyze(
        trades,
        current_policy={
            "revision": 3,
            "applied_at": trades[181]["exit_ts"],
        },
        learning_snapshot={"lifetime_n": 1000},
        now=1_800_000_000,
    )

    assert report["post_policy"]["status"] == "collecting"
    assert report["post_policy"]["canonical"]["n"] == 19
    assert report["post_policy"]["minimum_canonical_n"] == 20


def test_unknown_legacy_provenance_blocks_strategy_change():
    trades = []
    for index in range(200):
        trade = _trade(index, -0.2)
        for key in (
            "paper_source",
            "learning_source",
            "readiness_eligible",
            "real_readiness_eligible",
        ):
            trade.pop(key)
        trades.append(trade)

    report = _review(trades)

    assert report["status"] == "data_quality_blocked"
    assert report["recommendation"]["code"] == "DATA_QUALITY_BLOCK"
    assert report["recommendation"]["auto_applicable"] is False


def test_outcome_contract_mismatch_blocks_strategy_change():
    trades = [_trade(index, 0.2) for index in range(200)]
    trades[-1]["outcome"] = "LOSS"
    report = _review(trades)
    assert report["recommendation"]["code"] == "DATA_QUALITY_BLOCK"
    assert report["data_quality"]["excluded_by_reason"] == {
        "outcome_contract_mismatch": 1
    }
    assert report["recommendation"]["auto_applicable"] is False


def test_trade_review_is_deterministic_for_identical_evidence():
    trades = [_trade(i, 0.1 if i % 3 else -0.2) for i in range(200)]

    first = _review(trades)
    second = _review(list(reversed(trades)))

    assert first["run_id"] == second["run_id"]
    assert first["metrics"] == second["metrics"]
    assert first["recommendation"] == second["recommendation"]


def test_exploration_agent_opens_tiny_shadow_control_after_drought():
    clock = Clock()
    calls = []

    def opener(**kwargs):
        calls.append(kwargs)
        return {"status": "opened", "trade_id": "paper-control-1"}

    agent = PaperExplorationAgent(
        clock=clock,
        opener=opener,
        enabled=True,
        drought_after_s=300,
        cooldown_s=600,
        max_entries_per_hour=2,
    )
    clock.advance(301)
    state = agent.consider(
        market={
            "status": "healthy",
            "market_regime": "mixed",
            "control_candidates": [
                {
                    "symbol": "ETHUSDT",
                    "price": 3000.0,
                    "price_ts": clock(),
                    "move_bps": 2.0,
                }
            ],
        },
        trading={"last_close_age_s": 500},
        review={"metrics": {"exploration": {"coverage": {}}}},
        open_positions=[],
        policy={"pause_new_entries": False},
        paper_safe=True,
        now=clock(),
    )

    assert state["status"] == "opened"
    assert len(calls) == 1
    assert calls[0]["signal"]["readiness_eligible"] is False
    assert calls[0]["signal"]["action"] == "SELL"
    assert calls[0]["extra"]["training_bucket"] == "D_NEG_EV_CONTROL"
    assert calls[0]["extra"]["final_size_usd"] <= 2.0


def test_exploration_agent_requires_healthy_market_and_paper_safety():
    clock = Clock()
    calls = []
    agent = PaperExplorationAgent(
        clock=clock,
        opener=lambda **kwargs: calls.append(kwargs),
        enabled=True,
        drought_after_s=300,
    )
    clock.advance(301)
    base = {
        "trading": {"last_close_age_s": 500},
        "review": {},
        "open_positions": [],
        "policy": {"pause_new_entries": False},
        "now": clock(),
    }

    unsafe = agent.consider(
        market={"status": "healthy", "control_candidates": []},
        paper_safe=False,
        **base,
    )
    unhealthy = agent.consider(
        market={"status": "critical", "control_candidates": []},
        paper_safe=True,
        **base,
    )

    assert unsafe["status"] == "blocked"
    assert unhealthy["status"] == "observing"
    assert calls == []


def test_exploration_agent_enforces_cooldown_after_success():
    clock = Clock()
    agent = PaperExplorationAgent(
        clock=clock,
        opener=lambda **kwargs: {"status": "opened", "trade_id": "t1"},
        enabled=True,
        drought_after_s=300,
        cooldown_s=600,
    )
    clock.advance(301)
    kwargs = {
        "market": {
            "status": "healthy",
            "market_regime": "mixed",
            "control_candidates": [
                {
                    "symbol": "ETHUSDT",
                    "price": 3000.0,
                    "price_ts": clock(),
                    "move_bps": 2.0,
                }
            ],
        },
        "trading": {"last_close_age_s": 1000},
        "review": {},
        "open_positions": [],
        "policy": {"pause_new_entries": False},
        "paper_safe": True,
    }
    assert agent.consider(now=clock(), **kwargs)["status"] == "opened"
    clock.advance(60)
    assert agent.consider(now=clock(), **kwargs)["status"] == "cooldown"


def test_dashboard_contains_review_exploration_and_archive_cards():
    html = open("src/services/dashboard_web.py", encoding="utf-8").read()
    assert 'id="agent_review_status"' in html
    assert 'id="agent_exploration_status"' in html
    assert 'id="agent_archive_status"' in html
