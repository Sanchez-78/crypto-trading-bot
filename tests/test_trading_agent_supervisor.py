import json
from pathlib import Path

import pytest

from src.services import trading_agent_supervisor as agents


class FakeClock:
    def __init__(self, value=1_700_000_000.0):
        self.value = float(value)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += float(seconds)


@pytest.fixture(autouse=True)
def paper_safe_env(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "paper_train")
    monkeypatch.setenv("ENABLE_REAL_ORDERS", "false")
    monkeypatch.setenv("LIVE_TRADING_CONFIRMED", "false")
    monkeypatch.setenv("PAPER_EXPLORATION_ENABLED", "true")
    monkeypatch.setenv("TRADING_AGENT_MIN_LIFETIME_SAMPLES", "200")
    monkeypatch.setenv("TRADING_AGENT_MIN_TUNING_SAMPLES", "20")
    monkeypatch.setenv("TRADING_AGENT_MIN_NEW_TRADES", "20")
    monkeypatch.setenv("TRADING_AGENT_POLICY_COOLDOWN_S", "3600")


def _learning(lifetime_n=250, pf=0.60, expectancy=-0.02):
    return {
        "lifetime_n": lifetime_n,
        "rolling20_n": 20,
        "rolling20_pf": pf,
        "rolling20_expectancy": expectancy,
    }


def _source(clock, learning=None):
    learning = learning or _learning()

    def collect():
        return {
            "closed_trades": [
                {
                    "trade_id": "latest",
                    "symbol": "BTCUSDT",
                    "exit_ts": clock() - 10,
                }
            ],
            "open_positions": [],
            "learning_snapshot": dict(learning),
        }

    return collect


def _supervisor(tmp_path, clock, source=None, **kwargs):
    market = agents.MarketStateAgent(
        clock=clock,
        stale_after_s=30,
        warmup_s=10,
        sample_interval_s=1,
    )
    market.record_tick("BTCUSDT", 50_000.0, clock())
    return agents.TradingAgentSupervisor(
        state_file=tmp_path / "agent_state.json",
        clock=clock,
        mode_provider=lambda: "paper_train",
        expected_symbols_provider=lambda: ["BTCUSDT"],
        trading_source=source or _source(clock),
        market_agent=market,
        enabled=True,
        auto_apply=True,
        cycle_interval_s=60,
        **kwargs,
    )


def test_market_agent_tracks_per_symbol_freshness_without_cache_refresh():
    clock = FakeClock()
    market = agents.MarketStateAgent(
        clock=clock,
        stale_after_s=10,
        warmup_s=5,
        sample_interval_s=1,
    )
    market.record_tick("BTCUSDT", 50_000, clock())
    market.record_tick("ETHUSDT", 3_000, clock())

    healthy = market.analyze(["BTCUSDT", "ETHUSDT"])
    assert healthy["status"] == "healthy"
    assert healthy["fresh_symbols"] == 2

    clock.advance(20)
    market.record_tick("BTCUSDT", 50_010, clock())
    partial = market.analyze(["BTCUSDT", "ETHUSDT"])

    assert partial["status"] == "degraded"
    assert partial["fresh_symbols"] == 1
    assert partial["stale_symbols"] == ["ETHUSDT"]
    assert partial["price_age_s"]["BTCUSDT"] == 0.0
    assert partial["price_age_s"]["ETHUSDT"] == 20.0


def test_market_agent_pauses_after_warmup_when_feed_is_offline():
    clock = FakeClock()
    market = agents.MarketStateAgent(
        clock=clock,
        stale_after_s=10,
        warmup_s=5,
    )
    assert market.analyze(["BTCUSDT"])["status"] == "warming_up"
    clock.advance(6)
    result = market.analyze(["BTCUSDT"])
    assert result["status"] == "critical"
    assert result["pause_recommended"] is True


@pytest.mark.parametrize(
    ("pf", "expectancy", "expected"),
    [
        (0.40, -0.20, 0.50),
        (0.60, -0.02, 0.75),
        (1.10, 0.02, 1.00),
    ],
)
def test_strategy_tuner_is_bounded_and_risk_off_only(pf, expectancy, expected):
    tuner = agents.StrategyTuningAgent(min_samples=20)
    proposal = tuner.propose(
        trading=_learning(pf=pf, expectancy=expectancy),
        market={"status": "healthy", "pause_recommended": False},
        current_policy=agents._default_policy(),
        now=1_700_000_000,
    )
    assert proposal["target_entry_quota_multiplier"] == expected
    assert 0.50 <= proposal["target_entry_quota_multiplier"] <= 1.00


