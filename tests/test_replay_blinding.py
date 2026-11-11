"""Blinding of the preregistered C1 test in the CLI and epoch report (review 2026-11-09)."""
from __future__ import annotations

import json
import random

import pytest

from scripts.research import learner_replay_report as cli
from scripts.research import p0_8_plus_epoch_report as epoch
from src.services import learner_replay as lr

BASE_S = 1_800_000_000.0


def rows(n, start=BASE_S, step=600.0, seed=1):
    rng = random.Random(seed)
    out = []
    for i in range(n):
        entry = start + i * step
        out.append({"trade_id": f"t{i}", "entry_ts": entry, "exit_ts": entry + 30, "pnl_pct": rng.gauss(-0.09, 0.18),
                    "learning_source": "s", "symbol": f"S{i % 4}", "regime": "R", "side": "BUY",
                    "predicted_gross_move_bps": 1.0})
    return out


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(lr, "BOOTSTRAP_REPLICATES", 200)


def prov(tmp_path, run_id="R-test"):
    return ["--run-id", run_id, "--provenance-log", str(tmp_path / "verdict.log")]


def write(tmp_path, data):
    path = tmp_path / "ev.json"
    path.write_text(json.dumps({"rows": data}), encoding="utf-8")
    return path


def test_exploratory_replay_excludes_trades_after_cutoff(tmp_path):
    data = rows(1500)
    cutoff = data[999]["entry_ts"]
    ev = write(tmp_path, data)
    cli.main(["--json", str(ev), "--prereg-after", str(cutoff), "--out", str(tmp_path / "o")])
    result = json.loads((tmp_path / "o" / "replay.json").read_text(encoding="utf-8"))
    assert result["n"] == 1000
    assert result["preregistered"]["verdict"] == "PENDING"
    assert result["preregistered"]["variants"] is None
    md = (tmp_path / "o" / "replay.md").read_text(encoding="utf-8")
    assert "skryté" in md and "do cutoffu" in md


def test_prereg_result_is_written_once_and_frozen(tmp_path, monkeypatch):
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    frozen = tmp_path / "prereg_result.json"
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(cutoff),
              "--prereg-result", str(frozen), *prov(tmp_path), "--out", str(tmp_path / "a")])
    first = json.loads(frozen.read_text(encoding="utf-8"))
    assert first["verdict"] != "PENDING" and len(first["scored_trade_ids"]) == lr.PREREGISTERED_FINAL_N
    # different later data must not change the frozen result
    cli.main(["--json", str(write(tmp_path, rows(2600, seed=7))), "--prereg-after", str(cutoff),
              "--prereg-result", str(frozen), *prov(tmp_path), "--out", str(tmp_path / "b")])
    again = json.loads((tmp_path / "b" / "replay.json").read_text(encoding="utf-8"))["preregistered"]
    assert again == first
    with pytest.raises(ValueError, match="cutoff_mismatch"):
        cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(cutoff + 1),
                  "--prereg-result", str(frozen), *prov(tmp_path), "--out", str(tmp_path / "c")])


def test_pending_never_writes_frozen_file(tmp_path):
    data = rows(1200)
    frozen = tmp_path / "prereg_result.json"
    cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(data[999]["entry_ts"]),
              "--prereg-result", str(frozen), *prov(tmp_path), "--out", str(tmp_path / "o")])
    assert not frozen.exists()


def test_epoch_report_until_excludes_later_entries(tmp_path):
    data = rows(50)
    selected = epoch.load_rows(json_path=write(tmp_path, data), until=data[19]["entry_ts"])
    assert len(selected) == 20
    with pytest.raises(ValueError):
        epoch.load_rows(json_path=write(tmp_path, data), until=float("nan"))


