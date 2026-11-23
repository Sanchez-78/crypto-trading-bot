"""deploy_env_check: effective env in the order the running bot sees it (review 77, P1)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deploy" / "research_eval"))
import deploy_env_check as dec  # noqa: E402

FLAG = "PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED"
BASE = "TRADING_MODE=paper_train ENABLE_REAL_ORDERS=false LIVE_TRADING_CONFIRMED=false"


def _files(tmp_path, text, ignore="no"):
    path = tmp_path / "unit.env"
    path.write_text(text, encoding="utf-8")
    return f"{path} (ignore_errors={ignore})"


def environ(**kv):
    return "\0".join(f"{k}={v}" for k, v in kv.items()).encode() + b"\0"


def test_planned_value_accepted_without_overrides():
    env = dec.preflight(BASE, "", f"{FLAG}=true", "PAPER_TP_ZONE_BPS=35\n")
    assert env[FLAG] == "true" and env["PAPER_TP_ZONE_BPS"] == "35"


def test_new_managed_dropin_beats_older_environment_value():
    # deploy_bot_files.sh guarantees the managed drop-in sorts last, so it replaces earlier
    # Environment= values (including its own previous version) of the same key.
    env = dec.preflight(f"{BASE} {FLAG}=false", "", f"{FLAG}=true", "")
    assert env[FLAG] == "true"


def test_environment_file_false_overrides_planned_true_is_refused(tmp_path):
    with pytest.raises(dec.Refused, match="EnvironmentFile also sets"):
        dec.preflight(BASE, _files(tmp_path, f"{FLAG}=false\n"), f"{FLAG}=true")


@pytest.mark.parametrize("text", [f"{FLAG}=false\n", f"{FLAG}=ture\n", f"export {FLAG}=true\n"])
def test_dotenv_setting_the_planned_key_is_refused(text):
    with pytest.raises(dec.Refused, match="dotenv"):
        dec.preflight(BASE, "", f"{FLAG}=true", text)


def test_environment_file_overrides_environment_for_invariants(tmp_path):
    with pytest.raises(dec.Refused, match="TRADING_MODE"):
        dec.preflight(BASE, _files(tmp_path, "TRADING_MODE=live\n"), f"{FLAG}=true")


def test_dotenv_only_fills_missing_keys():
    env = dec.preflight(BASE, "", "", "TRADING_MODE=live\nENABLE_REAL_ORDERS=true\nX=1\n")
    assert env["TRADING_MODE"] == "paper_train" and env["ENABLE_REAL_ORDERS"] == "false" and env["X"] == "1"
    filled = dec.preflight("ENABLE_REAL_ORDERS=false", "", "", "TRADING_MODE=paper_train\n")
    assert filled["TRADING_MODE"] == "paper_train"


@pytest.mark.parametrize("value", ["True", "1", "yes", "on", ""])
def test_flag_must_be_literal_true_or_false(value):
    with pytest.raises(dec.Refused, match="true or false"):
        dec.preflight(BASE, "", f"{FLAG}={value}" if value else f"{FLAG}=", "")


def test_real_trading_flags_refused():
    with pytest.raises(dec.Refused, match="ENABLE_REAL_ORDERS"):
        dec.preflight("TRADING_MODE=paper_train ENABLE_REAL_ORDERS=true", "", "", "")


def test_env_files_parsing(tmp_path):
    missing = tmp_path / "missing.env"
    assert dec.preflight(BASE, f"{missing} (ignore_errors=yes)", "", "")
    with pytest.raises(dec.Refused, match="missing"):
        dec.preflight(BASE, f"{missing} (ignore_errors=no)", "", "")
    with pytest.raises(dec.Refused, match="parse"):
        dec.preflight(BASE, "garbage-without-flags", "", "")
    # review 78 R2: a recognised item followed by an unparsed remainder is refused too
    with pytest.raises(dec.Refused, match="parse"):
        dec.env_files(f"{missing} (ignore_errors=yes) GARBAGE")
    two = dec.env_files(f"{missing} (ignore_errors=yes) {missing}.b (ignore_errors=no)")
    assert [flag for _, flag in two] == [True, False]


def test_postcheck_reads_the_real_process_environment():
    good = environ(TRADING_MODE="paper_train", ENABLE_REAL_ORDERS="false", LIVE_TRADING_CONFIRMED="false",
                   **{FLAG: "true"})
    assert dec.postcheck(good, f"{FLAG}=true")[FLAG] == "true"
    stale = environ(TRADING_MODE="paper_train", **{FLAG: "false"})
    with pytest.raises(dec.Refused, match="running process"):
        dec.postcheck(stale, f"{FLAG}=true")
    with pytest.raises(dec.Refused, match="running process"):
        dec.postcheck(environ(TRADING_MODE="paper_train"), f"{FLAG}=true")


def test_postcheck_invariants_with_dotenv_fill():
    proc = environ(**{FLAG: "true"})
    assert dec.postcheck(proc, f"{FLAG}=true", "TRADING_MODE=paper_train\n")
    with pytest.raises(dec.Refused, match="LIVE_TRADING_CONFIRMED"):
        dec.postcheck(environ(TRADING_MODE="paper_train", LIVE_TRADING_CONFIRMED="true", **{FLAG: "true"}),
                      f"{FLAG}=true")


CHECK_DIR = Path(__file__).resolve().parents[1] / "deploy" / "research_eval"
MOD = "src/services/candidate.py"
SRC = b"VALUE = 'pinned'\n"


def _tree(tmp_path, content=SRC):
    services = tmp_path / "tree" / "src" / "services"
    services.mkdir(parents=True)
    (tmp_path / "tree" / "src" / "__init__.py").write_bytes(b"")
    (services / "__init__.py").write_bytes(b"")
    (tmp_path / "tree" / MOD).write_bytes(content)
    (tmp_path / "pycache").mkdir()
    return tmp_path / "tree", tmp_path / "pycache"


def _run_optimized(tree, prefix, pinned_hash, *, extra_path=None, use_prefix=True):
    """Run verify_staged_import under -O and PYTHONOPTIMIZE=2 (asserts stripped)."""
    import os
    import subprocess
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2])\n"
        + ("sys.path.insert(0, sys.argv[5])\n" if extra_path else "")
        + "import deploy_env_check as d\n"
        "try:\n"
        "    d.verify_staged_import(sys.argv[2], [sys.argv[3]], {sys.argv[3]: sys.argv[4]}, sys.argv[6])\n"
        "except d.Refused as e:\n"
        "    print('REFUSED', e); sys.exit(2)\n"
        "print('OK')\n")
    args = [sys.executable, "-O", "-B"]
    if use_prefix:
        args += ["-X", f"pycache_prefix={prefix}"]
    args += ["-c", code, str(CHECK_DIR), str(tree), MOD, pinned_hash, str(extra_path or ""), str(prefix)]
    env = {**os.environ, "PYTHONOPTIMIZE": "2"}
    env.pop("PYTHONPYCACHEPREFIX", None)
    return subprocess.run(args, capture_output=True, text=True, env=env)


def test_staged_import_accepts_pinned_source_even_when_optimized(tmp_path):
    import hashlib
    tree, prefix = _tree(tmp_path)
    out = _run_optimized(tree, prefix, hashlib.sha256(SRC).hexdigest())
    assert out.returncode == 0 and "OK" in out.stdout, out.stdout + out.stderr


def test_staged_import_refuses_wrong_hash_when_optimized(tmp_path):
    tree, prefix = _tree(tmp_path)
    out = _run_optimized(tree, prefix, "0" * 64)
    assert out.returncode == 2 and "tree bytes differ" in out.stdout


def test_staged_import_refuses_module_loaded_elsewhere_when_optimized(tmp_path):
    import hashlib
    tree, prefix = _tree(tmp_path)
    shadow = tmp_path / "shadow" / "src" / "services"
    shadow.mkdir(parents=True)
    (tmp_path / "shadow" / "src" / "__init__.py").write_bytes(b"")
    (shadow / "__init__.py").write_bytes(b"")
    (shadow / "candidate.py").write_bytes(b"VALUE = 'shadow'\n")
    out = _run_optimized(tree, prefix, hashlib.sha256(SRC).hexdigest(), extra_path=tmp_path / "shadow")
    assert out.returncode == 2 and "imported elsewhere" in out.stdout


def test_staged_import_refuses_without_dedicated_pycache_prefix(tmp_path):
    import hashlib
    tree, prefix = _tree(tmp_path)
    out = _run_optimized(tree, prefix, hashlib.sha256(SRC).hexdigest(), use_prefix=False)
    assert out.returncode == 2 and "pycache prefix" in out.stdout


def test_validator_has_no_asserts_and_runs_isolated():
    import ast
    import re
    script = (CHECK_DIR / "deploy_bot_files.sh").read_text(encoding="utf-8")
    heredoc = re.search(r"<<'PY'\n(.*?)\nPY\n", script, re.S).group(1)
    assert not [n for n in ast.walk(ast.parse(heredoc)) if isinstance(n, ast.Assert)]
    module = ast.parse((CHECK_DIR / "deploy_env_check.py").read_text(encoding="utf-8"))
    assert not [n for n in ast.walk(module) if isinstance(n, ast.Assert)]
    assert '/usr/bin/python3 -I -B -X pycache_prefix="$SCRATCH/pycache" -' in script


def test_cli_exit_codes(tmp_path, capsys):
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{FLAG}=false\n", encoding="utf-8")
    assert dec.main(["pre", "--environment", BASE, "--env-files", "", "--vars", f"{FLAG}=true",
                     "--dotenv", str(dotenv)]) == 2
    proc = tmp_path / "environ"
    proc.write_bytes(environ(TRADING_MODE="paper_train", **{FLAG: "true"}))
    assert dec.main(["post", "--environ", str(proc), "--vars", f"{FLAG}=true",
                     "--dotenv", str(tmp_path / "absent")]) == 0


# 2026-11-23: RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED is a strict bool (the bot treats unknown values as off).
ECON_FLAG = "RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED"


@pytest.mark.parametrize("value", ["true", "false"])
def test_econ_bad_log_limit_flag_accepts_true_false(value):
    env = dec.preflight(BASE, "", f"{ECON_FLAG}={value}", "")
    assert env[ECON_FLAG] == value


@pytest.mark.parametrize("value", ["1", "yes", "on", "TRUE", "True", "", "maybe"])
def test_econ_bad_log_limit_flag_refuses_anything_else(value):
    with pytest.raises(dec.Refused):
        dec.preflight(BASE, "", f"{ECON_FLAG}={value}", "")


# 2026-11-23 review A1: ALLOW_OPEN_POSITIONS must check the executor's canonical state, not len(json).
import json as _json


def _pos(tid, **over):
    """Shape of open_paper_position()'s canonical record (economic fields; P0.8+ path stores max_hold_s null)."""
    base = {
        "trade_id": tid, "mode": "paper_live", "symbol": "BTCUSDT", "side": "BUY",
        "entry_price": 100.0, "entry_ts": 1795434294.6, "created_at": 1795434294.6, "size_usd": 7.5,
        "paper_cost_contract_version": 1, "paper_fee_round_trip_fraction": 0.0008,
        "paper_slippage_round_trip_fraction": 0.0002, "tp": 100.35, "sl": 99.7,
        "timeout_s": 1200.0, "max_hold_s": None, "explore_bucket": "P0_8_PLUS_EVIDENCE_COLLECTION",
        "max_seen": 100.0, "min_seen": 100.0, "regime": "BULL_TREND",
        "training_bucket": None, "paper_source": "p0_8_plus",
    }
    base.update(over)
    return base