def test_strategy_tuner_requires_durable_and_recent_evidence(monkeypatch):
    monkeypatch.setenv("TRADING_AGENT_MIN_LIFETIME_SAMPLES", "200")
    tuner = agents.StrategyTuningAgent(min_samples=20)
    proposal = tuner.propose(
        trading=_learning(lifetime_n=199, pf=0.10, expectancy=-1.0),
        market={"status": "healthy", "pause_recommended": False},
        current_policy=agents._default_policy(),
        now=1_700_000_000,
    )
    assert proposal["reason"] == "insufficient_lifetime_samples"
    assert proposal["target_entry_quota_multiplier"] == 1.0


def test_supervisor_applies_only_after_repeated_confirmation(tmp_path):
    clock = FakeClock()
    supervisor = _supervisor(tmp_path, clock)

    first = supervisor.run_cycle()
    assert first["proposal"]["decision"] == "awaiting_confirmation"
    assert first["policy"]["revision"] == 0

    second = supervisor.run_cycle()
    assert second["proposal"]["decision"] == "applied"
    assert second["policy"]["revision"] == 1
    assert second["policy"]["paper_entry_quota_multiplier"] == 0.75
    assert second["policy"]["pause_new_entries"] is False
    assert second["audit"][-1]["event"] == "policy_applied"

    persisted = json.loads((tmp_path / "agent_state.json").read_text())
    assert persisted["policy"]["revision"] == 1


def test_stale_market_pause_is_immediate_and_persisted(tmp_path):
    clock = FakeClock()
    market = agents.MarketStateAgent(
        clock=clock,
        stale_after_s=5,
        warmup_s=1,
    )
    clock.advance(2)
    supervisor = agents.TradingAgentSupervisor(
        state_file=tmp_path / "state.json",
        clock=clock,
        mode_provider=lambda: "paper_train",
        expected_symbols_provider=lambda: ["BTCUSDT"],
        trading_source=_source(clock),
        market_agent=market,
        enabled=True,
        auto_apply=True,
    )
    state = supervisor.run_cycle()
    assert state["agents"]["market_state"]["status"] == "critical"
    assert state["proposal"]["decision"] == "applied"
    assert state["policy"]["pause_new_entries"] is True
    # A single revision can reduce quota by at most 0.25.
    assert state["policy"]["paper_entry_quota_multiplier"] == 0.75


@pytest.mark.parametrize(
    "real_flag",
    [
        "ENABLE_REAL_ORDERS", "LIVE_TRADING_CONFIRMED", "REAL_TRADING_ENABLED"
    ],
)
def test_real_order_flags_block_policy_even_in_paper_mode(
    tmp_path, monkeypatch, real_flag
):
    monkeypatch.setenv(real_flag, "true")
    clock = FakeClock()
    supervisor = _supervisor(tmp_path, clock)
    state = supervisor.run_cycle()
    state = supervisor.run_cycle()

    assert state["supervisor"]["status"] == "safety_blocked"
    assert state["proposal"]["decision"] == "blocked_real_order_flags"
    assert state["policy"] == agents._default_policy()
    assert supervisor.get_effective_policy() == agents._default_policy()


def test_non_paper_mode_is_read_only(tmp_path):
    clock = FakeClock()
    market = agents.MarketStateAgent(clock=clock, stale_after_s=30, warmup_s=10)
    market.record_tick("BTCUSDT", 50_000, clock())
    supervisor = agents.TradingAgentSupervisor(
        state_file=tmp_path / "state.json",
        clock=clock,
        mode_provider=lambda: "live_real",
        expected_symbols_provider=lambda: ["BTCUSDT"],
        trading_source=_source(clock),
        market_agent=market,
        enabled=True,
        auto_apply=True,
    )
    state = supervisor.run_cycle()
    assert state["supervisor"]["status"] == "read_only_non_paper"
    assert state["proposal"]["decision"] == "blocked_non_paper_mode"
    assert supervisor.get_effective_policy() == agents._default_policy()


