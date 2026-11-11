"""Mutations for the review-78 fixes (R1 pinned staging, R2 parser); isolated copy only."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ["tests/test_deploy_pinned.py", "tests/test_deploy_env_check.py", "tests/test_deploy_bot_files_allowlist.py"]
D = "deploy/research_eval/"
MUTATIONS = {
    "R1_install_from_source_again": (D + "deploy_bot_files.sh", 'install_staged "$PINNED" "$APP" "$FILES"',
                                     'for f in $FILES; do install -m 644 "$NEW/$(basename "$f")" "$APP/$f"; done'),
    "R1_postimage_vs_source": (D + "deploy_bot_files.sh",
                               'verify_pinned "$APP" "$FILES" "$EXPECTED_SHA256" || rollback "postimage differs from EXPECTED_SHA256"',
                               'for f in $FILES; do [ "$(sha256sum < "$APP/$f")" = "$(sha256sum < "$NEW/$(basename "$f")")" ] || rollback "x"; done'),
    "R1_verify_always_ok": (D + "deploy_pinned.sh", '    [ "$got" = "$want" ] || {', '    true || {'),
    "R1_install_reads_source": (D + "deploy_pinned.sh", '  for f in $3; do install -m 644 "$stage/$f" "$app/$f"; done',
                                '  for f in $3; do install -m 644 "$stage/../new/$(basename "$f")" "$app/$f"; done'),
    "R1_sandbox_writes_stage": (D + "deploy_bot_files.sh", '-p ReadWritePaths="$SCRATCH"', '-p ReadWritePaths="$STAGE_DIR"'),
    "R2_partial_parse_accepted": (D + "deploy_env_check.py", '    if ENV_FILE_ITEM.sub("", listing).strip():',
                                  '    if listing.strip() and not items:'),
}


def run(tmp: Path) -> dict:
    p = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--noconftest", *TESTS],
                       cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = [l for l in p.stdout.splitlines() if " passed" in l or " failed" in l or " error" in l]
    return {"exit": p.returncode, "summary": lines[-1] if lines else p.stdout[-200:]}


def main() -> int:
    res = {}
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        shutil.copytree(ROOT / "deploy", tmp / "deploy")
        (tmp / "tests").mkdir()
        for t in TESTS:
            shutil.copy(ROOT / t, tmp / t)
        res["baseline"] = run(tmp)
        for name, (rel, old, new) in MUTATIONS.items():
            original = (tmp / rel).read_text(encoding="utf-8")
            assert original.count(old) == 1, name
            (tmp / rel).write_text(original.replace(old, new), encoding="utf-8", newline="\n")
            res[name] = run(tmp)
            (tmp / rel).write_text(original, encoding="utf-8", newline="\n")
        res["restored"] = run(tmp)
    Path(__file__).with_name("r1_mutation_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    for k, v in res.items():
        print(k, v)
    ok = res["baseline"]["exit"] == 0 and res["restored"]["exit"] == 0 and all(
        v["exit"] != 0 for k, v in res.items() if k not in ("baseline", "restored"))
    print("ALL_CAUGHT" if ok else "SURVIVOR")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
