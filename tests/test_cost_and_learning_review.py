import ast
import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "research"))

import cost_and_learning_review as review  # noqa: E402

SCRIPT = ROOT / "scripts" / "research" / "cost_and_learning_review.py"
CUTOFF = review.C1_CUTOFF_MS
HOUR = 3_600_000


# ------------------------------------------------------------------ fixtures

def _stats(gross, lo9, hi9):
    # Frozen screen format: n lives on the hypothesis, not on the target.
    return {"gross_bps": gross, "ci95_net9": [lo9, hi9]}


def _sens(gross, lo9, hi9, n=300):
    return review.sensitivity({"n": n, **_stats(gross, lo9, hi9)}, "x")


def _source(expected=100, missing=0):
    gaps = [{"count": missing, "start_ms": 0, "end_exclusive_ms": 60_000 * missing}] if missing else []
    return {"expected_rows": expected, "rows": expected - missing, "missing_rows": missing, "missing_ranges": gaps}


def _coverage(gap_symbol=None):
    out = []
    for sym in review.UNIVERSE:
        missing = 5 if sym == gap_symbol else 0
        out.append({"symbol": sym, "sources": {"futures": _source(missing=missing), "spot": _source(),
                                               "metrics": _source(), "funding": {"rows": 10}}})
    return out


def _report(gross=1.0, gap_symbol=None):
    stats = {h: {"n": 300, "r15": _stats(gross, -9.5, -6.5), "tpsl": _stats(0.2, -9.2, -8.4)}
             for h in review.HYPOTHESES}
    return {b: {"coverage": _coverage(gap_symbol), "statistics": copy.deepcopy(stats)} for b in review.BLOCKS}


def _c1(verdict="CONTRARIAN_CONFIRMED", n=1000, upper_n=None):
    """Internally consistent synthetic final C1 (format of learner_replay.evaluate_preregistered)."""
    upper_n = upper_n if upper_n is not None else n // 2 + 20
    welch, boot = {"CONTRARIAN_CONFIRMED": ((0.5, 7.5), (0.3, 7.9)),
                   "CONTRARIAN_REFUTED": ((-7.5, -0.5), (-7.9, -0.3)),
                   "CONTRARIAN_NOT_SHOWN": ((-1.0, 6.0), (-1.2, 6.5))}[verdict]
    lift = (welch[0] + welch[1]) / 2
    last_entry = CUTOFF + 5 * 24 * HOUR
    return {"verdict": verdict, "scored_after_ms": CUTOFF, "final_n": 1000, "min_days": 7,
            "fresh_n": n + 37, "days_elapsed": 7.4, "scored_last_entry_ms": last_entry,
            "scored_trade_ids": [f"t{i:05d}" for i in range(n)],
            "variants": {"C1_contrarian": {"n": n, "lift_bps": lift, "lift_low_bps": welch[0],
                                           "lift_high_bps": welch[1], "upper_n": upper_n, "lower_n": n - upper_n,
                                           "spearman": 0.1,
                                           "day_bootstrap": {"blocks": 28, "valid": 2000,
                                                             "lower_bps": boot[0], "upper_bps": boot[1]}}}}


def _dump(obj):
    return json.dumps(obj, sort_keys=True).encode("utf-8")


def _final_set(tmp_path, result=None, prov_overrides=None, mu=None):
    """Write result + provenance (+ optional mu); return (paths, trusted reference hash)."""
    result = _c1() if result is None else result
    rbytes = _dump(result)
    prov = {"contract": review.PROVENANCE_CONTRACT, "hypothesis": "C1_contrarian", "scored_after_ms": CUTOFF,
            "run_id": "20261116T174700Z", "evaluated_at_ms": CUTOFF + 7 * 24 * HOUR + 10 * HOUR,
            "result_sha256": hashlib.sha256(rbytes).hexdigest(), "id_hash_convention": review.ID_HASH_CONVENTION}
    prov.update(prov_overrides or {})
    pbytes = _dump(prov)
    (tmp_path / "prereg_result.json").write_bytes(rbytes)
    (tmp_path / "provenance.json").write_bytes(pbytes)
    paths = {"result": tmp_path / "prereg_result.json", "provenance": tmp_path / "provenance.json"}
    if mu is not None:
        (tmp_path / "mu.json").write_bytes(_dump(mu))
        paths["mu"] = tmp_path / "mu.json"
    return paths, hashlib.sha256(pbytes).hexdigest()