def test_policy_cooldown_and_new_trade_evidence_gate_recovery(tmp_path):
    clock = FakeClock()
    learning = _learning(pf=0.60, expectancy=-0.02)
    supervisor = _supervisor(
        tmp_path,
        clock,
        source=_source(clock, learning),
    )
    supervisor.run_cycle()
    reduced = supervisor.run_cycle()
    assert reduced["policy"]["paper_entry_quota_multiplier"] == 0.75

    learning.update(_learning(lifetime_n=250, pf=1.20, expectancy=0.03))
    supervisor.run_cycle()
    blocked = supervisor.run_cycle()
    assert blocked["proposal"]["decision"] == "blocked_policy_cooldown"
    assert blocked["policy"]["paper_entry_quota_multiplier"] == 0.75

    clock.advance(3601)
    learning["lifetime_n"] = 270
    supervisor.market_agent.record_tick("BTCUSDT", 50_100, clock())
    recovered = supervisor.run_cycle()
    assert recovered["proposal"]["decision"] == "applied"
    assert recovered["policy"]["paper_entry_quota_multiplier"] == 1.0


def test_circuit_breaker_opens_after_three_collection_failures(tmp_path):
    clock = FakeClock()

    def broken_source():
        raise RuntimeError("metrics unavailable")

    supervisor = _supervisor(tmp_path, clock, source=broken_source)
    for _ in range(3):
        state = supervisor.run_cycle()
        clock.advance(1)

    assert state["supervisor"]["status"] == "circuit_open"
    assert state["supervisor"]["consecutive_failures"] == 3
    assert state["supervisor"]["auto_apply"] is False


def test_candidate_pause_and_quota_never_change_position_size(monkeypatch):
    class FakeSupervisor:
        def __init__(self, policy):
            self.policy = policy

        def get_effective_policy(self):
            return dict(self.policy)

    pause_policy = {
        **agents._default_policy(),
        "revision": 2,
        "pause_new_entries": True,
        "reason": "market_price_feed_critical",
    }
    monkeypatch.setattr(agents, "_supervisor", FakeSupervisor(pause_policy))
    paused = agents.apply_policy_to_training_candidate(
        symbol="BTCUSDT",
        bucket="C_WEAK_EV_TRAIN",
        size_mult=0.08,
    )
    assert paused["allowed"] is False
    assert paused["size_mult"] == 0.0

    quota_policy = {
        **agents._default_policy(),
        "revision": 3,
        "paper_entry_quota_multiplier": 0.50,
        "reason": "critical_negative_recent_edge",
    }
    monkeypatch.setattr(agents, "_supervisor", FakeSupervisor(quota_policy))
    monkeypatch.setattr(agents, "_candidate_sequence", 0)
    results = [
        agents.apply_policy_to_training_candidate(
            symbol="BTCUSDT",
            bucket="C_WEAK_EV_TRAIN",
            size_mult=0.08,
        )
        for _ in range(400)
    ]
    accepted = [result for result in results if result["allowed"]]
    assert 140 <= len(accepted) <= 260
    assert all(result["size_mult"] == 0.08 for result in accepted)


def test_market_stream_dispatch_updates_only_current_symbol(monkeypatch):
    from src.services import market_stream
    from src.services import paper_trade_executor
    from src.services import signal_engine

    calls = []
    ticks = []
    monkeypatch.setattr(
        paper_trade_executor,
        "update_paper_positions",
        lambda prices, ts: calls.append((dict(prices), ts)) or [],
    )
    monkeypatch.setattr(agents, "record_market_tick", lambda s, p, ts: ticks.append((s, p, ts)))
    monkeypatch.setattr(market_stream, "publish", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_stream, "track_price", lambda *args, **kwargs: None)
    monkeypatch.setattr(signal_engine, "SIGNAL_ENGINE_ENABLED", False)
    market_stream._symbol_prices.clear()
    market_stream._symbol_price_timestamps.clear()

    market_stream._dispatch("BTCUSDT", 49_999, 50_001)
    market_stream._dispatch("ETHUSDT", 2_999, 3_001)

    assert calls[0][0] == {"BTCUSDT": 50_000.0}
    assert calls[1][0] == {"ETHUSDT": 3_000.0}
    assert len(ticks) == 2
    snapshot = market_stream.get_price_feed_snapshot()
    assert set(snapshot["price_timestamps"]) == {"BTCUSDT", "ETHUSDT"}


