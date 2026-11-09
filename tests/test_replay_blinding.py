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
              "--prereg-result", str(frozen), "--out", str(tmp_path / "a")])
    first = json.loads(frozen.read_text(encoding="utf-8"))
    assert first["verdict"] != "PENDING" and len(first["scored_trade_ids"]) == lr.PREREGISTERED_FINAL_N
    # different later data must not change the frozen result
    cli.main(["--json", str(write(tmp_path, rows(2600, seed=7))), "--prereg-after", str(cutoff),
              "--prereg-result", str(frozen), "--out", str(tmp_path / "b")])
    again = json.loads((tmp_path / "b" / "replay.json").read_text(encoding="utf-8"))["preregistered"]
    assert again == first
    with pytest.raises(ValueError, match="cutoff_mismatch"):
        cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(cutoff + 1),
                  "--prereg-result", str(frozen), "--out", str(tmp_path / "c")])


def test_pending_never_writes_frozen_file(tmp_path):
    data = rows(1200)
    frozen = tmp_path / "prereg_result.json"
    cli.main(["--json", str(write(tmp_path, data)), "--prereg-after", str(data[999]["entry_ts"]),
              "--prereg-result", str(frozen), "--out", str(tmp_path / "o")])
    assert not frozen.exists()


def test_epoch_report_until_excludes_later_entries(tmp_path):
    data = rows(50)
    selected = epoch.load_rows(json_path=write(tmp_path, data), until=data[19]["entry_ts"])
    assert len(selected) == 20
    with pytest.raises(ValueError):
        epoch.load_rows(json_path=write(tmp_path, data), until=float("nan"))


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
              "--prereg-result", str(frozen), "--out", str(tmp_path / "o")])
    assert not frozen.exists()
