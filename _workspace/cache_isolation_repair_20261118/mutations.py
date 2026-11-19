"""Mutations for the planner fix (task B) and the status error flag; isolated copy only (no runtime DB)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_outbox_reconcile_plan.py", "tests/test_outbox_terminal_backlog.py"]
B = "src/services/v5_legacy_bridge/"
R = B + "outbox_reconcile.py"
MUTATIONS = {
    "no_trade_id_identity_check": (R, ' or doc.get("trade_id") != key:', ':'),
    "close_by_markers_only": (R, '    if event_type == "paper_close" and _complete(doc, _CLOSE_FIELDS):',
                              '    if event_type == "paper_close" and _positive(doc.get("exit_ts")) '
                              'and _positive(doc.get("exit_price")):'),
    "open_schema_ignored": (R, '            and _complete(doc, _OPEN_FIELDS)):', '            and True):'),
    "missing_field_allowed": (R, 'all(name in doc and check(doc[name])', 'all(name not in doc or check(doc[name])'),
    "bare_event_type_closes": (R, '    if event_type == "paper_close" and _complete(doc, _CLOSE_FIELDS):',
                               '    if event_type == "paper_close" or _complete(doc, _CLOSE_FIELDS):'),
    "any_non_open_type_closes": (R, '    if event_type == "paper_close" and _complete(doc, _CLOSE_FIELDS):',
                                 '    if event_type != "paper_open" and _complete(doc, _CLOSE_FIELDS):'),
    "symbol_any_text": (R, '    "symbol": _symbol,', '    "symbol": lambda v: isinstance(v, str) and bool(v),'),
    "side_truthy_only": (R, '    "side": lambda v: v in ("BUY", "SELL"),', '    "side": lambda v: bool(v),'),
    "real_orders_not_checked": (R, '    "real_orders_allowed": lambda v: v is False,',
                                '    "real_orders_allowed": lambda v: True,'),
    "zero_or_negative_allowed": (R, 'return isinstance(value, (int, float)) and _number(value) and value > 0',
                                 'return isinstance(value, (int, float)) and _number(value)'),
    "negative_duration_allowed": (R, '    "duration_seconds": _non_negative,', '    "duration_seconds": _number,'),
    "unrecognised_doc_treated_absent": (R, '    return "unknown"\n\n\ndef plan(', '    return "absent"\n\n\ndef plan('),
    "learning_after_planned_close_deferred": (R, '            elif r.key in planned_close:', '            elif False:'),
    "learning_merged_into_open_doc": (R, '            elif observed == "open":\n                act, why = "DEFERRED_CLOSE_MISSING"',
                                      '            elif observed == "open":\n                act, why = "MERGE_LEARNING"'),
    "dependency_kept_when_capped": (R, 'f"write cap {max_writes} reached", ""', 'f"write cap {max_writes} reached", depends_on'),
    "open_written_over_existing": (R, '            if r.key in closes or observed != "absent":',
                                   '            if r.key in closes:'),
    "status_hides_backlog_error": (B + "outbox_flush_worker.py",
                                   '            "backlog_error": backlog.get("error"),\n', ''),
}


def run(tmp: Path) -> dict:
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS], cwd=tmp,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l or " error" in l]
    return {"exit": p.returncode, "summary": lines[-1] if lines else p.stdout[-200:],
            "failed": [l for l in p.stdout.splitlines() if l.startswith("FAILED")],
            "import_error": "ImportError" in p.stdout or "SyntaxError" in p.stdout}


def main() -> int:
    res = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for name in ("src", "tests"):
            shutil.copytree(ROOT / name, tmp / name, ignore=shutil.ignore_patterns("__pycache__", "runtime", "*.sqlite*"))
        res["baseline"] = run(tmp)
        for name, (rel, old, new) in MUTATIONS.items():
            target = tmp / rel
            original = target.read_bytes()
            text = original.decode("utf-8").replace("\r\n", "\n")
            assert text.count(old) == 1, name
            target.write_text(text.replace(old, new), encoding="utf-8")
            res[name] = run(tmp)
            target.write_bytes(original)
        res["restored"] = run(tmp)
    Path(__file__).with_name("mutation_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v["summary"], v["failed"][:2])
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 and not v["import_error"] for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
