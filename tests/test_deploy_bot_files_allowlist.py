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
    ]


def test_allowed_keys_exclude_costs_exits_and_real_trading():
    keys = _list("ALLOWED_KEYS")
    assert "PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED" in keys
    forbidden = re.compile(r"(TP|SL|FEE|SLIPPAGE|COST_MODEL|TRADING_MODE|REAL|LIVE|ORDER|EXECUT)")
    assert not [k for k in keys if forbidden.search(k) and k != "PAPER_COST_EXPLORATION_ENABLED"]


def test_files_exclude_execution_cost_and_mode_modules():
    for path in _list("ALLOWED_FILES"):
        assert not re.search(r"(executor|execution|cost_model|runtime_mode|risk|signal_router)", path), path


def test_phase_refresh_flag_value_is_validated_strictly():
    assert 'env.get("PAPER_COMPLETED_CANDLE_PHASE_REFRESH_ENABLED", "false") in {"true", "false"}' in TEXT
