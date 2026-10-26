"""Predeclared thresholds and arithmetic on synthetic and immutable evidence."""
from dataclasses import asdict
import json
import math
from pathlib import Path

import pytest

from src.services.learning_experiment_verdict import evaluate_selection_experiment as evaluate


def test_real_evidence_has_no_edge_in_both_arms_and_insufficient_effect_samples():
    path = Path(__file__).resolve().parents[1] / 'docs/codex_prompts/evidence/epoch_20260925_closed_trades_20261026.json'
    arms = {'ADAPTIVE': [], 'CONTROL': []}
    for row in json.loads(path.read_text(encoding='utf-8'))['rows']:
        for tag in json.loads(row['tags_json'] or '[]'):
            if tag.startswith('paper_source_learning_v1:'):
                action = json.loads(tag.split(':', 1)[1])['policy_action']
                if action in arms:
                    arms[action].append(row['pnl_pct'] * 100)
    result = evaluate(arms['ADAPTIVE'], arms['CONTROL'])
    assert result.codes == ('ADAPTIVE_NO_EDGE', 'CONTROL_NO_EDGE', 'EFFECT_INSUFFICIENT_DATA')
    assert (result.adaptive.n, result.control.n) == (59, 68)
    assert result.adaptive.mean_bps == pytest.approx(-7.81)
    assert result.control.mean_bps == pytest.approx(-12.14294117647)
    assert result.adaptive.upper_bps == pytest.approx(-3.9277043271)
    assert result.control.upper_bps == pytest.approx(-8.3038589448)
    assert result.diff_bps == pytest.approx(4.33294117647)
    assert result.diff_low_bps == pytest.approx(-2.17250040216)
    assert result.diff_high_bps == pytest.approx(10.8383827551)


@pytest.mark.parametrize('n, expected', [(29, ('EFFECT_INSUFFICIENT_DATA',)),
    (30, ('ADAPTIVE_NO_EDGE', 'CONTROL_POSITIVE', 'EFFECT_INSUFFICIENT_DATA'))])
def test_minimum_arm_boundary_and_order(n, expected):
    assert evaluate([-1.] * n, [1.] * n).codes == expected


@pytest.mark.parametrize('na,nc', [(99,100), (100,99)])
def test_effect_waits_until_both_arms_reach_threshold(na, nc):
    result = evaluate([1.] * na, [0.] * nc)
    assert result.codes == ('ADAPTIVE_POSITIVE', 'EFFECT_INSUFFICIENT_DATA')
    assert result.diff_low_bps == 1.  # a positive interval alone is insufficient


@pytest.mark.parametrize('adaptive,control,codes', [
    (2.,1.,('ADAPTIVE_POSITIVE','CONTROL_POSITIVE','SELECTION_EFFECT_POSITIVE')),
    (-2.,-1.,('ADAPTIVE_NO_EDGE','CONTROL_NO_EDGE','SELECTION_EFFECT_NEGATIVE')),
    (0.,0.,('SELECTION_EFFECT_NOT_SHOWN',)),
    (1.,1.,('ADAPTIVE_POSITIVE','CONTROL_POSITIVE','SELECTION_EFFECT_NOT_SHOWN')),
])
def test_effect_at_minimum_and_zero_sd(adaptive, control, codes):
    result = evaluate([adaptive]*100,[control]*100)
    assert result.codes == codes
    assert result.adaptive.sd_bps == result.control.sd_bps == 0
    assert result.diff_low_bps == result.diff_high_bps == adaptive-control


def test_custom_thresholds_and_sample_sd():
    result = evaluate([0.,2.],[0.,2.],min_arm_n=2,min_effect_n=2)
    assert result.codes == ('SELECTION_EFFECT_NOT_SHOWN',)
    assert result.adaptive.sd_bps == pytest.approx(math.sqrt(2))
    assert result.adaptive.lower_bps == pytest.approx(-.645)
    assert result.diff_high_bps == pytest.approx(1.96*math.sqrt(2))
    assert result.diff_low_bps == -result.diff_high_bps


@pytest.mark.parametrize('bad', [None,'3',True,float('nan'),float('inf'),float('-inf'),complex(1,1),10**400])
@pytest.mark.parametrize('side', [0,1])
def test_invalid_value_overrides_other_codes(bad,side):
    arms=[[-1.]*100,[-1.]*100]
    arms[side]=[bad]
    result=evaluate(*arms)
    assert result.codes==('INVALID_DATA',)
    assert result.adaptive.mean_bps is result.control.mean_bps is result.diff_bps is None
    json.dumps(asdict(result),allow_nan=False)


@pytest.mark.parametrize('arms', [(None,[]),('12',[]),({'a':1},[])])
def test_invalid_containers(arms):
    assert evaluate(*arms).codes==('INVALID_DATA',)


@pytest.mark.parametrize('kwargs', [{'min_arm_n':True},{'min_arm_n':1},{'min_effect_n':0},
                                  {'min_effect_n':100.},{'min_effect_n':'100'}])
def test_invalid_thresholds(kwargs):
    assert evaluate([1.]*100,[0.]*100,**kwargs).codes==('INVALID_DATA',)


def test_nonfinite_calculation_is_invalid():
    assert evaluate([1e308]*100,[-1e308]*100).codes==('INVALID_DATA',)


def test_empty_and_singleton_have_no_invented_sd():
    result=evaluate([],[])
    assert result.codes==('EFFECT_INSUFFICIENT_DATA',)
    assert result.adaptive.n==0 and result.adaptive.mean_bps is result.diff_bps is None
    result=evaluate([2.],[1.])
    assert result.diff_bps==1. and result.diff_low_bps is result.diff_high_bps is None
    assert result.adaptive.sd_bps is result.adaptive.lower_bps is None


def test_determinism_permutation_and_translation_invariance():
    a,c=[-10.,0.,5.,20.]*30,[-15.,1.,9.]*40
    result=evaluate(a,c)
    assert result==evaluate(a,c)==evaluate(a[::-1],c[::-1])
    moved=evaluate([x+20 for x in a],[x+20 for x in c])
    assert moved.diff_bps==pytest.approx(result.diff_bps)
    assert moved.diff_low_bps==pytest.approx(result.diff_low_bps)