def _mu_for(result, **overrides):
    mu = {"contract": review.MU_CONTRACT, "result_sha256": hashlib.sha256(_dump(result)).hexdigest(),
          "scored_set_sha256": review.id_hash(result["scored_trade_ids"]), "scored_after_ms": CUTOFF,
          "unit": "bps", "cost_basis": "paper_net_9bps", "mu_bps": -9.0}
    mu.update(overrides)
    return mu


def _write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


class SpyLoader:
    """Records every file read; reading a forbidden path raises a sentinel immediately."""

    def __init__(self, forbidden=()):
        self.reads = []
        self.forbidden = {Path(p).resolve() for p in forbidden}

    def __call__(self, path):
        if Path(path).resolve() in self.forbidden:
            raise AssertionError(f"SENTINEL: forbidden read of {Path(path).name}")
        self.reads.append(Path(path).name)
        return review.load_json(path)


# ------------------------------------------------------------------ units / arithmetic

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
    flat = json.dumps(_sens(1.0, -9.5, -6.5))
    for key in ("wr", "profit_factor", "drawdown"):
        assert key not in flat


# ------------------------------------------------------------------ F04 intervals / n

def test_f04_zero_sample_is_no_data_without_budgets():
    s = review.sensitivity({"n": 0, "gross_bps": 1.0, "ci95_net9": [5.0, -10.0]}, "x")
    assert s == {"status": "NO_DATA", "n": 0}


def test_f04_reversed_interval_rejected():
    with pytest.raises(review.ReviewError):
        _sens(1.0, 5.0, -10.0, n=10)


@pytest.mark.parametrize("n", [-1, 2.5, True, None, "300"])
def test_f04_invalid_n_rejected(n):
    with pytest.raises(review.ReviewError):
        review.sensitivity({"n": n, **_stats(1.0, -9.5, -6.5)}, "x")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, None])
def test_f04_non_finite_or_bool_values_rejected(bad):
    with pytest.raises(review.ReviewError):
        review.sensitivity({"n": 10, "gross_bps": bad, "ci95_net9": [-9.0, -8.0]}, "x")
    with pytest.raises(review.ReviewError):
        review.sensitivity({"n": 10, "gross_bps": 1.0, "ci95_net9": [bad, -8.0]}, "x")


def test_f04_valid_interval_excluding_point_mean_is_allowed():
    s = _sens(1.0, -5.0, -4.0)  # gross CI [4, 5] does not contain the mean 1.0
    assert s["status"] == "OK" and s["gross_ci95"] == [pytest.approx(4.0), pytest.approx(5.0)]


# ------------------------------------------------------------------ F03 schema / coverage

def test_f03_empty_statistics_rejected():
    empty = {b: {"coverage": _coverage(), "statistics": {}} for b in review.BLOCKS}
    with pytest.raises(review.ReviewError):
        review.futures_cost_table(empty)


@pytest.mark.parametrize("path", [("HOLDOUT",), ("TEST", "statistics", "H4"), ("TRAIN", "statistics", "H7", "tpsl")])
def test_f03_missing_phase_hypothesis_or_target_rejected(path):
    report = _report()
    node = report
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    with pytest.raises(review.ReviewError):
        review.futures_cost_table(report)


def test_f03_conflicting_nested_n_rejected():
    report = _report()
    report["HOLDOUT"]["statistics"]["H1"]["r15"]["n"] = 999
    with pytest.raises(review.ReviewError):
        review.futures_cost_table(report)


def test_f03_complete_coverage_ok_and_documented_gap_partial():
    assert review.coverage_review(_report())["status"] == "OK"
    partial = review.coverage_review(_report(gap_symbol="DOTUSDT"))
    assert partial["status"] == "PARTIAL"
    assert partial["missing_range_count"] == 3 and partial["missing_rows_by_source_interval"] == 15


@pytest.mark.parametrize("mutate", [
    lambda r: r["TEST"].pop("coverage"),
    lambda r: r["TEST"].__setitem__("coverage", []),
    lambda r: r["TEST"]["coverage"].pop(3),
    lambda r: r["TEST"]["coverage"][0]["sources"].pop("metrics"),
    lambda r: r["TEST"]["coverage"][0]["sources"].pop("funding"),
    lambda r: r["TEST"]["coverage"][0]["sources"]["spot"].__setitem__("expected_rows", 0),
])
def test_f03_missing_or_empty_coverage_is_not_ok(mutate):
    report = _report()
    mutate(report)
    out = review.coverage_review(report)
    assert out["status"] == "NOT_VERIFIED" and out["blocks"]["TEST"]["problems"]


