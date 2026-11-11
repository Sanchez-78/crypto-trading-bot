"""Synthetic server preflight for the C1 provenance producer (review 75). No real C1 data.

Run from a staging copy of the research code tree, inside a fresh directory on the same
filesystem as /opt/cryptomaster_research:
    python3 -B preflight_c1_provenance.py <staged_code_dir> <work_dir>
Prints one JSON object; exit 0 only if every check passed.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
from pathlib import Path

CODE, WORK = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
sys.path.insert(0, str(CODE))
from scripts.research import learner_replay_report as cli  # noqa: E402
from src.services import learner_replay as lr  # noqa: E402

lr.BOOTSTRAP_REPLICATES = 200  # synthetic speed only
RUN_ID = "20261116T174700Z"
LOG_TEXT = "2026-11-11T00:00:00Z SYNTHETIC prior line\n"


def rows(n=2600, start=1_800_000_000.0, step=600.0):
    rng = random.Random(1)
    return [{"trade_id": f"t{i}", "entry_ts": start + i * step, "exit_ts": start + i * step + 30,
             "pnl_pct": rng.gauss(-0.09, 0.18), "learning_source": "s", "symbol": f"S{i % 4}",
             "regime": "R", "side": "BUY", "predicted_gross_move_bps": 1.0} for i in range(n)]


DATA = rows()
CUTOFF_MS = round(DATA[999]["entry_ts"] * 1000)
cli.time.time = lambda: DATA[-1]["entry_ts"] + 30 * 86400
TRADES = [t for t in (cli.to_trade(r) for r in DATA) if t]


def case_dir(name: str) -> Path:
    d = WORK / name
    d.mkdir()
    (d / "verdict.log").write_text(LOG_TEXT, encoding="utf-8")
    return d


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def refs(d: Path) -> list[str]:
    return [l for l in (d / "verdict.log").read_text(encoding="utf-8").splitlines() if " PROVENANCE " in l]


def triple_consistent(d: Path) -> bool:
    result, manifest = d / "prereg_result.json", d / "prereg_provenance.json"
    if not (result.exists() and manifest.exists()):
        return False
    m = json.loads(manifest.read_text(encoding="utf-8"))
    last = refs(d)[-1]
    return (m["result_sha256"] == sha(result) and f"manifest_sha256={sha(manifest)}" in last
            and f"result_sha256={sha(result)}" in last and f"run={m['run_id']} " in last)


def alias_rejected(name: str, make_alias) -> dict:
    d = case_dir(name)
    make_alias(d)
    try:
        cli.frozen_preregistered(TRADES, CUTOFF_MS, d / "prereg_result.json", RUN_ID, d / "verdict.log")
        rejected = False
    except ValueError:
        rejected = True
    log = d / "verdict.log"
    # A dangling symlink log (target = the absent result) must stay dangling: nothing written.
    unchanged = (not log.exists()) if log.is_symlink() else log.read_text(encoding="utf-8") == LOG_TEXT
    return {"rejected": rejected, "log_unchanged": unchanged,
            "no_result": not (d / "prereg_result.json").exists()}


checks = {}
checks["symlink_log_to_result"] = alias_rejected(
    "symlink", lambda d: ((d / "verdict.log").unlink(), (d / "verdict.log").symlink_to(d / "prereg_result.json"),
                          None))
checks["hardlink_log_to_result_tmp"] = alias_rejected(
    "hl_result_tmp", lambda d: os.link(d / "verdict.log", d / "prereg_result.json.tmp"))
checks["hardlink_log_to_manifest_tmp"] = alias_rejected(
    "hl_manifest_tmp", lambda d: os.link(d / "verdict.log", d / "prereg_provenance.json.tmp"))
checks["hardlink_log_to_manifest"] = alias_rejected(
    "hl_manifest", lambda d: os.link(d / "verdict.log", d / "prereg_provenance.json"))

# Normal freeze through the CLI with the same arguments run_eval.sh passes.
d = case_dir("normal")
ev = d / "ev.json"
ev.write_text(json.dumps({"rows": DATA}), encoding="utf-8")
cli.main(["--json", str(ev), "--prereg-after", str(DATA[999]["entry_ts"]), "--prereg-result",
          str(d / "prereg_result.json"), "--run-id", RUN_ID, "--provenance-log", str(d / "verdict.log"),
          "--out", str(d / "out")])
checks["normal_freeze"] = {"one_reference": len(refs(d)) == 1, "triple_consistent": triple_consistent(d),
                           "modes_0444": all(oct((d / f).stat().st_mode & 0o777) == "0o444"
                                             for f in ("prereg_result.json", "prereg_provenance.json")),
                           "dir_fsync_ok": True}
cli._fsync_dir(d)  # raises if the directory cannot be opened/synced on this host

# Failure between manifest and reference, then retry.
d = case_dir("crash_before_reference")
real_append, real_write = cli._append_reference, cli._write_frozen


def boom(*a, **k):
    raise OSError("synthetic crash")


cli._append_reference = boom
try:
    cli.frozen_preregistered(TRADES, CUTOFF_MS, d / "prereg_result.json", "R1", d / "verdict.log")
except OSError:
    pass
cli._append_reference = real_append
state = {"no_result": not (d / "prereg_result.json").exists(), "orphan_manifest": (d / "prereg_provenance.json").exists(),
         "no_reference": not refs(d)}
cli.frozen_preregistered(TRADES, CUTOFF_MS, d / "prereg_result.json", "R2", d / "verdict.log")
checks["crash_before_reference"] = {**state, "retry_one_reference": len(refs(d)) == 1,
                                    "retry_triple_consistent": triple_consistent(d)}

# Failure between reference and result marker, then retry.
d = case_dir("crash_before_result")


def fail_result(path, payload):
    if path.name == "prereg_result.json":
        raise OSError("synthetic crash")
    real_write(path, payload)


cli._write_frozen = fail_result
try:
    cli.frozen_preregistered(TRADES, CUTOFF_MS, d / "prereg_result.json", "R1", d / "verdict.log")
except OSError:
    pass
cli._write_frozen = real_write
state = {"no_result": not (d / "prereg_result.json").exists(), "orphan_reference": len(refs(d)) == 1}
cli.frozen_preregistered(TRADES, CUTOFF_MS, d / "prereg_result.json", "R2", d / "verdict.log")
checks["crash_before_result"] = {**state, "retry_two_references": len(refs(d)) == 2,
                                 "retry_latest_matches_files": triple_consistent(d)}

ok = all(all(v.values()) for v in checks.values())
print(json.dumps({"python": sys.version.split()[0], "ok": ok, "checks": checks}, indent=2, sort_keys=True))
sys.exit(0 if ok else 1)