def _short(tid, **over):
    return _pos(tid, side="SELL", tp=99.65, sl=100.3, **over)


def _without(pos, field):
    return {k: v for k, v in pos.items() if k != field}


def test_open_positions_count_accepts_canonical_state():
    state = {"paper_decision_a": _pos("paper_decision_a"), "paper_decision_b": _short("paper_decision_b"),
             "paper_decision_c": _pos("paper_decision_c", max_hold_s=300, training_bucket="A_STRICT_TAKE",
                                      paper_source="strict_take"),
             "paper_decision_d": _pos("paper_decision_d", max_hold_s=300, training_bucket="C_WEAK_EV_TRAIN",
                                      paper_source="training_sampler")}
    assert dec.open_positions_count(_json.dumps(state)) == 4
    assert dec.open_positions_count("{}") == 0


_ECON_REQUIRED = ("side", "size_usd", "tp", "sl", "max_hold_s", "timeout_s", "paper_cost_contract_version",
                  "paper_fee_round_trip_fraction", "paper_slippage_round_trip_fraction")


@pytest.mark.parametrize("field", _ECON_REQUIRED)
def test_open_positions_count_refuses_missing_economic_field(field):
    # Review R1: the loader would fill these in (side -> BUY flips a short to a long).
    for pos in (_pos("t"), _short("t")):
        with pytest.raises(dec.Refused):
            dec.open_positions_count(_json.dumps({"t": _without(pos, field)}))