def test_f03_inconsistent_gap_fields_rejected():
    report = _report()
    report["TRAIN"]["coverage"][0]["sources"]["futures"]["missing_rows"] = 4  # no ranges listed
    with pytest.raises(review.ReviewError):
        review.coverage_review(report)


def test_f03_public_path_reports_not_verified_coverage(tmp_path):
    report = _report()
    report["HOLDOUT"]["coverage"] = []
    out = tmp_path / "o"
    assert review.cli(["--futures-report", str(_write(tmp_path, "r.json", report)), "--out", str(out)]) == 0
    data = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert data["coverage"]["status"] == "NOT_VERIFIED" and data["four_questions"][0]["status"] == "NOT_VERIFIED"


# ------------------------------------------------------------------ F01 read order / exposure

def test_f01_mu_never_read_without_c1_api_and_cli(tmp_path):
    report = _write(tmp_path, "r.json", _report())
    mu = _write(tmp_path, "mu.json", {"mu_bps": -9.0})
    spy = SpyLoader(forbidden=[mu])
    with pytest.raises(review.BlindingRefusal):
        review.build(report, None, mu, loader=spy)
    assert spy.reads == ["r.json"]
    assert review.cli(["--futures-report", str(report), "--c1-mu", str(mu), "--out", str(tmp_path / "o")]) == 3
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("verdict", ["PENDING", "INSUFFICIENT_DATA"])
def test_f01_mu_never_read_for_non_final_c1(tmp_path, verdict):
    result = {"verdict": verdict, "scored_after_ms": CUTOFF, "final_n": 1000, "min_days": 7, "fresh_n": 204,
              "variants": None}
    paths, ref = _final_set(tmp_path, result=result, mu={"mu_bps": -9.0})
    spy = SpyLoader(forbidden=[paths["mu"]])
    with pytest.raises(review.BlindingRefusal):
        review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                     provenance_path=paths["provenance"], provenance_sha=ref, loader=spy)
    assert "mu.json" not in spy.reads


def test_f01_mu_never_read_without_trusted_reference_and_result_not_opened(tmp_path):
    paths, _ = _final_set(tmp_path, mu={"mu_bps": -9.0})
    spy = SpyLoader(forbidden=[paths["mu"], paths["result"]])
    with pytest.raises(review.BlindingRefusal):
        review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                     provenance_path=paths["provenance"], provenance_sha=None, loader=spy)
    spy2 = SpyLoader(forbidden=[paths["result"]])
    out = review.build(_write(tmp_path, "r2.json", _report()), paths["result"], None,
                       provenance_path=None, provenance_sha=None, loader=spy2)
    assert out["c1"]["status"] == "NOT_VERIFIED" and out["exposure"]["frozen_c1_result_read"] is False


def test_f01_mu_never_read_on_provenance_mismatch(tmp_path):
    paths, _ = _final_set(tmp_path, mu={"mu_bps": -9.0})
    spy = SpyLoader(forbidden=[paths["mu"], paths["result"]])
    with pytest.raises(review.BlindingRefusal):
        review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                     provenance_path=paths["provenance"], provenance_sha="0" * 64, loader=spy)


def test_f01_mu_never_read_for_invalid_final(tmp_path):
    bad = _c1()
    bad["scored_trade_ids"][1] = bad["scored_trade_ids"][0]
    paths, ref = _final_set(tmp_path, result=bad, mu={"mu_bps": -9.0})
    spy = SpyLoader(forbidden=[paths["mu"]])
    with pytest.raises(review.ReviewError) as exc:
        review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                     provenance_path=paths["provenance"], provenance_sha=ref, loader=spy)
    assert "SENTINEL" not in str(exc.value)


def test_f01_read_order_and_exposure_after_valid_c1(tmp_path):
    result = _c1()
    paths, ref = _final_set(tmp_path, result=result, mu=_mu_for(result))
    spy = SpyLoader()
    out = review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                       provenance_path=paths["provenance"], provenance_sha=ref, loader=spy)
    assert spy.reads == ["r.json", "provenance.json", "prereg_result.json", "mu.json"]
    assert out["exposure"] == {"raw_post_cutoff_trades_read": False, "frozen_c1_result_read": True,
                               "frozen_c1_mu_read": True}
    assert out["c1"]["split"]["q"] == pytest.approx(520 / 1000)


def test_f01_json_and_markdown_report_same_exposure(tmp_path):
    out = tmp_path / "o"
    assert review.cli(["--futures-report", str(_write(tmp_path, "r.json", _report())), "--out", str(out)]) == 0
    data = json.loads((out / "review.json").read_text(encoding="utf-8"))
    md = (out / "review.md").read_text(encoding="utf-8")
    assert data["c1"]["status"] == "PENDING" and data["exposure"]["frozen_c1_mu_read"] is False
    assert "zmrazený výsledek C1 ne" in md and "zmrazený agregát mu ne" in md and "PENDING" in md
    assert "post_cutoff_outcomes_opened" not in json.dumps(data)