def _freeze(tmp_path, monkeypatch, capsys, data, cutoff, run_id="20261116T174700Z", out="a"):
    frozen = tmp_path / "prereg_result.json"
    args = ["--json", str(write(tmp_path, data)), "--prereg-after", str(cutoff),
            "--prereg-result", str(frozen), *prov(tmp_path, run_id), "--out", str(tmp_path / out)]
    cli.main(args)
    return frozen, capsys.readouterr().out


def test_freeze_writes_provenance_bound_to_exact_result_bytes(tmp_path, monkeypatch, capsys):
    import hashlib
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    now_s = data[-1]["entry_ts"] + 30 * 86400
    monkeypatch.setattr(cli.time, "time", lambda: now_s)
    frozen, line = _freeze(tmp_path, monkeypatch, capsys, data, cutoff)
    prov_path = cli.provenance_path(frozen)
    manifest = json.loads(prov_path.read_text(encoding="utf-8"))
    assert manifest == {"contract": "c1_provenance_v1", "hypothesis": "C1_contrarian",
                        "scored_after_ms": round(cutoff * 1000), "run_id": "20261116T174700Z",
                        "evaluated_at_ms": round(now_s * 1000),
                        "result_sha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
                        "id_hash_convention": cli.ID_HASH_CONVENTION}
    assert f"provenance_sha256={hashlib.sha256(prov_path.read_bytes()).hexdigest()}" in line
    import os
    import stat
    if os.name != "nt":
        assert not (prov_path.stat().st_mode & stat.S_IWUSR)


def test_provenance_hash_printed_only_by_the_freezing_run(tmp_path, monkeypatch, capsys):
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    frozen, first = _freeze(tmp_path, monkeypatch, capsys, data, cutoff)
    before = cli.provenance_path(frozen).read_bytes()
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 40 * 86400)
    _, second = _freeze(tmp_path, monkeypatch, capsys, data, cutoff, run_id="later", out="b")
    assert "provenance_sha256=" in first and "provenance_sha256=" not in second
    assert cli.provenance_path(frozen).read_bytes() == before


def test_pending_or_insufficient_writes_no_provenance(tmp_path, monkeypatch, capsys):
    data = rows(1200)
    frozen, line = _freeze(tmp_path, monkeypatch, capsys, data, data[999]["entry_ts"])
    assert not cli.provenance_path(frozen).exists() and "provenance_sha256" not in line


def test_produced_manifest_is_accepted_by_cost_review(tmp_path, monkeypatch, capsys):
    """End-to-end on synthetic data at the real C1 cutoff with the real 2 000 replicates."""
    import hashlib
    from scripts.research import cost_and_learning_review as review
    monkeypatch.setattr(lr, "BOOTSTRAP_REPLICATES", 2000)
    cutoff = review.C1_CUTOFF_MS / 1000
    data = rows(2600, start=cutoff - 999 * 600.0, step=600.0)
    assert data[999]["entry_ts"] == cutoff
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    frozen, line = _freeze(tmp_path, monkeypatch, capsys, data, cutoff)
    reference = line.split("provenance_sha256=")[1].split()[0]
    report = review.build(_review_report(tmp_path), frozen, provenance_path=cli.provenance_path(frozen),
                          provenance_sha=reference)
    assert report["c1"]["status"] in review.C1_FINAL
    assert report["inputs"]["c1_provenance_verified"] and report["inputs"]["c1_result_verified"]
    assert report["inputs"]["c1_result_sha256_observed"] == hashlib.sha256(frozen.read_bytes()).hexdigest()


def _log_lines(tmp_path):
    log = tmp_path / "verdict.log"
    return [l for l in log.read_text(encoding="utf-8").splitlines() if " PROVENANCE " in l] if log.exists() else []