@pytest.mark.parametrize("over", [
    {"side": "LONG"}, {"side": "buy"}, {"side": None},
    {"size_usd": 0}, {"size_usd": -1}, {"size_usd": "7.5"}, {"size_usd": True},
    {"tp": 0}, {"tp": None}, {"sl": 0}, {"sl": None}, {"timeout_s": 0}, {"timeout_s": None},
    {"tp": 99.0}, {"sl": 101.0}, {"tp": 100.0},                       # wrong side of entry for BUY
    {"max_hold_s": 0}, {"max_hold_s": -5}, {"max_hold_s": "300"},
    {"paper_cost_contract_version": 2}, {"paper_fee_round_trip_fraction": -0.1},
    {"paper_slippage_round_trip_fraction": None},
])
def test_open_positions_count_refuses_bad_economic_value(over):
    with pytest.raises(dec.Refused):
        dec.open_positions_count(_json.dumps({"t": _pos("t", **over)}))


def test_open_positions_count_refuses_short_with_long_geometry():
    with pytest.raises(dec.Refused):
        dec.open_positions_count(_json.dumps({"t": _pos("t", side="SELL")}))


@pytest.mark.parametrize("pos", [
    _pos("t", paper_source="training_sampler", training_bucket=None),      # loader would set the bucket
    _without(_pos("t", training_bucket="C_WEAK_EV_TRAIN"), "created_at"),   # loader would set created_at
])
def test_open_positions_count_refuses_incomplete_training_position(pos):
    with pytest.raises(dec.Refused):
        dec.open_positions_count(_json.dumps({"t": pos}))