def test_f01_rejected_mu_error_does_not_echo_values(tmp_path):
    result = _c1()
    paths, ref = _final_set(tmp_path, result=result, mu=_mu_for(result, unit="pct", mu_bps=-123.456))
    with pytest.raises(review.ReviewError) as exc:
        review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                     provenance_path=paths["provenance"], provenance_sha=ref)
    assert "123" not in str(exc.value)


# ------------------------------------------------------------------ F02 provenance / consistency

@pytest.mark.parametrize("verdict", review.C1_FINAL)
def test_f02_each_final_verdict_accepted_when_consistent(tmp_path, verdict):
    paths, ref = _final_set(tmp_path, result=_c1(verdict))
    out = review.build(_write(tmp_path, "r.json", _report()), paths["result"],
                       provenance_path=paths["provenance"], provenance_sha=ref)
    assert out["c1"]["status"] == verdict and out["c1"]["profitability"] == "NOT_VERIFIED"
    assert out["c1"]["bootstrap_unit"] == "6h UTC blocks"


def test_f02_prefix_longer_than_1000_and_unequal_groups(tmp_path):
    result = _c1(n=1137, upper_n=601)
    paths, ref = _final_set(tmp_path, result=result, mu=_mu_for(result))
    out = review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                       provenance_path=paths["provenance"], provenance_sha=ref)
    assert out["c1"]["scored_n"] == 1137
    assert out["c1"]["split"]["q"] == pytest.approx(601 / 1137)


def _broken(mutator):
    result = _c1()
    mutator(result)
    return result


@pytest.mark.parametrize("name,mutator", [
    ("cutoff", lambda r: r.__setitem__("scored_after_ms", 0)),
    ("protocol", lambda r: r.__setitem__("final_n", 300)),
    ("duplicate_ids", lambda r: r["scored_trade_ids"].__setitem__(1, r["scored_trade_ids"][0])),
    ("empty_ids", lambda r: r.__setitem__("scored_trade_ids", [])),
    ("bool_id", lambda r: r["scored_trade_ids"].__setitem__(0, True)),
    ("short_prefix", lambda r: r.__setitem__("scored_trade_ids", r["scored_trade_ids"][:999])),
    ("sum_mismatch", lambda r: r["variants"]["C1_contrarian"].__setitem__("upper_n", 400)),
    ("bool_count", lambda r: r["variants"]["C1_contrarian"].__setitem__("lower_n", True)),
    ("zero_group", lambda r: r["variants"]["C1_contrarian"].update(upper_n=0, lower_n=1000)),
    ("missing_welch", lambda r: r["variants"]["C1_contrarian"].pop("lift_low_bps")),
    ("reversed_welch", lambda r: r["variants"]["C1_contrarian"].update(lift_low_bps=9.0)),
    ("missing_boot", lambda r: r["variants"]["C1_contrarian"]["day_bootstrap"].pop("upper_bps")),
    ("nan_lift", lambda r: r["variants"]["C1_contrarian"].__setitem__("lift_bps", "NaN")),
    ("few_blocks", lambda r: r["variants"]["C1_contrarian"]["day_bootstrap"].__setitem__("blocks", 15)),
    ("fresh_lt_scored", lambda r: r.__setitem__("fresh_n", 10)),
    ("no_last_entry", lambda r: r.pop("scored_last_entry_ms")),
    ("margin_lt_6h", lambda r: r.__setitem__("scored_last_entry_ms", CUTOFF + 7 * 24 * HOUR + 5 * HOUR)),
    ("verdict_vs_ci", lambda r: r.__setitem__("verdict", "CONTRARIAN_REFUTED")),
    ("unknown_verdict", lambda r: r.__setitem__("verdict", "CONFIRMED!")),
])
def test_f02_inconsistent_final_rejected(tmp_path, name, mutator):
    paths, ref = _final_set(tmp_path, result=_broken(mutator))
    with pytest.raises(review.ReviewError):
        review.build(_write(tmp_path, "r.json", _report()), paths["result"],
                     provenance_path=paths["provenance"], provenance_sha=ref)