def test_a1_reference_logged_once_with_matching_hashes(tmp_path, monkeypatch, capsys):
    import hashlib
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    frozen, _ = _freeze(tmp_path, monkeypatch, capsys, data, cutoff, run_id="RUN1")
    _freeze(tmp_path, monkeypatch, capsys, data, cutoff, run_id="RUN2", out="b")
    lines = _log_lines(tmp_path)
    assert len(lines) == 1
    manifest_sha = hashlib.sha256(cli.provenance_path(frozen).read_bytes()).hexdigest()
    result_sha = hashlib.sha256(frozen.read_bytes()).hexdigest()
    assert f"run=RUN1 manifest_sha256={manifest_sha} result_sha256={result_sha}" in lines[0]


def test_a1_reference_survives_failure_after_freeze(tmp_path, monkeypatch, capsys):
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")  # --out cannot be created -> run fails after freezing
    frozen = tmp_path / "prereg_result.json"
    with pytest.raises(OSError):
        cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(cutoff),
                  "--prereg-result", str(frozen), *prov(tmp_path), "--out", str(blocker / "o")])
    assert frozen.exists() and len(_log_lines(tmp_path)) == 1


def test_a1_reference_is_logged_before_the_freeze_marker(tmp_path, monkeypatch, capsys):
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    real = cli._write_frozen

    def fail_on_result(path, payload):
        if path.name == "prereg_result.json":
            raise OSError("simulated crash before the marker")
        real(path, payload)

    monkeypatch.setattr(cli, "_write_frozen", fail_on_result)
    with pytest.raises(OSError):
        _freeze(tmp_path, monkeypatch, capsys, data, cutoff)
    assert len(_log_lines(tmp_path)) == 1 and not (tmp_path / "prereg_result.json").exists()


@pytest.mark.parametrize("drop", ["--run-id", "--provenance-log"])
def test_a2_freeze_requires_run_id_and_log(tmp_path, drop):
    data = rows(1200)
    args = ["--json", str(write(tmp_path, data)), "--prereg-after", str(data[999]["entry_ts"]),
            "--prereg-result", str(tmp_path / "prereg_result.json"), *prov(tmp_path), "--out", str(tmp_path / "o")]
    i = args.index(drop)
    del args[i:i + 2]
    with pytest.raises(SystemExit):
        cli.main(args)
    assert not (tmp_path / "o").exists() and not (tmp_path / "prereg_result.json").exists()


def test_a2_library_freeze_fails_closed_without_run_id(tmp_path, monkeypatch):
    data = rows(2600)
    cutoff_ms = round(data[999]["entry_ts"] * 1000)
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    trades = [t for t in (cli.to_trade(r) for r in data) if t]
    with pytest.raises(ValueError, match="run_id and provenance_log"):
        cli.frozen_preregistered(trades, cutoff_ms, tmp_path / "prereg_result.json", None, tmp_path / "v.log")
    assert not (tmp_path / "prereg_result.json").exists()
    assert not cli.provenance_path(tmp_path / "prereg_result.json").exists()


def _final_trades(data, monkeypatch):
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    return [t for t in (cli.to_trade(r) for r in data) if t]


@pytest.mark.parametrize("alias", ["result", "manifest", "result_tmp", "manifest_tmp", "relative_result"])
def test_b1_log_aliasing_result_or_manifest_rejected_before_any_write(tmp_path, monkeypatch, alias):
    data = rows(2600)
    trades = _final_trades(data, monkeypatch)
    result = tmp_path / "prereg_result.json"
    manifest = cli.provenance_path(result)
    log = {"result": result, "manifest": manifest, "result_tmp": tmp_path / "prereg_result.json.tmp",
           "manifest_tmp": tmp_path / "prereg_provenance.json.tmp"}.get(alias)
    if alias == "relative_result":
        monkeypatch.chdir(tmp_path)
        log = cli.Path("sub") / ".." / "prereg_result.json"
        (tmp_path / "sub").mkdir()
    with pytest.raises(ValueError, match="alias"):
        cli.frozen_preregistered(trades, round(data[999]["entry_ts"] * 1000), result, "R1", log)
    assert not result.exists() and not manifest.exists()
    assert not any(tmp_path.glob("*.tmp"))


