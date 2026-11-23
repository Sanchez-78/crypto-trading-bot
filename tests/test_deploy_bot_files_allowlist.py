"""Static guard on deploy/research_eval/deploy_bot_files.sh allowlists (reviewed changes only)."""
import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "research_eval" / "deploy_bot_files.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")


def _list(name):
    match = re.search(rf'^{name}="([^"]*)"$', TEXT, re.M)
    assert match, name
    return match.group(1).split()


def test_allowed_files_are_exactly_the_reviewed_set():
    assert _list("ALLOWED_FILES") == [
        "src/services/paper_source_learning.py", "src/services/paper_learning_budget.py",
        "src/services/candle_cache_v1.py", "src/services/p0_8_plus_live_pipeline.py",
        "src/services/paper_trade_executor.py",
        "src/services/v5_legacy_bridge/outbox.py", "src/services/v5_legacy_bridge/outbox_flush_worker.py",
        "src/services/realtime_decision_engine.py",
    ]
    # 2026-11-23: executor back after the approved bucket-cap code review (2026-11-19 re-review).
    assert "PAPER_EXPLORE_MAX_OPEN_PER_BUCKET" in _list("ALLOWED_KEYS")
    # 2026-11-23: ECON BAD journal-volume flag (code APPROVE, re-review r2); strict bool in the env check.
    assert "RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED" in _list("ALLOWED_KEYS")
    helper = (SCRIPT.parent / "deploy_env_check.py").read_text(encoding="utf-8")
    assert '"RDE_ECON_BAD_REJECT_LOG_LIMIT_ENABLED")' in helper.split("STRICT_BOOL_KEYS = ", 1)[1].split("\n", 1)[0]
    # the header no longer claims execution paths are excluded
    assert "REAL or\n# execution paths" not in TEXT


def test_live_preimage_is_checked_before_backup_and_right_before_install():
    # review 2026-11-19 B4: a live file changed after the review must never be silently overwritten.
    assert '"${EXPECTED_PREIMAGE_SHA256:?}"' in TEXT
    check = 'verify_pinned "$APP" "$FILES" "$EXPECTED_PREIMAGE_SHA256"'
    assert TEXT.count(check) == 2
    first, second = TEXT.index(check), TEXT.rindex(check)
    assert first < TEXT.index('cp -p "$APP/$f" "$BACKUP/$f"')               # before the backup
    assert TEXT.index("trap 'rollback") < second < TEXT.index('install_staged "$PINNED" "$APP" "$FILES"')
    assert TEXT.index("for _ in $(seq 1 60); do") < second                   # after the positions wait
    block = TEXT[second:TEXT.index('install_staged "$PINNED" "$APP" "$FILES"')]
    assert "trap - ERR INT TERM" in block and "exit 2" in block and "rollback" not in block.split("fi", 1)[0]


def test_journal_check_fails_closed():
    # review 2026-11-19 B1: journalctl failure or an empty journal must roll back, never pass.
    assert "--no-pager > \"$JOURNAL\" || true" not in TEXT
    assert 'rollback "journal unreadable"' in TEXT and 'rollback "journal empty since restart"' in TEXT


def test_nested_paths_are_backed_up_and_basenames_unique():
    # 2026-11-19: v5_legacy_bridge/* live below src/services; the backup must create each
    # file's own directory, and the flat source dir needs unique basenames.
    assert 'mkdir -p "$BACKUP/$(dirname "$f")"; cp -p "$APP/$f" "$BACKUP/$f"' in TEXT
    assert 'mkdir -p "$BACKUP/src/services"\n' not in TEXT
    assert "duplicate basename in FILES" in TEXT
    names = [p.rsplit("/", 1)[-1] for p in _list("ALLOWED_FILES")]
    assert len(names) == len(set(names))


# Executor exception: bucket-cap code approved 2026-11-19; deploy step reviewed separately.
EXECUTOR_EXCEPTION = "src/services/paper_trade_executor.py"


