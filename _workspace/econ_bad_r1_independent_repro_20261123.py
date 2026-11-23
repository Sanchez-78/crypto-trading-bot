"""Independent, import-free reproduction of the ECON BAD summary logger failure."""

import ast
from concurrent.futures import ThreadPoolExecutor
import io
from itertools import count
import logging
import os
from pathlib import Path
import re
import threading
import time


source_path = Path(__file__).resolve().parents[1] / "src/services/realtime_decision_engine.py"
tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
names = {
    "_econ_bad_reject_log_limit_enabled",
    "_econ_bad_reject_category",
    "_ecl_add",
    "EconBadRejectLogLimiter",
    "_econ_bad_should_emit_reject_detail",
}
module = ast.Module(
    body=[node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names],
    type_ignores=[],
)


class Clock:
    value = 1000.0

    def __call__(self):
        return self.value


class FlakyLog:
    remaining_failures = 1

    def __init__(self):
        self.written = []

    def warning(self, message):
        if self.remaining_failures:
            self.remaining_failures -= 1
            raise OSError("transient logger failure")
        self.written.append(message)


clock = Clock()
logger = FlakyLog()
env = {
    "_ecl_threading": threading,
    "_time": time,
    "_ecl_os": os,
    "_ECL_CATEGORY_RE": re.compile(r"[a-z_]{1,40}"),
    "ECON_BAD_REJECT_LOG_LIMIT_FLAG": "RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED",
    "log": logger,
}
exec(compile(module, str(source_path), "exec"), env)
limiter = env["EconBadRejectLogLimiter"](clock=clock)
emit = env["_econ_bad_should_emit_reject_detail"]
kwargs = {"env": {"RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED": "true"}, "limiter": limiter}
reason = "weak_ev (ev=0.0300<0.045)"

assert [emit(reason, **kwargs) for _ in range(3)] == [True, False, False]
clock.value += 61
assert emit(reason, **kwargs) is True
assert logger.written == []
assert limiter.totals_snapshot() == {"weak_ev": (3, 2)}
assert [emit(reason, **kwargs) for _ in range(2)] == [False, False]
clock.value += 61
assert emit(reason, **kwargs) is True
assert len(logger.written) == 1
assert "seq=2 " in logger.written[0]
assert "window_rejects=3 window_suppressed=2" in logger.written[0]
assert "total_rejects=6 total_suppressed=4" in logger.written[0]
print("THROWING_LOGGER_RECOVERY_PASS", logger.written[0])


class FailingStream:
    def write(self, _text):
        raise OSError("journal stream unavailable")

    def flush(self):
        pass


# The production setup uses logging.basicConfig(stream=sys.stderr), which installs a
# StreamHandler. StreamHandler.emit catches write errors before the caller sees them.
clock = Clock()
logger = logging.getLogger("econ_bad_r1_independent_repro")
logger.setLevel(logging.WARNING)
logger.propagate = False
handler = logging.StreamHandler(FailingStream())
logger.addHandler(handler)
env["log"] = logger
limiter = env["EconBadRejectLogLimiter"](clock=clock)
kwargs["limiter"] = limiter
previous_raise_exceptions = logging.raiseExceptions
logging.raiseExceptions = False
try:
    assert [emit(reason, **kwargs) for _ in range(3)] == [True, False, False]
    clock.value += 61
    assert emit(reason, **kwargs) is True
    assert limiter.totals_snapshot() == {"weak_ev": (3, 2)}
    sink = io.StringIO()
    handler.setStream(sink)
    clock.value += 61
    assert emit(reason, **kwargs) is True
    written = sink.getvalue()
    assert "seq=2 " in written
    assert "window_rejects=1 window_suppressed=0" in written
    assert "total_rejects=4 total_suppressed=2" in written
    print("STREAM_HANDLER_RECOVERY_PASS", written.strip())
finally:
    logging.raiseExceptions = previous_raise_exceptions
    logger.removeHandler(handler)
    handler.close()


tick = count()
limiter = env["EconBadRejectLogLimiter"](window_s=50, clock=lambda: 1000.0 + next(tick))


def concurrent_observe(_worker_id):
    summaries = []
    for _ in range(1000):
        _, summary = limiter.observe(reason)
        if summary:
            summaries.append(summary)
    return summaries


with ThreadPoolExecutor(max_workers=8) as pool:
    summaries = [line for batch in pool.map(concurrent_observe, range(8)) for line in batch]
summaries.sort(key=lambda line: int(re.search(r"\bseq=(\d+)", line).group(1)))
assert len(summaries) == 159
for expected_seq, line in enumerate(summaries, start=1):
    assert f"seq={expected_seq} " in line
    assert "window_rejects=50 window_suppressed=49" in line
    assert f"total_rejects={50 * expected_seq} total_suppressed={49 * expected_seq}" in line
assert limiter.snapshot() == {"weak_ev": (50, 49)}
assert limiter.totals_snapshot() == {"weak_ev": (7950, 7791)}
print("CONCURRENT_ROLLOVERS_PASS", len(summaries), "summaries")
