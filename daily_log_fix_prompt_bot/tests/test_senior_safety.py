"""Senior safety regression tests for audit bot and app metrics."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

# The audit bot uses a src/ layout and is not installed as a package in CI.
# Add both repo root and auditbot src explicitly for fresh GitHub Actions checkouts.
REPO_ROOT = Path(__file__).resolve().parents[2]
AUDITBOT_SRC = REPO_ROOT / "daily_log_fix_prompt_bot" / "src"
for path in (REPO_ROOT, AUDITBOT_SRC):
    path_s = str(path)
    if path_s not in sys.path:
        sys.path.insert(0, path_s)

from daily_log_fix_prompt_bot.config import Settings, load_config
from daily_log_fix_prompt_bot.log_fetcher import LogFetcher, _SAFE_GLOB_RE
from daily_log_fix_prompt_bot.models import LogMetrics
from daily_log_fix_prompt_bot.report_writer import ReportWriter


def test_config_loads_safety_flags(monkeypatch):
    monkeypatch.setenv("ENABLE_AUTO_FIX", "true")
    monkeypatch.setenv("ENABLE_REMOTE_WRITE", "true")
    monkeypatch.setenv("SAVE_UNSANITIZED_RAW_LOGS", "true")
    monkeypatch.setenv("MAX_LOG_LINES", "123")
    cfg = load_config()
    assert cfg.enable_auto_fix is True
    assert cfg.enable_remote_write is True
    assert cfg.save_unsanitized_raw_logs is True
    assert cfg.max_log_lines == 123


def test_config_defaults_do_not_save_unsanitized_raw_logs(monkeypatch):
    monkeypatch.delenv("SAVE_UNSANITIZED_RAW_LOGS", raising=False)
    cfg = load_config()
    assert cfg.save_unsanitized_raw_logs is False


def test_fix_prompt_does_not_hardcode_stale_commit(tmp_path: Path):
    out = tmp_path / "fix_prompt_final.md"
    ReportWriter().write_fix_prompt(out, LogMetrics(), [])
    text = out.read_text(encoding="utf-8")
    assert "53acfef" not in text
    assert "current checked-out commit" in text


def test_fix_prompt_does_not_say_push_to_main(tmp_path: Path):
    out = tmp_path / "fix_prompt_final.md"
    ReportWriter().write_fix_prompt(out, LogMetrics(), [])
    text = out.read_text(encoding="utf-8")
    assert "Push to origin/main" not in text
    assert "push directly to `main`" in text
    assert "Create a new branch" in text


def test_fix_prompt_says_no_deploy(tmp_path: Path):
    out = tmp_path / "fix_prompt_final.md"
    ReportWriter().write_fix_prompt(out, LogMetrics(), [])
    text = out.read_text(encoding="utf-8")
    assert "Do not deploy or restart production" in text
    assert "Deploy only through a separate deployment prompt/checklist" in text


def test_app_metrics_contract_has_no_hidden_learning_monitor_import():
    import inspect
    import src.services.app_metrics_contract as contract

    source = inspect.getsource(contract)
    assert "learning_monitor" not in source
    assert "lm_health" not in source


def test_learning_confidence_momentum_from_session_metrics():
    from src.services.app_metrics_contract import build_app_metrics_snapshot

    snapshot = build_app_metrics_snapshot(
        closed_trades=[],
        session_metrics={"confidence_momentum": "RISING"},
        open_positions=[],
        last_signals={},
        now=1_000_000.0,
    )
    assert snapshot["learning"]["confidence_momentum"] == "RISING"


def test_app_metrics_window_count_matches_loaded_trades():
    from src.services.app_metrics_contract import build_app_metrics_snapshot

    trades = [
        {"profit": 0.01, "close_reason": "TP", "timestamp": 1_000_000.0},
        {"profit": -0.02, "close_reason": "SL", "timestamp": 1_000_001.0},
    ]
    snapshot = build_app_metrics_snapshot(
        closed_trades=trades,
        session_metrics={},
        open_positions=[],
        last_signals={},
        now=1_000_010.0,
        window_limit_requested=100,
    )
    assert snapshot["window"]["count"] == 2
    assert snapshot["window"]["actual_loaded"] == 2
    assert snapshot["window"]["limit_requested"] == 100
    assert snapshot["window"]["limit_configured"] >= 2


def test_log_fetcher_uses_local_journalctl_when_ssh_unavailable(monkeypatch):
    cfg = Settings(service_name="cryptomaster", use_journalctl=True, max_log_lines=50000)

    # Avoid real SSH creation in unit test.
    monkeypatch.setattr("daily_log_fix_prompt_bot.log_fetcher.SSHClient", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no ssh")))

    class FakeCompleted:
        returncode = 0
        stdout = "2026-05-07 cryptomaster[1]: [BOOT_VERSION] git_sha=abc mode=paper_train\n"
        stderr = ""

    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return FakeCompleted()

    monkeypatch.setattr("daily_log_fix_prompt_bot.log_fetcher.subprocess.run", fake_run)

    fetcher = LogFetcher(cfg)
    logs = fetcher.fetch_logs()

    assert "[BOOT_VERSION]" in logs
    assert fetcher.last_source == "local_journalctl"
    assert calls[0][:3] == ["journalctl", "-u", "cryptomaster"]


def test_log_fetcher_falls_back_to_local_file_when_journalctl_fails(monkeypatch, tmp_path: Path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    cfg = Settings(
        service_name="cryptomaster",
        use_journalctl=True,
        max_log_lines=50000,
        project_root=str(project_dir),
    )
    monkeypatch.setattr("daily_log_fix_prompt_bot.log_fetcher.SSHClient", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no ssh")))

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "journal unavailable"

    monkeypatch.setattr("daily_log_fix_prompt_bot.log_fetcher.subprocess.run", lambda *args, **kwargs: FakeCompleted())

    bot_log = project_dir / "bot.log"
    bot_log.write_text("local bot log line", encoding="utf-8")

    fetcher = LogFetcher(cfg)
    logs = fetcher.fetch_logs()

    assert "local bot log line" in logs
    assert fetcher.last_source == "local_file"


def test_log_fetcher_remote_journalctl_command_quotes_service_name(monkeypatch):
    """BUG-068: service_name is shlex-quoted in the remote journalctl command."""
    cfg = Settings(service_name="my-service", use_journalctl=True, log_lookback_hours=24)

    captured = {}

    class FakeSSH:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, command):
            captured["command"] = command
            return "", "", 0

    monkeypatch.setattr("daily_log_fix_prompt_bot.log_fetcher.SSHClient", lambda *args, **kwargs: FakeSSH())

    fetcher = LogFetcher(cfg)
    fetcher._fetch_journalctl_remote()

    assert "my-service" in captured["command"]
    # shlex.quote leaves safe names unchanged; confirm no bare metachar injection possible
    import shlex
    assert shlex.quote(cfg.service_name) in captured["command"]


def test_log_fetcher_remote_file_logs_rejects_unsafe_glob(monkeypatch):
    """BUG-068: remote_log_glob with shell metacharacters raises ValueError."""
    cfg = Settings(remote_log_glob="/var/log/*.log; rm -rf /")

    class FakeSSH:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, command):
            return "", "", 0

    monkeypatch.setattr("daily_log_fix_prompt_bot.log_fetcher.SSHClient", lambda *args, **kwargs: FakeSSH())

    fetcher = LogFetcher(cfg)
    import pytest
    with pytest.raises(ValueError, match="Unsafe characters"):
        fetcher._fetch_file_logs_remote()


def test_run_daily_analysis_saves_sanitized_logs_not_raw_by_default(monkeypatch, tmp_path: Path):
    import daily_log_fix_prompt_bot.main as main_mod

    cfg = SimpleNamespace(
        local_report_dir=str(tmp_path),
        service_name="cryptomaster",
        log_lookback_hours=24,
        sanitize_secrets=True,
        save_unsanitized_raw_logs=False,
    )
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    class FakeFetcher:
        def __init__(self, config):
            pass
        def fetch_logs(self):
            return "API_KEY=SECRET123\nnormal line"

    class FakeSanitizer:
        def sanitize(self, text):
            return text.replace("SECRET123", "[REDACTED]")

    class FakeParser:
        def parse(self, text):
            return {"events": [], "metrics": {}}

    class FakeDetector:
        def detect(self, events, metrics, text):
            return []

    monkeypatch.setattr(main_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(main_mod, "get_report_dir", lambda config: report_dir)
    monkeypatch.setattr(main_mod, "LogFetcher", FakeFetcher)
    monkeypatch.setattr(main_mod, "Sanitizer", FakeSanitizer)
    monkeypatch.setattr(main_mod, "LogParser", FakeParser)
    monkeypatch.setattr(main_mod, "IssueDetector", FakeDetector)

    main_mod.run_daily_analysis()

    assert (report_dir / "sanitized_logs.txt").exists()
    assert "SECRET123" not in (report_dir / "sanitized_logs.txt").read_text(encoding="utf-8")
    assert not (report_dir / "raw_logs.txt").exists()


def test_run_daily_analysis_raw_logs_only_when_enabled(monkeypatch, tmp_path: Path):
    import daily_log_fix_prompt_bot.main as main_mod

    cfg = SimpleNamespace(
        local_report_dir=str(tmp_path),
        service_name="cryptomaster",
        log_lookback_hours=24,
        sanitize_secrets=True,
        save_unsanitized_raw_logs=True,
    )
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    class FakeFetcher:
        def __init__(self, config):
            pass
        def fetch_logs(self):
            return "API_KEY=SECRET123\nnormal line"

    class FakeSanitizer:
        def sanitize(self, text):
            return text.replace("SECRET123", "[REDACTED]")

    class FakeParser:
        def parse(self, text):
            return {"events": [], "metrics": {}}

    class FakeDetector:
        def detect(self, events, metrics, text):
            return []

    monkeypatch.setattr(main_mod, "load_config", lambda: cfg)
    monkeypatch.setattr(main_mod, "get_report_dir", lambda config: report_dir)
    monkeypatch.setattr(main_mod, "LogFetcher", FakeFetcher)
    monkeypatch.setattr(main_mod, "Sanitizer", FakeSanitizer)
    monkeypatch.setattr(main_mod, "LogParser", FakeParser)
    monkeypatch.setattr(main_mod, "IssueDetector", FakeDetector)

    main_mod.run_daily_analysis()

    assert (report_dir / "raw_logs.txt").exists()
    assert "SECRET123" in (report_dir / "raw_logs.txt").read_text(encoding="utf-8")


# ── Glob regex tests ────────────────────────────────────────────────────────


@pytest.mark.parametrize("pattern", [
    "/var/log/cryptomaster/*.log",
    "/var/log/cryptomaster/bot-2026-05-??.log",
    "/var/log/cryptomaster/bot-[0-9].log",
    "/var/log/cryptomaster/bot-[abc].log",
    "/opt/CryptoMaster_srv/bot.log",
    "/var/log/*.log",
])
def test_safe_glob_re_allows_valid_patterns(pattern):
    assert _SAFE_GLOB_RE.match(pattern), f"Should be allowed: {pattern!r}"


@pytest.mark.parametrize("pattern", [
    "/var/log/cryptomaster/*.log; rm -rf /",
    "/var/log/cryptomaster/*.log | cat",
    "/var/log/cryptomaster/$(whoami).log",
    "/var/log/cryptomaster/`whoami`.log",
    "/var/log/cryptomaster/*.log > /tmp/x",
    "/var/log/cryptomaster/*.log\n/etc/passwd",
])
def test_safe_glob_re_rejects_metacharacters(pattern):
    assert not _SAFE_GLOB_RE.match(pattern), f"Should be rejected: {pattern!r}"


# ── expanduser test ─────────────────────────────────────────────────────────


def test_fetch_local_logs_expands_user_tilde(monkeypatch, tmp_path: Path):
    """_fetch_local_logs calls expanduser() so ~/... paths resolve correctly."""
    home = tmp_path / "fakehome"
    project = home / "CryptoMaster_srv"
    project.mkdir(parents=True)
    bot_log = project / "bot.log"
    bot_log.write_text("tilde-expand log line", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "daily_log_fix_prompt_bot.log_fetcher.SSHClient",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("no ssh")),
    )

    cfg = Settings(project_root="~/CryptoMaster_srv", use_journalctl=False)
    fetcher = LogFetcher(cfg)
    logs = fetcher._fetch_local_logs()
    assert "tilde-expand log line" in logs
