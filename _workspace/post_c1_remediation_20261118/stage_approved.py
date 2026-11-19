"""Build index-only patches with exactly the approved hunks (server copy -> current local file).

Mode "check": write approved_hunks.patch and run `git apply --cached --check` against the index (= HEAD).
Mode "apply": stage those hunks into the index only (`git apply --cached`); the working tree is not touched.
"""
import difflib
import subprocess
import sys
from pathlib import Path

D = Path(__file__).resolve().parent
ROOT = D.parents[1]
PAIRS = [("readiness_monitor.server.py", "src/services/readiness_monitor.py"),
         ("dashboard_web.server.py", "src/services/dashboard_web.py"),
         ("outbox.server.py", "src/services/v5_legacy_bridge/outbox.py"),
         ("outbox_flush_worker.server.py", "src/services/v5_legacy_bridge/outbox_flush_worker.py")]


def lines(text):
    return text.replace("\r\n", "\n").splitlines(keepends=True)


def main(mode):
    patch, stats = [], []
    for srv, loc in PAIRS:
        a = lines((D / "server_copies" / srv).read_text(encoding="utf-8"))
        b = lines((ROOT / loc).read_text(encoding="utf-8"))
        d = list(difflib.unified_diff(a, b, "a/" + loc, "b/" + loc, n=3))
        if d:
            patch.append(f"diff --git a/{loc} b/{loc}\n")
            patch += [l if l.endswith("\n") else l + "\n\\ No newline at end of file\n" for l in d]
        plus = sum(1 for l in d if l.startswith("+") and not l.startswith("+++"))
        minus = sum(1 for l in d if l.startswith("-") and not l.startswith("---"))
        stats.append(f"{loc}: +{plus} -{minus}")
    out = D / "approved_hunks.patch"
    out.write_text("".join(patch), encoding="utf-8", newline="\n")
    print("\n".join(stats))
    args = ["git", "apply", "--cached", "--recount", "-v"] + (["--check"] if mode == "check" else []) + [str(out)]
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    print(r.stdout[-3000:], r.stderr[-3000:], "exit", r.returncode)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