def test_accepted_records_load_without_economic_change(monkeypatch, tmp_path):
    """Cross-check against the real loader: every accepted record reloads with its economic fields intact."""
    import copy
    from src.services import paper_trade_executor as pte
    from src.services.paper_close_journal import PaperCloseJournal
    state = {"a": _pos("a"), "b": _short("b"),
             "c": _pos("c", max_hold_s=300, training_bucket="C_WEAK_EV_TRAIN", paper_source="training_sampler",
                       timeout_s=300.0),
             # Training record whose stored timeout the loader really shortens (review R1 test gap).
             "d": _pos("d", max_hold_s=300, training_bucket="C_WEAK_EV_TRAIN", paper_source="training_sampler",
                       timeout_s=1200.0)}
    assert dec.open_positions_count(_json.dumps(state)) == 4
    path = tmp_path / "paper_open_positions.json"
    path.write_text(_json.dumps(state), encoding="utf-8")
    monkeypatch.setattr(pte, "_STATE_FILE", str(path))
    monkeypatch.setattr(pte, "_POSITIONS", {})

    class _NoCloses:
        def closed_ids(self, _ids):
            return set()

    monkeypatch.setattr(pte, "_paper_close_journal", lambda: _NoCloses())
    monkeypatch.setattr(pte, "_save_paper_state", lambda *_a, **_k: True)
    monkeypatch.setattr(pte, "_reconcile_stale_paper_positions", lambda *_a, **_k: {})
    before = copy.deepcopy(state)
    pte._load_paper_state()
    assert set(pte._POSITIONS) == set(before)
    journal = PaperCloseJournal(tmp_path / "paper_close_journal.sqlite")
    for tid, orig in before.items():
        loaded = pte._POSITIONS[tid]
        for field in ("symbol", "entry_price", "entry_ts", "created_at") + _ECON_REQUIRED:
            if tid == "d" and field == "timeout_s":
                continue
            assert loaded.get(field) == orig.get(field), (tid, field)
        assert pte._effective_paper_hold_s(loaded) == pte._effective_paper_hold_s(orig), tid
        assert pte._paper_cost_fractions(loaded) == (orig["paper_fee_round_trip_fraction"],
                                                     orig["paper_slippage_round_trip_fraction"])
        # Review R2: an accepted record must be closable into the authoritative journal.
        assert journal.prepare({**loaded, "trade_id": tid}, loaded, {"net_pnl_pct": 0.0})["trade_id"] == tid
    assert pte._POSITIONS["d"]["timeout_s"] == 300.0 < before["d"]["timeout_s"]   # the shortening did happen


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
@pytest.mark.parametrize("where", ["nested", "top_optional"])
def test_open_positions_count_refuses_non_finite_anywhere(literal, where, tmp_path):
    # Review R3: json.loads accepts these; the journal's json.dumps(allow_nan=False) would refuse the close.
    from src.services.paper_close_journal import PaperCloseJournal
    good = _pos("t", features={"x": 1.0})
    text = _json.dumps({"t": good}).replace('{"x": 1.0}', '{"x": %s}' % literal if where == "nested"
                                             else '{"x": 1.0}, "score_at_entry": %s' % literal)
    assert text != _json.dumps({"t": good})
    with pytest.raises(dec.Refused):
        dec.open_positions_count(text)
    # The same record really is unclosable: the journal refuses it.
    pos = _json.loads(text)["t"]
    with pytest.raises(ValueError):
        PaperCloseJournal(tmp_path / "j.sqlite").prepare(pos, pos, {"net_pnl_pct": 0.0})
    # The finite record passes the validator and the journal.
    assert dec.open_positions_count(_json.dumps({"t": good})) == 1
    assert PaperCloseJournal(tmp_path / "ok.sqlite").prepare(good, good, {"net_pnl_pct": 0.0})["trade_id"] == "t"


