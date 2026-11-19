"""Stage HEAD + exactly the approved outbox_flush_worker.py insertions into the index (working tree untouched).

The approved hunks were reviewed on top of the server version; HEAD holds an older version with
different context around stop()/_run_loop, so `git apply` cannot place them. Each insertion is
put on a unique anchor; every anchor must match exactly once.
Mode "check": print the staged diff vs HEAD. Mode "apply": write the blob and update the index.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = "src/services/v5_legacy_bridge/outbox_flush_worker.py"


def git(*args, inp=None):
    r = subprocess.run(["git", *args], cwd=ROOT, input=inp, capture_output=True, check=True)
    return r.stdout


def insert_after(text, anchor, block):
    assert text.count(anchor) == 1, anchor
    return text.replace(anchor, anchor + block)


def main(mode):
    head = git("show", f"HEAD:{PATH}").decode("utf-8").replace("\r\n", "\n")
    local = (ROOT / PATH).read_text(encoding="utf-8").replace("\r\n", "\n")
    method = local[local.index("    def _report_terminal_backlog"):local.index("    def stop(")]
    status_start = local.index("        backlog = self.outbox.backlog_stats() if self.outbox else {}\n")
    status_extra = local[local.index('            # Rows past OUTBOX_MAX_RETRIES'):local.index('            "firebase_connected"')]

    new = insert_after(head, "        self._stop_event = threading.Event()\n",
                       "        self._last_terminal_count: Optional[int] = None\n")
    new = insert_after(new, '        logger.info("[V5_BRIDGE_OUTBOX_FLUSH] Worker started")\n',
                       "        self._report_terminal_backlog()\n\n" + method.rstrip("\n") + "\n")
    new = insert_after(new, '                logger.error(f"[V5_BRIDGE_OUTBOX_FLUSH_ERROR] {e}")\n',
                       "            self._report_terminal_backlog()  # logs only when the count changes\n")
    new = insert_after(new, "            count_by_type = {}\n\n",
                       local[status_start:local.index("        return {", status_start)])
    new = insert_after(new, '            "count_by_type": count_by_type,\n', status_extra)
    assert "Optional" in head.split("class ", 1)[0]  # typing.Optional already imported in HEAD

    out = ROOT / "_workspace/post_c1_remediation_20261118/outbox_flush_worker.staged.py"
    out.write_text(new, encoding="utf-8", newline="\n")
    if mode == "apply":
        sha = git("hash-object", "-w", "--path", PATH, str(out)).decode().strip()
        mode_bits = git("ls-files", "-s", PATH).decode().split()[0]
        git("update-index", "--cacheinfo", f"{mode_bits},{sha},{PATH}")
        print("staged", sha)
    else:
        import difflib
        print("".join(difflib.unified_diff(head.splitlines(True), new.splitlines(True), "HEAD", "staged", n=1)))


if __name__ == "__main__":
    main(sys.argv[1])
