"""Offline report on disposable DBs and the immutable supplied evidence."""
import json
import os
from pathlib import Path
import sqlite3

import pytest

from scripts.research import p0_8_plus_epoch_report as report

EVIDENCE = Path(__file__).resolve().parents[1] / "docs/codex_prompts/evidence/epoch_20260925_closed_trades.json"


def _row(**overrides):
    row = dict(trade_id="one", learning_source="test", entry_ts=1700000000, exit_ts=1700000100,
               pnl_pct=.2, outcome="WIN", exit_reason="TP", side="BUY", entry_price=100,
               exit_price=100.3, mfe_gross_bps=40, mae_gross_bps=-10,
               predicted_gross_move_bps=35, predicted_net_edge_bps=20)
    row.update(overrides)
    return row


def _json_rows(tmp_path, rows):
    path = tmp_path / "source.json"
    path.write_text(json.dumps({"rows": rows}), encoding="utf-8")
    return path


def test_supplied_evidence_report_counts_means_and_no_calibration(tmp_path):
    before = EVIDENCE.read_bytes()
    output = tmp_path / "report"
    assert report.main(["--json", str(EVIDENCE), "--out", str(output)]) == 0
    data = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert data["total"]["n"] == 82
    assert data["total"]["outcomes"] == dict(WIN=28, LOSS=52, FLAT=2)
    assert data["total"]["mean_net_bps"] == pytest.approx(-10.634756, abs=.01)
    sources = data["by_learning_source"]
    assert sources["sideways_mean_reversion_v1"]["mean_net_bps"] == pytest.approx(-11.798421, abs=.01)
    assert sources["volatility_breakout_v1"]["mean_net_bps"] == pytest.approx(-7.9816, abs=.01)
    assert sources["sideways_mean_reversion_v1"]["evidence_budget"]["code"] == "STOP_NO_EDGE"
    assert sources["volatility_breakout_v1"]["evidence_budget"]["code"] == "CONTINUE"
    assert data["total"]["calibration"]["status"] == "NO_DATA"
    assert data["total"]["calibration"]["mean_predicted_gross_bps"] is None
    assert data["total"]["barriers"]["realized_breakeven_tp_share"] == pytest.approx(.560056, abs=.00001)
    assert data["total"]["excursions"]["mfe_gross_bps"]["thresholds"]["20"]["count"] == 45
    assert data["total"]["excursions"]["mae_gross_bps"]["thresholds"]["20"]["count"] == 46
    assert EVIDENCE.read_bytes() == before
    assert "NO_DATA" in (output / "report.md").read_text(encoding="utf-8")


def test_sqlite_read_only_since_calibration_and_side(tmp_path, monkeypatch):
    path = tmp_path / "history.sqlite"
    rows = [_row(trade_id="old", entry_ts=1, exit_ts=2),
            _row(), _row(trade_id="short", side="SELL", exit_price=99.7, predicted_gross_move_bps=25)]
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE closed_trades (" + ",".join(rows[0]) + ")")
        conn.executemany("INSERT INTO closed_trades VALUES (" + ",".join("?" for _ in rows[0]) + ")",
                         [tuple(row.values()) for row in rows])
    original = path.read_bytes()
    real_connect = sqlite3.connect
    def readonly(database, **kwargs):
        assert "mode=ro" in database and kwargs["uri"] is True
        return real_connect(database, **kwargs)
    monkeypatch.setattr(report.sqlite3, "connect", readonly)
    output = tmp_path / "output"
    report.main(["--db", str(path), "--since", "1700000000", "--out", str(output)])
    data = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert data["total"]["n"] == 2
    calibration = data["total"]["calibration"]
    assert calibration["n"] == 2 and calibration["mean_predicted_gross_bps"] == 30
    assert calibration["mean_realized_gross_bps"] == pytest.approx(30)
    assert calibration["mean_error_bps"] == pytest.approx(0, abs=1e-10)
    assert calibration["mean_absolute_error_bps"] == pytest.approx(5)
    assert path.read_bytes() == original
    assert {p.name for p in tmp_path.iterdir()} == {"history.sqlite", "output"}


