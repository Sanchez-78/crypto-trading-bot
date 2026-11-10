import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import cost_and_learning_review as review  # noqa: E402

SCRIPT = ROOT / "scripts" / "research" / "cost_and_learning_review.py"


def _stats(gross, lo9, hi9):
    # Frozen screen format: n lives on the hypothesis, not on the target.
    return {"gross_bps": gross, "ci95_net9": [lo9, hi9]}


def _sens(gross, lo9, hi9):
    return review.sensitivity({"n": 300, **_stats(gross, lo9, hi9)}, "x")


def _report(gross=1.0):
    block = {"coverage": [{"sources": {"futures": {"missing_ranges": [{"count": 1}]},
                                       "metrics": {"missing_ranges": []}}}],
             "statistics": {"H1": {"n": 300, "r15": _stats(gross, -9.5, -6.5), "tpsl": _stats(0.2, -9.2, -8.4)}}}
    return {"TRAIN": block, "TEST": block, "HOLDOUT": block}


def _c1(verdict="CONTRARIAN_CONFIRMED", upper_n=520, lower_n=480):
    return {"verdict": verdict, "scored_after_ms": 1, "scored_trade_ids": ["a", "b", "c"],
            "variants": {"C1_contrarian": {"lift_bps": 4.0, "lift_low_bps": 0.5, "lift_high_bps": 7.5,
                                           "upper_n": upper_n, "lower_n": lower_n,
                                           "day_bootstrap": {"blocks": 28, "lower_bps": 0.3, "upper_bps": 7.9}}}}


def _write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def test_unit_conversion_and_round_trip():
    assert review.pct_to_bps(0.0008) == pytest.approx(8.0)
    assert review.pct_to_bps(0.0001) == pytest.approx(1.0)
    assert review.round_trip_bps(10.0) == 20.0
    with pytest.raises(review.ReviewError):
        review.pct_to_bps(float("nan"))


def test_net_is_gross_minus_cost_and_spread_not_subtracted_again():
    s = _sens(1.0, -9.5, -6.5)
    assert s["net"]["9"]["mean_bps"] == pytest.approx(-8.0)
    assert s["net"]["18"]["mean_bps"] == pytest.approx(-17.0)
    # Only the constant cost is subtracted: no separate spread term exists.
    assert s["net"]["0"]["mean_bps"] == pytest.approx(s["gross_bps"])


def test_two_point_breakeven_is_labelled_approximation():
    w = review.two_point_breakeven_wr(9.0)
    assert w["wr_be"] == pytest.approx(34 / 60)
    assert review.two_point_breakeven_wr(18.0)["wr_be"] == pytest.approx(43 / 60)
    assert w["status"] == "APPROXIMATION_TWO_POINT" and w["invalid_with_timeouts"] is True


def test_ci_is_shifted_not_rebootstrapped():
    s = _sens(1.0, -9.5, -6.5)
    assert s["gross_ci95"] == [pytest.approx(-0.5), pytest.approx(2.5)]
    assert s["net"]["18"]["ci95"] == [pytest.approx(-18.5), pytest.approx(-15.5)]
    assert s["conservative_budget_from_ci_low_bps"] == pytest.approx(-3.5)
    assert s["cost_budget_with_reserve_bps"] == pytest.approx(-2.0)


def test_mean_only_does_not_yield_wr_pf_or_drawdown():
    s = _sens(1.0, -9.5, -6.5)
    flat = json.dumps(s)
    for key in ("wr", "profit_factor", "drawdown"):
        assert key not in flat


def test_positive_lift_with_negative_net_is_not_profitability(tmp_path):
    c1 = review.c1_section(_c1(), None)
    assert c1["status"] == "CONTRARIAN_CONFIRMED"
    assert c1["profitability"] == "NOT_VERIFIED"
    q = review.four_questions(c1, 0)
    assert q[2]["status"] == "NOT_VERIFIED" and q[3]["status"] == "NO"