def test_b1_symlinked_log_alias_rejected(tmp_path, monkeypatch):
    data = rows(2600)
    trades = _final_trades(data, monkeypatch)
    result = tmp_path / "prereg_result.json"
    link = tmp_path / "verdict.log"
    try:
        link.symlink_to(result)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this host")
    with pytest.raises(ValueError, match="alias"):
        cli.frozen_preregistered(trades, round(data[999]["entry_ts"] * 1000), result, "R1", link)
    assert not result.exists()


def test_b1_cli_rejects_alias_before_evaluation(tmp_path, monkeypatch):
    data = rows(1200)
    result = tmp_path / "prereg_result.json"
    monkeypatch.setattr(cli, "evaluate_preregistered",
                        lambda *a, **k: pytest.fail("evaluation must not run with invalid freeze inputs"))
    with pytest.raises(SystemExit):
        cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(data[999]["entry_ts"]),
                  "--prereg-result", str(result), "--run-id", "R1", "--provenance-log", str(result),
                  "--out", str(tmp_path / "o")])
    assert not result.exists() and not (tmp_path / "o").exists()


def _hardlink(src, dst):
    import os
    try:
        os.link(src, dst)
    except (OSError, NotImplementedError):
        pytest.skip("hardlinks not supported on this filesystem")


LOG_TEXT = "2026-11-10T05:47:18Z COHORT_BLIND fresh_closed=204\n"


@pytest.mark.parametrize("target", ["prereg_result.json.tmp", "prereg_provenance.json.tmp",
                                    "prereg_provenance.json"])
def test_b1_hardlinked_log_rejected_by_library(tmp_path, monkeypatch, target):
    data = rows(2600)
    trades = _final_trades(data, monkeypatch)
    result = tmp_path / "prereg_result.json"
    log = tmp_path / "verdict.log"
    log.write_text(LOG_TEXT, encoding="utf-8")
    _hardlink(log, tmp_path / target)
    with pytest.raises(ValueError, match="alias"):
        cli.frozen_preregistered(trades, round(data[999]["entry_ts"] * 1000), result, "R1", log)
    assert log.read_text(encoding="utf-8") == LOG_TEXT and not result.exists()


def test_b1_hardlinked_log_rejected_by_cli_before_evaluation(tmp_path, monkeypatch):
    data = rows(1200)
    result = tmp_path / "prereg_result.json"
    log = tmp_path / "verdict.log"
    log.write_text(LOG_TEXT, encoding="utf-8")
    _hardlink(log, tmp_path / "prereg_result.json.tmp")
    monkeypatch.setattr(cli, "evaluate_preregistered",
                        lambda *a, **k: pytest.fail("evaluation must not run with invalid freeze inputs"))
    with pytest.raises(SystemExit):
        cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(data[999]["entry_ts"]),
                  "--prereg-result", str(result), "--run-id", "R1", "--provenance-log", str(log),
                  "--out", str(tmp_path / "o")])
    assert log.read_text(encoding="utf-8") == LOG_TEXT and not result.exists()


def test_b1_write_never_goes_through_a_stale_hardlinked_tmp(tmp_path):
    log = tmp_path / "verdict.log"
    log.write_text(LOG_TEXT, encoding="utf-8")
    _hardlink(log, tmp_path / "x.json.tmp")  # bypasses validation on purpose (defence in depth)
    cli._write_frozen(tmp_path / "x.json", b'{"v": 1}')
    assert log.read_text(encoding="utf-8") == LOG_TEXT
    assert (tmp_path / "x.json").read_bytes() == b'{"v": 1}'


