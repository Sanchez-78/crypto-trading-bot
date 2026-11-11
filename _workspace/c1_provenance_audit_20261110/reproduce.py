"""Synthetic reproduction for the C1 provenance producer audit (no real data, temp dir only).

A1: the manifest hash is printed only by the freezing run; if that run's output never reaches
    verdict.log (any later run_eval.sh step fails), no later run re-emits it.
A2: --prereg-result without --run-id freezes with run_id "unspecified", which the consumer accepts.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.research import learner_replay_report as cli  # noqa: E402
from src.services import learner_replay as lr  # noqa: E402

lr.BOOTSTRAP_REPLICATES = 200  # speed only; consumer acceptance is not tested here


def rows(n, start=1_800_000_000.0, step=600.0):
    rng = random.Random(1)
    return [{"trade_id": f"t{i}", "entry_ts": start + i * step, "exit_ts": start + i * step + 30,
             "pnl_pct": rng.gauss(-0.09, 0.18), "learning_source": "s", "symbol": f"S{i % 4}", "regime": "R",
             "side": "BUY", "predicted_gross_move_bps": 1.0} for i in range(n)]


def run(tmp: Path, data, cutoff, out, run_id=None) -> str:
    ev = tmp / "ev.json"
    ev.write_text(json.dumps({"rows": data}), encoding="utf-8")
    args = ["--json", str(ev), "--prereg-after", str(cutoff), "--prereg-result", str(tmp / "prereg_result.json"),
            "--out", str(tmp / out)]
    if run_id:
        args += ["--run-id", run_id]
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main(args)
    return buf.getvalue().strip()


def main() -> None:
    data = rows(2600)
    cutoff = data[999]["entry_ts"]
    cli.time.time = lambda: data[-1]["entry_ts"] + 30 * 86400
    results = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        first = run(tmp, data, cutoff, "a", run_id="R1")
        second = run(tmp, data, cutoff, "b", run_id="R2")
        manifest = (tmp / "prereg_provenance.json").read_bytes()
        results["A1"] = {
            "freezing_run_prints_hash": "provenance_sha256=" in first,
            "later_run_prints_hash": "provenance_sha256=" in second,
            "manifest_sha256_on_disk": hashlib.sha256(manifest).hexdigest(),
            "consequence": "if the freezing run's stdout is not appended to verdict.log, no run re-emits it",
        }
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        run(tmp, data, cutoff, "a", run_id=None)
        manifest = json.loads((tmp / "prereg_provenance.json").read_text(encoding="utf-8"))
        results["A2"] = {"run_id_without_flag": manifest["run_id"]}
    out = Path(__file__).with_name("reproductions.json")
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