@pytest.mark.parametrize("over", [
    # Review R4a: finite but extreme inputs overflow only at settlement (fee * 100, USD P/L).
    {"paper_fee_round_trip_fraction": 1e308}, {"paper_fee_round_trip_fraction": 0.5},
    {"paper_slippage_round_trip_fraction": 1e308}, {"size_usd": 1e308}, {"size_usd": 2e6},
    {"entry_price": 1e300, "tp": 2e300, "max_seen": 1e300, "min_seen": 1e300},
    # Review R4b: fields the tick path compares/subtracts without a guard.
    {"max_seen": "broken"}, {"min_seen": "broken"}, {"max_seen": None}, {"min_seen": -1.0},
    {"_dyn_exit_features_ts": None}, {"_dyn_exit_features_ts": "x"}, {"created_at": "x"},
    {"max_seen_ts": "x"}, {"last_price": "x"}, {"last_price": 0}, {"_dyn_exit_atr_bps": -1},
    {"dynamic_exit_initial_stop": "x"}, {"timeout_s": 1e9}, {"max_hold_s": 1e9},
    {"regime": 5}, {"explore_bucket": 3}, {"paper_source": ["x"]},
])
def test_open_positions_count_refuses_unsafe_tick_or_settlement_field(over):
    with pytest.raises(dec.Refused):
        dec.open_positions_count(_json.dumps({"t": _pos("t", **over)}))


def test_open_positions_count_accepts_nullable_guarded_fields():
    pos = _pos("t", last_price=None, last_price_ts=None, dynamic_exit_initial_stop=None, _dyn_exit_atr_bps=None,
               max_seen_ts=None, min_seen_ts=None, strategy_id=None, training_bucket=None)
    assert dec.open_positions_count(_json.dumps({"t": pos})) == 1
    assert dec.open_positions_count(_json.dumps({"t": _without(_without(pos, "max_seen"), "min_seen")})) == 1