def test_b1_identity_check_error_fails_closed(tmp_path, monkeypatch):
    log = tmp_path / "verdict.log"
    log.write_text(LOG_TEXT, encoding="utf-8")
    (tmp_path / "prereg_provenance.json").write_text("{}", encoding="utf-8")

    def boom(a, b):
        raise PermissionError("denied")

    monkeypatch.setattr(cli.os.path, "samefile", boom)
    with pytest.raises(ValueError, match="distinct file"):
        cli.validate_freeze_inputs(tmp_path / "prereg_result.json", "R1", log)


@pytest.mark.parametrize("bad", ["R1\n2026-11-16T00:00:00Z PROVENANCE run=X", "R 1", "R\t1", "", "-lead",
                                 "x" * 65, "R1\r", "ü"])
def test_b2_run_id_must_be_one_token(tmp_path, monkeypatch, bad):
    data = rows(2600)
    trades = _final_trades(data, monkeypatch)
    result = tmp_path / "prereg_result.json"
    with pytest.raises(ValueError):
        cli.frozen_preregistered(trades, round(data[999]["entry_ts"] * 1000), result, bad, tmp_path / "verdict.log")
    assert not result.exists() and not (tmp_path / "verdict.log").exists()


def test_b2_cli_rejects_bad_run_id(tmp_path):
    data = rows(1200)
    with pytest.raises(SystemExit):
        cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(data[999]["entry_ts"]),
                  "--prereg-result", str(tmp_path / "prereg_result.json"), "--run-id", "a\nb",
                  "--provenance-log", str(tmp_path / "verdict.log"), "--out", str(tmp_path / "o")])


@pytest.mark.parametrize("good", ["20261116T174700Z", "manual-1", "a.b:c_d"])
def test_b2_valid_run_ids_accepted(good):
    assert cli.RUN_ID_PATTERN.fullmatch(good)


def test_b3_content_synced_before_rename_and_directory_after(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = cli.os.fsync, cli.Path.replace
    monkeypatch.setattr(cli.os, "fsync", lambda fd: (events.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(cli.Path, "replace", lambda self, target: (events.append("replace"), real_replace(self, target))[1])
    dirs = []
    monkeypatch.setattr(cli, "_fsync_dir", lambda d: (dirs.append(d), events.append("dir"))[0])
    cli._write_frozen(tmp_path / "x.json", b"{}")
    assert events == ["fsync", "replace", "dir"] and dirs == [tmp_path]
    assert (tmp_path / "x.json").read_bytes() == b"{}"


def test_b3_new_log_directory_synced(tmp_path, monkeypatch):
    dirs = []
    monkeypatch.setattr(cli, "_fsync_dir", lambda d: dirs.append(d))
    cli._append_reference(tmp_path / "verdict.log", "R1", "a" * 64, "b" * 64)
    cli._append_reference(tmp_path / "verdict.log", "R2", "c" * 64, "d" * 64)
    assert dirs == [tmp_path]  # only when the log is created
    assert len((tmp_path / "verdict.log").read_text(encoding="utf-8").splitlines()) == 2


def _review_report(tmp_path):
    from tests import test_cost_and_learning_review as fixtures
    path = tmp_path / "futures.json"
    path.write_text(json.dumps(fixtures._report()), encoding="utf-8")
    return path


def test_insufficient_data_is_never_frozen(tmp_path, monkeypatch):
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    frozen = tmp_path / "prereg_result.json"
    monkeypatch.setattr(cli.time, "time", lambda: data[-1]["entry_ts"] + 30 * 86400)
    monkeypatch.setattr(cli, "evaluate_preregistered",
                        lambda *a, **k: {"scored_after_ms": round(cutoff * 1000), "verdict": "INSUFFICIENT_DATA",
                                         "variants": None, "fresh_n": 1600, "final_n": 1000,
                                         "days_elapsed": 30, "min_days": 7})
    cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(cutoff),
              "--prereg-result", str(frozen), *prov(tmp_path), "--out", str(tmp_path / "o")])
    assert not frozen.exists()
    assert not cli.provenance_path(frozen).exists()