def test_legacy_sqlite_missing_columns_is_no_data(tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE closed_trades (entry_ts REAL,exit_ts REAL,pnl_pct REAL)")
        conn.execute("INSERT INTO closed_trades VALUES (1,2,0)")
    summary = report.build_report(report.load_rows(db=path))["total"]
    assert summary["outcomes"] == dict(WIN=0, LOSS=0, FLAT=1)
    assert summary["calibration"]["status"] == "NO_DATA"
    assert summary["excursions"]["mae_gross_bps"]["status"] == "NO_DATA"


def test_realized_barrier_medians_and_missing_excursion_denominators(tmp_path):
    path = _json_rows(tmp_path, [_row(mfe_gross_bps=60),
        _row(trade_id="loss", exit_reason="SL", outcome="LOSS", pnl_pct=-.4, mfe_gross_bps=None, mae_gross_bps=-40)])
    data = report.build_report(report.load_rows(json_path=path))["total"]
    assert data["barriers"]["tp_share"] == .5
    assert data["barriers"]["driftless_tp_share"] == .4  # 40/(60+40), not env25/(35+25)
    assert data["barriers"]["realized_breakeven_tp_share"] == pytest.approx(2/3)
    assert data["excursions"]["mfe_gross_bps"]["n"] == 1
    assert data["excursions"]["mfe_gross_bps"]["thresholds"]["35"]["fraction"] == 1
    assert data["cost_sensitivity"]["assumed_net_at_9_bps"] == -10
    assert data["cost_sensitivity"]["approximated_net_at_15_bps"] == -16


def test_day_bootstrap_retains_complete_blocks_and_is_deterministic(tmp_path):
    # Two trades on one UTC day and one on the next. Resampling individual
    # trades would have different percentile endpoints and weighting.
    path = _json_rows(tmp_path, [_row(entry_ts=1, exit_ts=86399, pnl_pct=.1),
        _row(trade_id="two", entry_ts=2, exit_ts=86399.9, pnl_pct=.1),
        _row(trade_id="three", entry_ts=3, exit_ts=86400, pnl_pct=-.2)])
    rows = report.load_rows(json_path=path)
    ci = report.day_block_bootstrap(rows)
    assert ci == report.day_block_bootstrap(list(reversed(rows)))
    assert ci["blocks"] == 2 and ci["replicates"] == 2000
    assert ci["lower_bps"] == -20 and ci["upper_bps"] == 10
    assert report.build_report(rows)["total"]["mean_net_bps"] == 0


def test_empty_input_and_filtered_empty_are_no_data(tmp_path):
    path = _json_rows(tmp_path, [])
    data = report.build_report(report.load_rows(json_path=path))
    assert data["status"] == "NO_DATA" and data["total"]["mean_net_bps"] is None
    assert data["total"]["bootstrap_95"]["status"] == "NO_DATA"
    assert data["total"]["evidence_budget"]["code"] == "CONTINUE"  # warmup, not proof of edge
    path = _json_rows(tmp_path, [_row()])
    assert report.load_rows(json_path=path, since=1800000000) == []


@pytest.mark.parametrize("changes", [dict(pnl_pct=None), dict(pnl_pct=float("inf")),
                                    dict(exit_ts=0), dict(exit_ts=1e300), dict(entry_ts=True)])
def test_invalid_core_data_fails_explicitly_without_report(tmp_path, changes):
    path = _json_rows(tmp_path, [_row(**changes)])
    output = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        report.main(["--json", str(path), "--out", str(output)])
    assert exc.value.code == 2 and not output.exists()


def test_missing_db_is_not_created(tmp_path):
    path, output = tmp_path / "missing.sqlite", tmp_path / "out"
    with pytest.raises(SystemExit):
        report.main(["--db", str(path), "--out", str(output)])
    assert not path.exists() and not output.exists()


def test_input_cannot_be_overwritten_and_only_output_files_written(tmp_path):
    path = tmp_path / "report.json"
    path.write_text('{"rows": []}', encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(SystemExit):
        report.main(["--json", str(path), "--out", str(tmp_path)])
    assert path.read_bytes() == before and not (tmp_path / "report.md").exists()


def test_report_preserves_persisted_outcome_instead_of_pnl_sign(tmp_path):
    path = _json_rows(tmp_path, [_row(pnl_pct=.04, outcome="FLAT"),
                                _row(trade_id="two", pnl_pct=-.01, outcome=None)])
    assert report.build_report(report.load_rows(json_path=path))["total"]["outcomes"] == dict(WIN=0, LOSS=0, FLAT=2)


def test_invalid_outcome_uses_same_fallback_in_total_and_exit_breakdown(tmp_path):
    path = _json_rows(tmp_path, [_row(outcome="UNKNOWN")])
    data = report.build_report(report.load_rows(json_path=path))["total"]
    assert data["outcomes"]["WIN"] == data["exit_reasons"]["TP"]["outcomes"]["WIN"] == 1
    assert sum(data["exit_reasons"]["TP"]["outcomes"].values()) == data["n"]


def test_output_hardlink_does_not_modify_external_file(tmp_path):
    source = _json_rows(tmp_path, [])
    outside = tmp_path / "keep.txt"
    outside.write_bytes(b"preserve unrelated file")
    output = tmp_path / "out"
    output.mkdir()
    os.link(outside, output / "report.md")
    report.main(["--json", str(source), "--out", str(output)])
    assert outside.read_bytes() == b"preserve unrelated file"
    assert not outside.samefile(output / "report.md")
    assert {p.name for p in output.iterdir()} == {"report.json", "report.md"}


def _policy_tag(action="ADAPTIVE", probability=.3, version="paper_source_learning_v1", **extra):
    return version + ":" + json.dumps(dict(policy_version=version, policy_action=action,
                                          policy_probability=probability, **extra))


@pytest.mark.parametrize("version", ["paper_source_learning_v1", "paper_source_learning_stonkfly_v1"])
def test_policy_tag_parser_selects_only_declared_fields(version):
    result = report.parse_policy_tag(json.dumps(["unrelated_tag", _policy_tag(version=version, neural_raw=[1, 2])]))
    assert result == dict(status="OK", policy_version=version, policy_action="ADAPTIVE", policy_probability=.3)


@pytest.mark.parametrize("tags", [None, "", "[]", '["unrelated_tag"]'])
def test_missing_policy_is_not_control(tags):
    result = report.parse_policy_tag(tags)
    assert result["status"] == result["policy_action"] == result["policy_version"] == "NO_POLICY"
    assert result["policy_probability"] is None


@pytest.mark.parametrize("tags", ["not json", "{}", "null", "[42]", [],
    json.dumps(["paper_source_learning_v1:broken"]),
    json.dumps(["paper_source_learning_v1:null"]),
    json.dumps(["paper_source_learning_v1"]),
    json.dumps([_policy_tag(), _policy_tag()]),
    json.dumps([_policy_tag(action="TYPO")]),
    json.dumps([_policy_tag(probability=True)]),
    json.dumps([_policy_tag(probability="0.3")]),
    json.dumps([_policy_tag(probability=float('nan'))]),
    json.dumps([_policy_tag(probability=float('inf'))]),
    json.dumps([_policy_tag(probability=-.1)]),
    json.dumps([_policy_tag(probability=1.1)]),
    json.dumps([_policy_tag(unused=float('nan'))]),
    json.dumps([_policy_tag(unused=float('inf'))]),
    json.dumps([_policy_tag().replace('"policy_version": "paper_source_learning_v1"', '"policy_version": "other"')]),
    json.dumps(['paper_source_learning_v1:{"policy_version":"paper_source_learning_v1","policy_action":"CONTROL","policy_action":"ADAPTIVE","policy_probability":1}'])])
def test_invalid_or_ambiguous_policy_tag_does_not_crash(tags):
    result = report.parse_policy_tag(tags)
    assert result["status"] == result["policy_version"] == result["policy_action"] == "INVALID_TAG"
    assert result["policy_probability"] is None


def test_profile_policy_groups_and_invalid_counts_partition_rows(tmp_path):
    rows = [_row(trade_id="a", learning_source="x_paper_probe_v2", tags_json=json.dumps([_policy_tag()])),
            _row(trade_id="c", learning_source="x_closed_v2", tags_json=json.dumps([_policy_tag("CONTROL", 1.)])),
            _row(trade_id="n", learning_source="x_v1"),
            _row(trade_id="i", learning_source="x", tags_json="broken")]
    loaded = report.load_rows(json_path=_json_rows(tmp_path, rows))
    original = json.dumps(loaded, sort_keys=True)
    data = report.build_report(loaded)
    assert json.dumps(loaded, sort_keys=True) == original
    assert {k: v['n'] for k, v in data['by_profile'].items()} == {
        'paper_probe_v2': 1, 'closed_v2': 1, 'v1': 1, 'UNKNOWN_PROFILE': 1}
    assert data['policy_tag_counts'] == dict(OK=2, NO_POLICY=1, INVALID_TAG=1)
    assert sum(g['n'] for actions in data['by_policy'].values() for g in actions.values()) == 4
    experiment = data['experiments']['paper_source_learning_v1']
    assert experiment['verdict']['adaptive']['n'] == experiment['verdict']['control']['n'] == 1
    assert data['by_policy']['paper_source_learning_v1']['ADAPTIVE']['policy_probability']['mean'] == .3
    assert set(data['daily'][0]['by_policy_action']) == {'ADAPTIVE','CONTROL','NO_POLICY','INVALID_TAG'}
    assert sum(x['n'] for x in data['daily'][0]['by_policy_action'].values()) == 4


def test_side_aware_calibration_known_correlations_and_quintiles(tmp_path):
    rows = []
    for index in range(1, 11):
        direction = 1 if index % 2 else -1
        rows.append(_row(trade_id=str(index), side='BUY' if direction == 1 else 'SELL',
                         predicted_gross_move_bps=index, exit_price=100 * (1 + direction*(2*index+1)/10000)))
    data = report.build_report(report.load_rows(json_path=_json_rows(tmp_path, rows)))['total']['calibration']
    assert data['status'] == 'OK' and data['n'] == 10
    assert data['mean_error_bps'] == pytest.approx(-6.5)
    assert data['mean_absolute_error_bps'] == pytest.approx(6.5)
    assert data['pearson'] == pytest.approx(1.) and data['spearman'] == pytest.approx(1.)
    assert [q['n'] for q in data['quintiles']] == [2]*5
    assert [q['mean_predicted_bps'] for q in data['quintiles']] == [1.5,3.5,5.5,7.5,9.5]
    assert [q['mean_realized_bps'] for q in data['quintiles']] == pytest.approx([4,8,12,16,20])


def test_calibration_ties_use_average_ranks_and_constant_is_undefined():
    assert report._ranks([1.,1.,2.,3.,3.]) == [1.5,1.5,3.,4.5,4.5]
    rows = [_row(predicted_gross_move_bps=p, exit_price=100*(1+r/10000))
            for p, r in zip([1,1,2,3,3],[1,2,2,3,3])]
    data = report._calibration(rows)
    assert data['spearman'] == pytest.approx(11/12)
    constant = report._calibration([_row(predicted_gross_move_bps=1,exit_price=100*(1+i/10000)) for i in range(5)])
    assert constant['pearson'] is constant['spearman'] is None
    assert [q['n'] for q in constant['quintiles']] == [5,0,0,0,0]
    assert constant['quintiles'][1]['mean_realized_bps'] is None


def test_calibration_small_n_is_no_data_but_preserves_legacy_descriptive_fields():
    data = report._calibration([_row()]*4)
    assert data['status'] == 'NO_DATA' and data['n'] == 4
    assert data['pearson'] is data['spearman'] is None and data['quintiles'] == []
    assert data['mean_predicted_gross_bps'] == 35  # previous output contract
    missing = report._calibration([_row(predicted_gross_move_bps=None)]*5)
    assert missing['n'] == 0 and missing['mean_error_bps'] is None


def test_joint_day_bootstrap_preserves_cross_arm_daily_dependence(tmp_path):
    a = [_row(entry_ts=1,exit_ts=100,pnl_pct=.1),_row(entry_ts=1,exit_ts=101,pnl_pct=.1),
         _row(entry_ts=1,exit_ts=86500,pnl_pct=1.1)]
    c = [_row(entry_ts=1,exit_ts=100,pnl_pct=0),_row(entry_ts=1,exit_ts=101,pnl_pct=0),
         _row(entry_ts=1,exit_ts=86500,pnl_pct=1)]
    ar = report.load_rows(json_path=_json_rows(tmp_path, a))
    cr = report.load_rows(json_path=_json_rows(tmp_path, c))
    result = report.day_block_difference(ar, cr)
    assert result == report.day_block_difference(ar[::-1], cr[::-1])
    assert result['lower_bps'] == pytest.approx(10) and result['upper_bps'] == pytest.approx(10)
    assert result['shared_blocks'] == 2 and result['valid_replicates'] == 2000
    assert result['skipped_replicates'] == 0


def test_joint_day_bootstrap_never_imputes_missing_arm_as_zero(tmp_path):
    a = report.load_rows(json_path=_json_rows(tmp_path, [_row(entry_ts=1,exit_ts=100,pnl_pct=.05)]))
    c = report.load_rows(json_path=_json_rows(tmp_path, [_row(entry_ts=1,exit_ts=86500,pnl_pct=-.05)]))
    result = report.day_block_difference(a, c)
    assert result['shared_blocks'] == 0 and result['limited_blocks'] is True
    assert 0 < result['valid_replicates'] < 2000
    assert result['valid_replicates']+result['skipped_replicates'] == 2000
    assert result['lower_bps'] == result['upper_bps'] == 10
    assert report.day_block_difference(a, [])['status'] == 'NO_DATA'


def test_json_since_is_inclusive_entry_filter_and_daily_series_uses_utc_exit(tmp_path):
    rows = [_row(entry_ts=1,exit_ts=86399,pnl_pct=-.1),_row(trade_id='new',entry_ts=2,exit_ts=86400,pnl_pct=.2)]
    source = _json_rows(tmp_path, rows)
    output = tmp_path/'out'
    report.main(['--json',str(source),'--since','2','--out',str(output)])
    data = json.loads((output/'report.json').read_text(encoding='utf-8'))
    assert data['total']['n'] == 1 and data['since_entry_ts'] == 2
    assert data['daily'] == [dict(day_utc='1970-01-02',n=1,mean_net_bps=20.,
                                 by_policy_action={'NO_POLICY':dict(n=1,mean_net_bps=20.)})]


def test_new_evidence_report_reference_values_and_signed_predictions(tmp_path):
    source = EVIDENCE.with_name('epoch_20260925_closed_trades_20261026.json')
    before = source.read_bytes()
    output = tmp_path/'out'
    report.main(['--json',str(source),'--out',str(output)])
    data = json.loads((output/'report.json').read_text(encoding='utf-8'))
    assert data['total']['n'] == 267
    assert data['total']['mean_net_bps'] == pytest.approx(-10.209588,abs=.01)
    assert data['policy_tag_counts'] == dict(OK=154,NO_POLICY=113,INVALID_TAG=0)
    assert {k:v['n'] for k,v in data['by_profile'].items()} == {'v1':123,'paper_probe_v2':144}
    policy = data['by_policy']['paper_source_learning_v1']
    for action,n,mean in [('ADAPTIVE',59,-7.81),('CONTROL',68,-12.142941),('PROBE',9,-11.518889),('WARMUP',13,7.439231)]:
        assert policy[action]['n'] == n
        assert policy[action]['mean_net_bps'] == pytest.approx(mean,abs=.01)
    neural = data['by_policy']['paper_source_learning_stonkfly_v1']['WARMUP']
    assert neural['n'] == 5 and neural['mean_net_bps'] == pytest.approx(-17.23,abs=.01)
    verdict = data['experiments']['paper_source_learning_v1']['verdict']
    assert verdict['codes'] == ['ADAPTIVE_NO_EDGE','CONTROL_NO_EDGE','EFFECT_INSUFFICIENT_DATA']
    assert verdict['diff_low_bps'] == pytest.approx(-2.1725,abs=.01)
    assert verdict['diff_high_bps'] == pytest.approx(10.83838,abs=.01)
    expected = {
        'trend_cost_aware_paper_probe_v2': (84,1.8412637,-12.591624,-1.7505824,-.18298),
        'sideways_mean_reversion_paper_probe_v2': (53,7.1672775,-7.2386506,-1.3597333,.18790),
        'volatility_breakout_v1': (9,27.7846258,11.6946974,4.8388086,.13171),
        'sideways_mean_reversion_v1': (8,19.524342,4.9552403,-1.1658169,-.68823),
        'volatility_breakout_paper_probe_v2': (7,19.7277983,2.5109609,9.2671602,.32437)}
    for name,(n,gross,net,realized,corr) in expected.items():
        calibration = data['by_learning_source'][name]['calibration']
        assert calibration['n'] == n and calibration['status'] == 'OK'
        for field,value in [('mean_predicted_gross_bps',gross),('mean_predicted_net_bps',net),('mean_realized_gross_bps',realized)]:
            assert calibration[field] == pytest.approx(value,abs=.01)
        assert calibration['pearson'] == pytest.approx(corr,abs=.05)
        assert sum(q['n'] for q in calibration['quintiles']) == n
    assert sum(day['n'] for day in data['daily']) == 267
    assert all(sum(g['n'] for g in day['by_policy_action'].values()) == day['n'] for day in data['daily'])
    md = (output/'report.md').read_text(encoding='utf-8')
    assert 'EFFECT_INSUFFICIENT_DATA' in md and 'Spearman' in md and 'Kvintil' in md
    assert source.read_bytes() == before
