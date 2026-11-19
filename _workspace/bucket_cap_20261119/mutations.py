"""Mutations for the bucket-cap review fixes (isolated copy; no runtime files)."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_explore_bucket_cap.py"]
EX = "src/services/paper_trade_executor.py"
EC = "deploy/research_eval/deploy_env_check.py"
MUTATIONS = {
    "cap_for_every_bucket": (EX, "    return exploration_bucket_cap() if bucket == EXPLORE_BUCKET_CAP_BUCKET else EXPLORE_BUCKET_CAP_DEFAULT",
                             "    return exploration_bucket_cap()"),
    "int_parse_again": (EX, '    return _EXPLORE_BUCKET_CAP_VALUES.get(str(raw).strip(), EXPLORE_BUCKET_CAP_DEFAULT)',
                        '    raw = str(raw).strip()\n    return int(raw) if raw.isdigit() and 1 <= int(raw) <= 7 else 2'),
    "env_check_unbounded_digits": (EC, 're.fullmatch(r"[0-9]{1,3}", value)', 're.fullmatch(r"[0-9]+", value)'),
    "cap_check_uses_default_only": (EX, "    if bucket_count >= _bucket_cap_for(bucket):", "    if bucket_count >= 2:"),
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
        for name in ("src", "tests", "deploy"):
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
        print(k, v["summary"])
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")


if __name__ == "__main__":
    main()