def test_unequal_median_groups_and_mu_validation():
    split = review.split_means(-9.0, 4.0, 600, 400)
    assert split["q"] == pytest.approx(0.6)
    assert split["mean_upper_bps"] == pytest.approx(-9.0 + 0.4 * 4.0)
    assert split["mean_lower_bps"] == pytest.approx(-9.0 - 0.6 * 4.0)
    assert "ci95" not in split
    good = review.c1_section(_c1(), None)["scored_set_sha256"]
    out = review.c1_section(_c1(), {"scored_set_sha256": good, "mu_bps": -9.0})
    assert out["split"]["q"] == pytest.approx(520 / 1000)
    with pytest.raises(review.ReviewError):
        review.c1_section(_c1(), {"scored_set_sha256": "other", "mu_bps": -9.0})


@pytest.mark.parametrize("verdict", [None, "PENDING", "INSUFFICIENT_DATA", "WHATEVER"])
def test_pending_or_unverified_c1_stays_closed(verdict):
    payload = None if verdict is None else {"verdict": verdict}
    c1 = review.c1_section(payload, None)
    assert c1["status"] == "PENDING" and c1["post_cutoff_outcomes_opened"] is False


def test_final_c1_without_scored_ids_is_rejected():
    bad = _c1()
    bad.pop("scored_trade_ids")
    with pytest.raises(review.ReviewError):
        review.c1_section(bad, None)


def test_bootstrap_blocks_not_labelled_days(tmp_path):
    out = tmp_path / "o"
    review.main(["--futures-report", str(_write(tmp_path, "r.json", _report())),
                 "--c1-result", str(_write(tmp_path, "c1.json", _c1())), "--out", str(out)])
    data = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert data["c1"]["bootstrap_unit"] == "6h UTC blocks"
    assert "6h bloky" in (out / "review.md").read_text(encoding="utf-8")


def test_deterministic_provenance_and_bad_inputs(tmp_path):
    report = _write(tmp_path, "r.json", _report())
    a, b = tmp_path / "a", tmp_path / "b"
    review.main(["--futures-report", str(report), "--out", str(a)])
    review.main(["--futures-report", str(report), "--out", str(b)])
    assert (a / "review.json").read_bytes() == (b / "review.json").read_bytes()
    data = json.loads((a / "review.json").read_text(encoding="utf-8"))
    assert len(data["inputs"]["futures_report_sha256"]) == 64 and data["c1"]["status"] == "PENDING"
    assert data["coverage_gap_ranges"] == 3
    (tmp_path / "nan.json").write_text('{"x": NaN}', encoding="utf-8")
    (tmp_path / "dup.json").write_text('{"x": 1, "x": 2}', encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"x": ', encoding="utf-8")
    for name in ("nan.json", "dup.json", "bad.json"):
        with pytest.raises(review.ReviewError):
            review.load_json(tmp_path / name)
    broken = _report()
    broken["HOLDOUT"] = {"statistics": {"H1": {"n": -1, "r15": _stats(1, 0, 1),
                                               "tpsl": _stats(0, -1, 1)}}}
    with pytest.raises(review.ReviewError):
        review.futures_cost_table(broken)


def test_refuses_to_overwrite_input_or_existing_output(tmp_path):
    out = tmp_path / "o"
    out.mkdir()
    report = out / "review.json"
    report.write_text(json.dumps(_report()), encoding="utf-8")
    with pytest.raises(review.ReviewError):
        review.main(["--futures-report", str(report), "--out", str(out)])
    assert json.loads(report.read_text(encoding="utf-8")) == _report()
    frozen = tmp_path / "frozen"
    frozen.mkdir()
    (frozen / "review.md").write_text("frozen", encoding="utf-8")
    with pytest.raises(review.ReviewError):
        review.main(["--futures-report", str(_write(tmp_path, "r.json", _report())), "--out", str(frozen)])
    assert (frozen / "review.md").read_text(encoding="utf-8") == "frozen"


def test_no_runtime_db_executor_firebase_or_network_imports():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= {"__future__", "argparse", "hashlib", "json", "math", "sys", "pathlib", "typing"}