def test_accepted_extremes_keep_settlement_finite(tmp_path):
    """At the validator's upper bounds, the real P/L computation stays finite and journal-serializable."""
    import math
    from src.services import paper_trade_executor as pte
    from src.services.paper_close_journal import PaperCloseJournal
    edge = dict(entry_price=5e8, tp=1e9, sl=1e-6, max_seen=1e9, min_seen=1e-6, size_usd=1e6,
                paper_fee_round_trip_fraction=0.1, paper_slippage_round_trip_fraction=0.1)
    records = {"a": _pos("a"), "b": _short("b"), "e": _pos("e", **edge),
               "s": _pos("s", side="SELL", entry_price=5e8, tp=1e-6, sl=1e9, max_seen=1e9, min_seen=1e-6,
                         size_usd=1e6, paper_fee_round_trip_fraction=0.1, paper_slippage_round_trip_fraction=0.1)}
    assert dec.open_positions_count(_json.dumps(records)) == 4
    journal = PaperCloseJournal(tmp_path / "j.sqlite")
    for tid, pos in records.items():
        fee, slip = pte._paper_cost_fractions(pos)
        for exit_price in (pos["tp"], pos["sl"], pos["max_seen"], pos["min_seen"]):
            pnl = pte._calculate_pnl(side=pos["side"], entry_price=pos["entry_price"], exit_price=exit_price,
                                     size_usd=pos["size_usd"], fee_pct=fee, slippage_pct=slip)
            assert all(math.isfinite(v) for v in pnl.values() if isinstance(v, float)), (tid, exit_price, pnl)
            _json.dumps(pnl, allow_nan=False)
        closed = {**pos, "net_pnl_usd": pnl["net_pnl_pct"] / 100.0 * pos["size_usd"]}
        assert journal.prepare(closed, pos, pnl)["trade_id"] == tid


@pytest.mark.parametrize("key", ["", " ", " t", "t ", "\t"])
def test_open_positions_count_refuses_empty_or_padded_trade_id(key):
    # Review R2: the loader restores an empty id, but the close journal refuses it -> never closable.
    with pytest.raises(dec.Refused):
        dec.open_positions_count(_json.dumps({key: _pos(key)}))


@pytest.mark.parametrize("text", [
    "not json", '"abc"', "42", "[]", '[{"trade_id": "t"}]',               # not a mapping / legacy list
    '{"trade-1": 42}',                                                     # review repro: non-dict record
    '{"positions": {"t": {}}}', '{"metadata": {}}',                        # wrapper / metadata keys
    _json.dumps({"t": _pos("other")}),                                     # trade_id mismatch
    _json.dumps({"t": {k: v for k, v in _pos("t").items() if k != "trade_id"}}),
    _json.dumps({"t": _pos("t", symbol="")}), _json.dumps({"t": _pos("t", symbol=None)}),
    _json.dumps({"t": _pos("t", entry_price=0)}), _json.dumps({"t": _pos("t", entry_price=None)}),
    _json.dumps({"t": _pos("t", entry_price=True)}), _json.dumps({"t": _pos("t", entry_ts=-1)}),
    '{"t": {"trade_id": "t", "symbol": "X", "entry_price": NaN, "entry_ts": 1}}',
])
def test_open_positions_count_refuses_unrestorable_state(text):
    with pytest.raises(dec.Refused):
        dec.open_positions_count(text)


def test_positions_cli_prints_count_or_refuses(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(_json.dumps({"t": _pos("t")}), encoding="utf-8")
    assert dec.main(["positions", "--file", str(good)]) == 0
    assert capsys.readouterr().out.strip() == "1"
    bad = tmp_path / "bad.json"
    bad.write_text('{"trade-1": 42}', encoding="utf-8")
    assert dec.main(["positions", "--file", str(bad)]) == 2
    assert "POSITIONS REFUSED" in capsys.readouterr().err
    assert dec.main(["positions", "--file", str(tmp_path / "missing.json")]) == 2
