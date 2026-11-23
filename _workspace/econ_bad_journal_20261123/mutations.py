"""Mutations for the REJECT_ECON_BAD_ENTRY detail rate limit (isolated copy; no runtime files)."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_econ_bad_reject_log_limit.py"]
RDE = "src/services/realtime_decision_engine.py"
MUTATIONS = {
    # required by the task
    "per_reject_print_restored": ("    if emit_detail:\n        print(f\"    decision=REJECT_ECON_BAD_ENTRY  {reason}\")",
                                  "    print(f\"    decision=REJECT_ECON_BAD_ENTRY  {reason}\")"),
    "per_reject_trace_restored": ("        if emit_detail:\n            log.warning(\n                \"[ECON_BAD_ENTRY_RETURN_TRACE] \"",
                                  "        if True:\n            log.warning(\n                \"[ECON_BAD_ENTRY_RETURN_TRACE] \""),
    "track_blocked_skipped": ('    track_blocked(reason="ECON_BAD_ENTRY")\n    if emit_detail:',
                              '    if emit_detail:\n        track_blocked(reason="ECON_BAD_ENTRY")\n    if emit_detail:'),
    # further
    "flag_default_on": ('return str(raw).strip().lower() in {"1", "true", "yes", "on"}',
                        'return str(raw).strip().lower() not in {"0", "false", "no", "off"}'),
    "near_miss_gated": ("    _update_econ_bad_near_miss(\n        symbol=sym,",
                        "    if False:\n        pass\n    if emit_detail if False else True:\n        pass\n    (lambda **k: None)(\n        symbol=sym,"),
    "category_cap_removed": ('            if cat not in self._counts and len(self._counts) >= self._max:\n                cat = "other"\n',
                             ""),
    "summary_count_off_by_one": ("            if not emit:\n                entry[1] += 1",
                                 "            entry[1] += 1"),
    "no_lock": ("        with self._lock:\n            now = self._clock()", "        if True:\n            now = self._clock()"),
    "invariant_gated_by_detail": ("        if (\n            actual_recovery_checked is True\n            and actual_recovery_allowed is True",
                                  "        if (\n            emit_detail\n            and actual_recovery_checked is True\n            and actual_recovery_allowed is True"),
    # review R1/R2 (2026-11-23): a lost summary line must lose no counts (cumulative totals + seq)
    "totals_not_accumulated": ("                for k, (r, s) in self._counts.items():\n                    _ecl_add(self._totals, k, r, s, self._max)",
                               "                self._totals = {k: list(v) for k, v in self._counts.items()}"),
    "seq_not_incremented": ("                self._seq += 1\n", ""),
    "totals_cap_removed": ('    if cat not in target and len(target) >= cap:\n        cat = "other"\n', ""),
    "summary_reports_window_as_total": ("total_rejects={t_rej} total_suppressed={t_sup}",
                                        "total_rejects={w_rej} total_suppressed={w_sup}"),
    "error_hides_details": ("    except Exception:\n        return True\n\n\ndef _econ_bad_reject_outputs",
                            "    except Exception:\n        return False\n\n\ndef _econ_bad_reject_outputs"),
}


def run(tmp):
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l or "error" in l]
    return {"exit": p.returncode, "summary": lines[-1] if lines else p.stdout[-300:]}


def main():
    res = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name in ("src", "tests"):
            shutil.copytree(ROOT / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite*"))
        # Warm-up: importing realtime_decision_engine (via firebase_client) creates
        # runtime/firebase_cache.sqlite in a fresh tree, which the conftest guard reports. Create it
        # once so every measured run starts from the same tree.
        res["warmup_creates_runtime_file"] = run(tmp)
        res["baseline"] = run(tmp)
        target = tmp / RDE
        original = target.read_bytes()
        for name, (old, new) in MUTATIONS.items():
            text = original.decode("utf-8").replace("\r\n", "\n")
            assert text.count(old) == 1, (name, text.count(old))
            target.write_text(text.replace(old, new), encoding="utf-8")
            res[name] = run(tmp)
            target.write_bytes(original)
        res["restored"] = run(tmp)
    Path(__file__).with_name("mutation_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v["summary"])
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 for k, v in res.items() if k not in ("baseline", "restored", "warmup_creates_runtime_file"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