def test_sampler_honors_supervisor_pause(monkeypatch):
    from src.services import paper_training_sampler as sampler

    monkeypatch.setattr(sampler, "_is_training_enabled", lambda: True)
    monkeypatch.setattr(
        sampler,
        "_get_training_bucket",
        lambda signal, ctx, reason: ("C_WEAK_EV_TRAIN", 0.08),
    )
    monkeypatch.setattr(sampler, "_get_disabled_symbols", lambda: set())
    monkeypatch.setattr(
        agents,
        "apply_policy_to_training_candidate",
        lambda **kwargs: {
            "allowed": False,
            "reason": "agent_supervisor_pause:test",
            "size_mult": 0.0,
            "policy_revision": 7,
        },
    )
    result = sampler.maybe_open_training_sample(
        {
            "symbol": "BTCUSDT",
            "action": "BUY",
            "ev": 0.05,
            "p": 0.7,
            "regime": "BULL_TREND",
        },
        reason="TEST",
        current_price=50_000,
    )
    assert result["allowed"] is False
    assert result["reason"] == "agent_supervisor_pause:test"
    assert result["agent_policy_revision"] == 7


def test_dashboard_exposes_agent_state_and_marks_stale(tmp_path, monkeypatch):
    from src.services import dashboard_read_model

    state_file = tmp_path / "agent_state.json"
    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "updated_at": 1,
                "supervisor": {"status": "monitoring", "mode": "paper_train"},
                "agents": {},
                "policy": agents._default_policy(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        dashboard_read_model, "_agent_state_path", lambda: str(state_file)
    )
    loaded = dashboard_read_model._load_agent_state()
    assert loaded["state_available"] is True
    assert loaded["state_stale"] is True
    assert loaded["supervisor"]["status"] == "stale"

    html = Path("src/services/dashboard_web.py").read_text(encoding="utf-8")
    assert "Autonomous Paper Agents" in html
    assert 'id="agent_supervisor_status"' in html
    assert "paper_entry_quota_multiplier" in html
    assert "data.agent_supervisor?.agents?.trading_health?.trading_status" in html


def test_signal_warmup_survives_the_first_live_tick_boundary(monkeypatch):
    import requests

    from src.services import signal_generator

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return [
                [0, "0", "0", "0", str(50_000 + index), "0"]
                for index in range(100)
            ]

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(signal_generator, "prices", {"STALE": [1.0]})
    monkeypatch.setattr(signal_generator, "_macd_vals", {"STALE": [1.0]})
    monkeypatch.setattr(signal_generator, "_adx_hist", {"STALE": 1.0})
    monkeypatch.setattr(signal_generator, "_rsi_hist", {"STALE": 1.0})
    monkeypatch.setattr(signal_generator, "_rsi_full_hist", {"STALE": [1.0]})
    monkeypatch.setattr(signal_generator, "_obi_hist", {"STALE": [1.0]})
    monkeypatch.setattr(signal_generator, "_price_z_hist", {"STALE": [1.0]})
    monkeypatch.setattr(signal_generator, "_first_run", True)

    signal_generator.warmup(["BTCUSDT"], candles=100)

    assert signal_generator._first_run is False
    assert "STALE" not in signal_generator.prices
    assert len(signal_generator.prices["BTCUSDT"]) == 100
    assert signal_generator.prices["BTCUSDT"][-1] == 50_099


def test_signal_and_price_freshness_paths_accept_canonical_and_legacy_shapes():
    signal_source = Path("src/services/signal_generator.py").read_text(
        encoding="utf-8"
    )
    executor_source = Path("src/services/trade_executor.py").read_text(
        encoding="utf-8"
    )

    assert '"timestamp":  call_ts' in signal_source
    assert 'signal.get("timestamp", signal.get("ts", time.time()))' in executor_source
    assert "isinstance(_cur_raw, (tuple, list))" in executor_source
    assert 'pos["signal"].get("ts", pos.get("open_ts", time.time()))' in executor_source


def test_env_example_keeps_agents_and_real_orders_safe_by_default():
    source = Path(".env.example").read_text(encoding="utf-8")
    assert "TRADING_AGENT_SUPERVISOR_ENABLED=false" in source
    assert "TRADING_AGENT_AUTO_APPLY=false" in source
    assert "ENABLE_REAL_ORDERS=false" in source
    assert "LIVE_TRADING_CONFIRMED=false" in source
