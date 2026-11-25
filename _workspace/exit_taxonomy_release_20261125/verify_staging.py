"""Pre-install proof that the dashboard interpreter loads exactly the pinned postimage bytes (D2).

Run on the server, BEFORE any write to /opt/cryptomaster, with the dashboard interpreter:
  /opt/dashboard_venv/bin/python3 -I -B -X pycache_prefix=<empty dir> verify_staging.py <stage_root>

<stage_root> is a fresh copy of /opt/cryptomaster/src WITHOUT __pycache__/.pyc/.pyo/sqlite, with the
four postimage files overlaid at src/services/. -I drops the script dir/cwd/PYTHON* env from the
import path, so only <stage_root> (inserted below) can provide `src`; the empty pycache_prefix and the
cache-free stage mean no old bytecode can be read. Reads the live cache only via the read model's
own mode=ro connections. Exit code 0 and the last line STAGING_VERIFIED only when every check passes.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

PINS = {
    "src/services/exit_taxonomy.py": "590cd21983052f53d5a9bedbc869fa27c66b4f097a6fcc51b874206bf4f4e94c",
    "src/services/performance_epoch.py": "58c560cc3702934180c50f293050ba32c1569c40d1ee2b76207782e7c900d2e6",
    "src/services/dashboard_read_model.py": "31ba1f98394ed9c07c7da6f229046e9dc5f5336b357f2a08ce0a17adea6a7fe5",
    "src/services/dashboard_web.py": "2446e0c19d37a61d8c8647834eb41085a9340b66e852988708fa600b3deef21e",
}
GROUPS = ("tp", "sl", "scratch", "stagnation", "timeout", "trailing_stop", "signal_exit", "risk_exit", "other")


def fail(message):
    print("STAGING_FAILED: " + message)
    sys.exit(1)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


stage = Path(sys.argv[1]).resolve()
if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
    fail("run with -I -B")
if not sys.pycache_prefix or any(Path(sys.pycache_prefix).iterdir()):
    fail("pycache_prefix must be an existing empty directory")
stale = [str(p) for p in stage.rglob("*") if p.name == "__pycache__" or p.suffix in (".pyc", ".pyo")]
if stale:
    fail(f"stale bytecode in stage: {stale[:3]}")
for rel, pin in PINS.items():
    path = stage / rel
    if sha(path) != pin:
        fail(f"stage file {rel} is not the pinned postimage")
    compile(path.read_bytes(), str(path), "exec")   # syntax of exactly these bytes, this interpreter

sys.path.insert(0, str(stage))
os.chdir(stage)   # nothing under the live tree is reachable via cwd either

import src.services.exit_taxonomy as tx              # noqa: E402
import src.services.performance_epoch as pe          # noqa: E402
import src.services.dashboard_read_model as rm       # noqa: E402
import src.services.dashboard_web as web             # noqa: E402

loaded = {"src/services/exit_taxonomy.py": tx, "src/services/performance_epoch.py": pe,
          "src/services/dashboard_read_model.py": rm, "src/services/dashboard_web.py": web}
for rel, module in loaded.items():
    source = Path(module.__file__).resolve()
    if source != stage / rel:
        fail(f"{module.__name__} loaded from {source}, not the stage")
    if sha(source) != PINS[rel]:
        fail(f"{module.__name__} source bytes differ from the pin")
outside = sorted(name for name, module in sys.modules.items()
                 if name.split(".")[0] == "src" and getattr(module, "__file__", None)
                 and not Path(module.__file__).resolve().is_relative_to(stage))
if outside:
    fail(f"src modules loaded outside the stage: {outside[:5]}")
if any(Path(sys.pycache_prefix).rglob("*.pyc")):
    fail("bytecode was written despite -B")

# Live data, read-only (the read model opens cache.sqlite with mode=ro).
metrics = rm.get_metrics()
json.dumps(metrics, allow_nan=False)
distribution = metrics["exit_distribution"]
group_sum = sum(int(distribution.get(g, 0)) for g in GROUPS)
if not (group_sum == int(distribution.get("total", -1)) == int(metrics["closed_trades"])):
    fail(f"exit groups {group_sum} / total {distribution.get('total')} / n {metrics['closed_trades']} disagree")
missing = set(rm._degraded_envelope([], "x")) - set(metrics)   # never-500 shape contract
if missing:
    fail(f"payload lacks degraded-envelope keys {sorted(missing)}")
recent = rm.get_recent_trades(10)
for row in recent:
    for key in ("direction", "direction_label", "exit_group", "exit_label", "price_move_pct"):
        if key not in row:
            fail(f"recent trade lacks {key}")

# Synthetic SELL fixture (the live window need not contain a short).
row = {"trade_id": "fixture", "symbol": "SOLUSDT", "entry_price": 69.98, "exit_price": 69.735,
       "pnl_usd": 0.0195, "pnl_pct": 0.2601, "pnl_pct_null": False, "exit_reason": "DYNAMIC_TARGET_EXIT",
       "entry_ts": 1.0, "exit_ts": 44.0, "regime": "BEAR_TREND", "win": 1, "side": "SELL", "outcome": "WIN"}
(fixture,) = rm._closed_trades_list([row])
if not (fixture["direction"] == "SHORT" and fixture["price_move_pct"] < 0
        and fixture["exit_group"] == "tp" and fixture["outcome"] == "WIN"):
    fail(f"SELL fixture not explained: {fixture}")
if tx.direction(None)["direction"] != "UNKNOWN":
    fail("unknown side shown as a direction")
if "escapeHtml(exitText)" not in web.HTML_TEMPLATE:
    fail("served HTML lacks the escaped exit text")

print(json.dumps({"stage": str(stage), "python": sys.version.split()[0],
                  "modules": {rel: str(Path(m.__file__).resolve()) for rel, m in loaded.items()},
                  "epoch_n": metrics["closed_trades"], "exit_distribution": distribution,
                  "recent_rows_checked": len(recent), "sell_fixture": fixture["direction"]}, indent=2))
print("STAGING_VERIFIED")
