"""Tests for health_reporter.py — Hetzner health report builder."""

import json
import sys
from pathlib import Path

import pytest

# Ensure both repo root and auditbot src are on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
AUDITBOT_SRC = REPO_ROOT / "daily_log_fix_prompt_bot" / "src"
for _p in (REPO_ROOT, AUDITBOT_SRC):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from daily_log_fix_prompt_bot.health_reporter import (
    build_hetzner_health,
    write_health_reports,
    _build_markdown,
)


# ── Fixtures / helpers ─────────────────────────────────────────────────────────

_BOOT_LINE = "2026-05-07T10:00:01 [BOOT_VERSION] git_sha=abc1234 mode=paper_train"
_SAFETY_LINES = (
    "2026-05-07T10:00:02 live_allowed=false\n"
    "2026-05-07T10:00:03 ENABLE_REAL_ORDERS=false\n"
    "2026-05-07T10:00:04 LIVE_TRADING_CONFIRMED=false"
)
_ACTIVITY_LINES = (
    "2026-05-07T10:01:00 [PAPER_TRAIN_ENTRY] symbol=BTCUSDT\n"
    "2026-05-07T10:02:00 [PAPER_EXIT] symbol=BTCUSDT reason=TP\n"
    "2026-05-07T10:03:00 [LEARNING_UPDATE] ok=True source=paper_closed_trade\n"
    "2026-05-07T10:04:00 [APP_METRICS_SAVE] ok=True"
)

_CLEAN_LOGS = "\n".join([_BOOT_LINE, _SAFETY_LINES, _ACTIVITY_LINES])


# ── Status tests ───────────────────────────────────────────────────────────────

def test_health_ok_from_clean_paper_train_logs():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    assert h["status"] == "OK"
    assert h["trading_mode"] == "paper_train"
    assert h["boot_version_seen"] is True
    assert h["live_allowed"] is False
    assert h["enable_real_orders"] is False
    assert h["live_trading_confirmed"] is False
    assert h["paper_train_entry_count"] == 1
    assert h["learning_update_ok_count"] == 1


def test_health_warning_when_no_learning_entries_yet():
    logs = "\n".join([_BOOT_LINE, _SAFETY_LINES])
    h = build_hetzner_health(logs, log_source="local_journalctl")
    assert h["status"] == "WARNING"
    assert h["paper_train_entry_count"] == 0
    assert h["learning_update_ok_count"] == 0
    assert any("PAPER_TRAIN_ENTRY" in w for w in h["warnings"])


def test_health_critical_when_live_real_detected():
    logs = (
        "2026-05-07T10:00:01 [BOOT_VERSION] git_sha=abc1234 mode=live_real\n"
        "2026-05-07T10:00:02 live_allowed=true"
    )
    h = build_hetzner_health(logs)
    assert h["status"] == "CRITICAL"
    assert any("live_real" in c for c in h["critical"])


def test_health_critical_when_enable_real_orders_true():
    logs = (
        f"{_BOOT_LINE}\n"
        "2026-05-07T10:00:02 live_allowed=false\n"
        "2026-05-07T10:00:03 ENABLE_REAL_ORDERS=true"
    )
    h = build_hetzner_health(logs)
    assert h["status"] == "CRITICAL"
    assert any("ENABLE_REAL_ORDERS" in c for c in h["critical"])


def test_health_critical_when_live_trading_confirmed_true():
    logs = (
        f"{_BOOT_LINE}\n"
        "live_allowed=false\n"
        "LIVE_TRADING_CONFIRMED=true"
    )
    h = build_hetzner_health(logs)
    assert h["status"] == "CRITICAL"
    assert any("LIVE_TRADING_CONFIRMED" in c for c in h["critical"])


def test_health_critical_when_learning_errors_present():
    logs = (
        f"{_BOOT_LINE}\n"
        "live_allowed=false\n"
        "2026-05-07T10:05:00 [LEARNING_UPDATE_ERROR] Firebase write failed"
    )
    h = build_hetzner_health(logs)
    assert h["status"] == "CRITICAL"
    assert h["learning_update_error_count"] == 1
    assert any("LEARNING_UPDATE_ERROR" in c for c in h["critical"])


def test_health_unknown_when_logs_empty():
    h = build_hetzner_health("", log_source="empty")
    assert h["status"] == "UNKNOWN"
    assert h["log_lines_analyzed"] == 0
    assert len(h["warnings"]) > 0


def test_health_unknown_when_no_boot_and_no_mode():
    logs = "2026-05-07T10:00:01 Some random log line with no markers"
    h = build_hetzner_health(logs)
    assert h["status"] == "UNKNOWN"


# ── Extraction tests ───────────────────────────────────────────────────────────

def test_health_extracts_boot_version_git_sha():
    logs = "2026-05-07T10:00:01 [BOOT_VERSION] git_sha=deadbeef123 mode=paper_train"
    h = build_hetzner_health(logs)
    assert h["boot_version_seen"] is True
    assert h["deployed_git_sha"] == "deadbeef123"


