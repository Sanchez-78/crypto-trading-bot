"""Real native generators and central routing on an immutable completed-bar view."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock
import json

import pytest

from src.services import p0_8_plus_shadow_evaluator as evaluator, paper_source_learning as policy
from src.services import strategy_trend_cost_aware_v1 as trend
from src.services import strategy_volatility_breakout_v1 as breakout
from src.services import strategy_sideways_mean_reversion_v1 as reversion
from src.services.candle_cache_v1 import CandleCache
from src.services.p0_risk_guard_v1 import RiskGuardResult
from src.services.strategy_registry import StrategyRegistry
from tests.test_strategy_trend_cost_aware_v1 import _make_candles
from tests.test_strategy_volatility_breakout_v1 import _make_compression_then_breakout
from tests.test_strategy_sideways_mean_reversion_v1 import _make_range_bound_candles, _push_extension, _GOOD_DOWN_SEEDS
from tests.test_paper_cost_exploration import training


@pytest.mark.parametrize('module', [trend, breakout, reversion])
def test_real_generator_preserves_cost_reject_by_default_and_returns_honest_probe(module, monkeypatch):
    if module is trend:
        bars, regime = _make_candles(220,drift_bps_per_bar=15,seed=20), 'BULL_TREND'
    elif module is breakout:
        bars, regime = _make_compression_then_breakout(seed=20), 'SIDEWAYS'
    else:
        bars, regime = _push_extension(_make_range_bound_candles(seed=_GOOD_DOWN_SEEDS[0]),direction=-1), 'SIDEWAYS'
    price = bars[-1]['close']
    args = dict(candles=bars,symbol='ETHUSDT',regime=regime,regime_confidence=.9,
        best_bid=price*.9999,best_ask=price*1.0001,
        signal_id_factory=lambda *parts:':'.join(map(str,parts)),now_ms=bars[-1]['open_time']+60000)
    baseline = module.generate_candidates(**args)
    assert baseline
    real_cost = module.cost_model.evaluate_edge
    def expensive(**kwargs):
        edge = real_cost(**kwargs)
        return replace(edge,cost=replace(edge.cost,entry_fee_bps=1000.))
    monkeypatch.setattr(module.cost_model,'evaluate_edge',expensive)
    assert module.generate_candidates(**args) == []
    probes = module.generate_candidates(**args,include_cost_rejected=True)
    assert len(probes) == len(baseline)
    for old,new in zip(baseline,probes):
        assert old.gross_expected_move_bps == new.gross_expected_move_bps
        assert new.net_expected_edge_bps < 0 and new.expected_cost_bps > old.expected_cost_bps
        assert new.side == old.side and new.evidence_only and not new.shadow_only


def pipeline(monkeypatch):
    bars = _make_candles(260,drift_bps_per_bar=2,range_mult=1.0003,start_time_ms=1_800_000_000_000)
    close_ms = bars[-1]['open_time']+60000
    partial = dict(bars[-1],open_time=close_ms,volume=0,high=bars[-1]['close'],low=bars[-1]['close'])
    clock = [close_ms/1000+1]
    cache = CandleCache(fetch_fn=lambda *_:bars+[partial],now_fn=lambda:clock[0],refresh_seconds=600)
    price = bars[-1]['close']
    quote = SimpleNamespace(bid=price*.99999,ask=price*1.00001)
    from src.services.stonkfly import runtime
    offer = Mock()
    monkeypatch.setattr(runtime,'offer_market',offer)
    registry = StrategyRegistry()
    evaluator.ensure_registered(['ETHUSDT'],registry=registry)
    def evaluate():
        return evaluator.evaluate_symbol('ETHUSDT',cache=cache,registry=registry,
            now_ms=int(clock[0]*1000),get_quote_fn=lambda *a,**k:quote,
            risk_guard_fn=lambda **_:RiskGuardResult(True,'fixture'))
    return evaluate,clock,close_ms,registry,offer


def test_completed_actual_native_candidate_reaches_p0_with_stable_identity_and_separate_cohort(training, monkeypatch):
    evaluate,clock,close_ms,registry,offer = pipeline(monkeypatch)
    results = evaluate()
    assert results
    row = next(r for r in results if r.strategy_id=='trend_cost_aware')
    assert row.evaluation.admitted and row.evaluation.net_expected_edge_bps < 0
    assert row.signal.market_data_event_time_ms == close_ms
    assert row.signal.feature_snapshot_time_ms == close_ms
    assert row.signal.generated_event_time_ms == close_ms
    assert row.signal.strategy_version == policy.PROBE_VERSION
    assert row.signal.learning_source == 'trend_cost_aware_paper_probe_v2'
    assert registry.get(row.strategy_id).current_version == policy.PROBE_VERSION
    assert ':trend_cost_aware:' in row.signal.signal_id
    assert row.evaluation.p0_strict_ev is False and row.evaluation.p0_readiness_eligible is False
    from src.services.p0_8_plus_live_pipeline import _map_to_legacy_signal
    mapped, extra = _map_to_legacy_signal(row, row.signal.reference_price)
    assert type(extra['cost_edge_ok']) is bool
    assert json.loads(json.dumps({'signal': mapped, 'extra': extra}, allow_nan=False))['extra']['cost_edge_ok'] is False
    assert offer.call_args.kwargs['candles'][-1]['open_time'] == close_ms-60000
    clock[0] += 4  # neural wake, same finalized input, not a second decision
    again = next(r for r in evaluate() if r.strategy_id=='trend_cost_aware')
    assert again.signal.signal_id == row.signal.signal_id
    assert again.evaluation.learning_metadata['policy_draw'] == row.evaluation.learning_metadata['policy_draw']
    clock[0] += 90  # failed/no refresh must not promote the cached partial bar
    stale = next(r for r in evaluate() if r.strategy_id=='trend_cost_aware')
    assert stale.signal.market_data_event_time_ms == close_ms
    assert not stale.evaluation.admitted and stale.evaluation.decision_code=='REJECT_STALE_MARKET_DATA'


def test_completed_profile_without_cost_experiment_keeps_cost_veto(training, monkeypatch):
    monkeypatch.setenv(policy.PROBE_FLAG,'false')
    evaluate,_,_,registry,_ = pipeline(monkeypatch)
    assert registry.get('trend_cost_aware').current_version == policy.CLOSED_BAR_VERSION
    assert evaluate() == []


def test_register_switches_profile_without_changing_strategy_ids_or_old_thresholds(training,monkeypatch):
    registry=StrategyRegistry()
    evaluator.ensure_registered(['BTCUSDT'],registry=registry)
    assert registry.get('trend_cost_aware').current_version==policy.PROBE_VERSION
    monkeypatch.setenv(policy.PROBE_FLAG,'false')
    monkeypatch.setenv(policy.CLOSED_BAR_FLAG,'false')
    evaluator.ensure_registered(['BTCUSDT'],registry=registry)
    assert registry.get('trend_cost_aware').current_version=='1'
    assert registry.get('trend_cost_aware').evidence_only