def test_allowed_keys_exclude_costs_exits_and_real_trading():
    keys = _list("ALLOWED_KEYS")
    assert "PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED" in keys
    forbidden = re.compile(r"(TP|SL|FEE|SLIPPAGE|COST_MODEL|TRADING_MODE|REAL|LIVE|ORDER|EXECUT)")
    assert not [k for k in keys if forbidden.search(k) and k != "PAPER_COST_EXPLORATION_ENABLED"]


def test_files_exclude_execution_cost_and_mode_modules():
    for path in _list("ALLOWED_FILES"):
        if path == EXECUTOR_EXCEPTION:
            continue
        assert not re.search(r"(executor|execution|cost_model|runtime_mode|risk|signal_router)", path), path


def test_review_77_guards_present():
    # P3 + review 78 R1: pinned bytes are staged once; validation, install and postimage use them.
    assert '"${EXPECTED_SHA256:?}"' in TEXT and '. "$HERE/deploy_pinned.sh"' in TEXT
    assert 'stage_files "$NEW" "$PINNED" "$FILES"' in TEXT
    assert TEXT.count('"$NEW') == 1  # the source is read exactly once (stage_files)
    assert 'install_staged "$PINNED" "$APP" "$FILES"' in TEXT
    assert TEXT.count('verify_pinned "$APP" "$FILES" "$EXPECTED_SHA256"') == 2  # after install + postimage
    assert 'ReadWritePaths="$SCRATCH"' in TEXT and "trap 'rm -rf \"$STAGE_DIR\" \"$SCRATCH\"' EXIT" in TEXT
    # review 79 N1: bytecode-free validation tree, empty pycache prefix, source identity asserted.
    assert 'build_tree "$APP" "$PINNED" "$TREE" "$FILES"' in TEXT
    # review 80 N2: isolated interpreter (-I ignores PYTHONOPTIMIZE etc.), prefix via -X, explicit refusals.
    assert '/usr/bin/python3 -I -B -X pycache_prefix="$SCRATCH/pycache" -' in TEXT
    assert "deploy_env_check.verify_staged_import(" in TEXT and 'STAGED_IMPORT REFUSED' in TEXT
    assert 'cp -r "$APP/src" "$TREE/src"' not in TEXT
    # P1: effective env via deploy_env_check before, and the real MainPID environment after.
    assert "deploy_env_check.preflight(" in TEXT
    assert 'post --environ "/proc/$pid/environ"' in TEXT
    assert 'systemctl show cryptomaster -p Environment --value)"\nfor kv in' not in TEXT
    # P2: staged import of every deployed module inside a read-only sandbox.
    assert "-p ProtectSystem=strict" in TEXT and 'ReadWritePaths="$STAGE_DIR"' not in TEXT
    helper = (SCRIPT.parent / "deploy_env_check.py").read_text(encoding="utf-8")
    assert 'importlib.import_module(path.removesuffix(".py").replace("/", "."))' in helper
    # The comment no longer claims the allowlist prevents executor changes.
    assert "no admission, cost, TP/SL or execution change" not in TEXT


def test_open_positions_opt_in_is_explicit_logged_and_default_waits():
    # 2026-11-23 operator instruction: deploy may restart with open PAPER positions only on an
    # explicit ALLOW_OPEN_POSITIONS=1; unset keeps the zero-open wait; unreadable state never passes.
    assert 'if [ "${ALLOW_OPEN_POSITIONS:-0}" = 1 ]; then' in TEXT
    block = TEXT.split('if [ "${ALLOW_OPEN_POSITIONS:-0}" = 1 ]; then', 1)[1].split("\nfi\n", 1)[0]
    assert 'log "OPEN_POSITIONS_ALLOWED open=$open (operator opt-in)"' in block
    assert '[ "$open" != err ] || { log "SKIPPED positions state unreadable"; exit 3; }' in block
    assert 'if [ "$open" != 0 ]; then log "SKIPPED open=$open"; exit 3; fi' in TEXT
    assert TEXT.index("ALLOW_OPEN_POSITIONS") < TEXT.index("trap 'rollback")   # before any live change