def test_health_extracts_trading_mode_from_trading_mode_env():
    logs = "2026-05-07T10:00:01 TRADING_MODE=paper_train live_allowed=false"
    h = build_hetzner_health(logs)
    assert h["trading_mode"] == "paper_train"


def test_health_counts_learning_markers():
    logs = "\n".join([
        _BOOT_LINE,
        "live_allowed=false",
        "[LEARNING_UPDATE] ok=True source=paper_closed_trade",
        "[LEARNING_UPDATE] ok=True source=paper_closed_trade",
        "[PAPER_TRAIN_ENTRY] symbol=BTCUSDT",
        "[PAPER_EXIT] symbol=BTCUSDT reason=TP",
        "[APP_METRICS_SAVE] ok=True",
        "[TIMEOUT_NO_PRICE] trade_id=paper_xyz",
        "[BUCKET_METRICS_ERROR] key=FLAT/RANGING",
    ])
    h = build_hetzner_health(logs)
    assert h["learning_update_ok_count"] == 2
    assert h["paper_train_entry_count"] == 1
    assert h["paper_exit_count"] == 1
    assert h["app_metrics_save_ok_count"] == 1
    assert h["timeout_no_price_count"] == 1
    assert h["bucket_metrics_error_count"] == 1


def test_health_extracts_last_timestamp():
    logs = (
        "2026-05-07T10:00:01 first line\n"
        "2026-05-07T10:05:33 last line"
    )
    h = build_hetzner_health(logs)
    assert h["last_log_timestamp"] == "2026-05-07T10:05:33"


# ── File output tests ──────────────────────────────────────────────────────────

def test_write_health_reports_writes_dated_and_latest_files(tmp_path):
    dated_dir = tmp_path / "reports" / "2026-05-07"
    local_report_dir = str(tmp_path / "reports")
    health = build_hetzner_health(_CLEAN_LOGS, log_source="remote")

    write_health_reports(dated_dir, local_report_dir, health)

    assert (dated_dir / "hetzner_health.json").exists()
    assert (dated_dir / "hetzner_health.md").exists()
    assert (tmp_path / "reports" / "latest_health.json").exists()
    assert (tmp_path / "reports" / "latest_health.md").exists()


def test_write_health_reports_json_is_valid(tmp_path):
    dated_dir = tmp_path / "reports" / "2026-05-07"
    health = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    write_health_reports(dated_dir, str(tmp_path / "reports"), health)

    raw = (dated_dir / "hetzner_health.json").read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert parsed["schema_version"] == "hetzner_health_v1"
    assert parsed["status"] == "OK"


def test_write_health_reports_latest_matches_dated(tmp_path):
    dated_dir = tmp_path / "reports" / "2026-05-07"
    health = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    write_health_reports(dated_dir, str(tmp_path / "reports"), health)

    dated_json = (dated_dir / "hetzner_health.json").read_text(encoding="utf-8")
    latest_json = (tmp_path / "reports" / "latest_health.json").read_text(encoding="utf-8")
    assert dated_json == latest_json


# ── Markdown tests ─────────────────────────────────────────────────────────────

def test_health_markdown_contains_mobile_sections():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    md = _build_markdown(h)
    for section in (
        "## Status",
        "## Runtime",
        "## Testovací trading a učení",
        "## Readiness",
        "## Evidence",
        "## Warnings",
        "## Critical",
        "## Next steps",
    ):
        assert section in md, f"Missing section: {section}"


def test_health_markdown_ok_shows_checkmark():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    md = _build_markdown(h)
    assert "✅" in md


def test_health_markdown_critical_shows_alarm():
    logs = (
        "2026-05-07T10:00:01 [BOOT_VERSION] git_sha=abc mode=live_real\n"
        "live_allowed=true"
    )
    h = build_hetzner_health(logs)
    md = _build_markdown(h)
    assert "🚨" in md


# ── Readiness tests ───────────────────────────────────────────────────────────

def test_readiness_paper_train_ok_set_for_clean_run():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    assert h["readiness"]["paper_train_ok"] is True


def test_readiness_paper_live_not_ready_without_enough_data():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    # Only 1 learning update — needs >= 10
    assert h["readiness"]["paper_live_ready"] is False


def test_readiness_shadow_and_live_never_auto_set():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="remote")
    assert h["readiness"]["shadow_live_ready"] is False
    assert h["readiness"]["live_real_guarded_ready"] is False


def test_health_never_ok_when_logs_empty():
    h = build_hetzner_health("", log_source="empty")
    assert h["status"] != "OK"


def test_health_schema_version_present():
    h = build_hetzner_health("", log_source="empty")
    assert h["schema_version"] == "hetzner_health_v1"


def test_health_log_source_preserved():
    h = build_hetzner_health(_CLEAN_LOGS, log_source="local_journalctl")
    assert h["log_source"] == "local_journalctl"