@pytest.mark.parametrize("override", [
    {"contract": "c1_provenance_v0"}, {"hypothesis": "V2_no_decay"}, {"scored_after_ms": CUTOFF + 1},
    {"run_id": ""}, {"id_hash_convention": "sha1"}, {"evaluated_at_ms": CUTOFF + 6 * 24 * HOUR},
])
def test_f02_bad_provenance_rejected(tmp_path, override):
    paths, ref = _final_set(tmp_path, prov_overrides=override)
    with pytest.raises(review.ReviewError):
        review.build(_write(tmp_path, "r.json", _report()), paths["result"],
                     provenance_path=paths["provenance"], provenance_sha=ref)


def test_f02_result_hash_mismatch_not_verified(tmp_path):
    paths, ref = _final_set(tmp_path, prov_overrides={"result_sha256": "f" * 64})
    out = review.build(_write(tmp_path, "r.json", _report()), paths["result"],
                       provenance_path=paths["provenance"], provenance_sha=ref)
    assert out["c1"]["status"] == "NOT_VERIFIED"


def test_f02_old_artefact_without_provenance_is_not_verified(tmp_path):
    out = tmp_path / "o"
    code = review.cli(["--futures-report", str(_write(tmp_path, "r.json", _report())),
                       "--c1-result", str(_write(tmp_path, "c1.json", _c1())), "--out", str(out)])
    data = json.loads((out / "review.json").read_text(encoding="utf-8"))
    assert code == 0 and data["c1"]["status"] == "NOT_VERIFIED"
    assert data["four_questions"][1]["status"] == "NOT_VERIFIED"


@pytest.mark.parametrize("override", [
    {"scored_set_sha256": "0" * 64}, {"result_sha256": "0" * 64}, {"scored_after_ms": 1},
    {"unit": "pct"}, {"cost_basis": "gross"}, {"contract": "mu_v0"}, {"mu_bps": float("inf")},
])
def test_f02_mu_bound_to_same_result_set_and_units(tmp_path, override):
    result = _c1()
    paths, ref = _final_set(tmp_path, result=result, mu=_mu_for(result, **override))
    with pytest.raises(review.ReviewError):
        review.build(_write(tmp_path, "r.json", _report()), paths["result"], paths["mu"],
                     provenance_path=paths["provenance"], provenance_sha=ref)


def test_unequal_median_groups_split_arithmetic():
    split = review.split_means(-9.0, 4.0, 600, 400)
    assert split["q"] == pytest.approx(0.6)
    assert split["mean_upper_bps"] == pytest.approx(-9.0 + 0.4 * 4.0)
    assert split["mean_lower_bps"] == pytest.approx(-9.0 - 0.6 * 4.0)
    assert "ci95" not in split


def test_positive_lift_never_marks_profitability_pass(tmp_path):
    paths, ref = _final_set(tmp_path)
    out = review.build(_write(tmp_path, "r.json", _report()), paths["result"],
                       provenance_path=paths["provenance"], provenance_sha=ref)
    q = out["four_questions"]
    assert out["c1"]["profitability"] == "NOT_VERIFIED"
    assert q[2]["status"] == "NOT_VERIFIED" and q[3]["status"] == "NO"


def test_id_hash_convention_is_stable():
    assert review.id_hash(["a", "b"]) == hashlib.sha256(b'["a","b"]').hexdigest()


# ------------------------------------------------------------------ regression / I/O safety

def test_deterministic_provenance_and_bad_inputs(tmp_path):
    report = _write(tmp_path, "r.json", _report(gap_symbol="BTCUSDT"))
    a, b = tmp_path / "a", tmp_path / "b"
    review.main(["--futures-report", str(report), "--out", str(a)])
    review.main(["--futures-report", str(report), "--out", str(b)])
    assert (a / "review.json").read_bytes() == (b / "review.json").read_bytes()
    data = json.loads((a / "review.json").read_text(encoding="utf-8"))
    assert len(data["inputs"]["futures_report_sha256"]) == 64 and data["c1"]["status"] == "PENDING"
    assert data["coverage"]["missing_range_count"] == 3
    (tmp_path / "nan.json").write_text('{"x": NaN}', encoding="utf-8")
    (tmp_path / "dup.json").write_text('{"x": 1, "x": 2}', encoding="utf-8")
    (tmp_path / "bad.json").write_text('{"x": ', encoding="utf-8")
    for name in ("nan.json", "dup.json", "bad.json"):
        with pytest.raises(review.ReviewError):
            review.load_json(tmp_path / name)


def test_cli_exit_codes(tmp_path):
    (tmp_path / "bad.json").write_text('{"x": ', encoding="utf-8")
    assert review.cli(["--futures-report", str(tmp_path / "bad.json"), "--out", str(tmp_path / "o")]) == 2


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
