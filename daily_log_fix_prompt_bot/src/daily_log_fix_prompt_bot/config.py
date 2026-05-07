"""Configuration for daily log fix prompt bot."""

from pathlib import Path
from dataclasses import dataclass
import os


_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in _TRUE_VALUES


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, default)).strip())
    except Exception:
        return default


@dataclass
class Settings:
    """Bot configuration from environment."""

    hetzner_host: str = "127.0.0.1"
    hetzner_port: int = 22
    hetzner_user: str = "root"
    ssh_key_path: str = "~/.ssh/id_ed25519"
    service_name: str = "cryptomaster"
    log_lookback_hours: int = 24
    local_report_dir: str = "reports"
    project_root: str = "/opt/CryptoMaster_srv"
    remote_log_glob: str = "/var/log/cryptomaster/*.log"
    use_journalctl: bool = True
    max_log_lines: int = 50000
    sanitize_secrets: bool = True
    enable_remote_write: bool = False
    enable_auto_fix: bool = False
    llm_provider: str = "none"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    save_unsanitized_raw_logs: bool = False


def load_config() -> Settings:
    """Load configuration from environment.

    Defaults are intentionally safe: no remote writes, no auto-fix, and no
    unsanitized raw log persistence unless explicitly enabled.
    """
    return Settings(
        hetzner_host=os.getenv("HETZNER_HOST", "127.0.0.1"),
        hetzner_port=_env_int("HETZNER_PORT", 22),
        hetzner_user=os.getenv("HETZNER_USER", "root"),
        ssh_key_path=os.getenv("SSH_KEY_PATH", "~/.ssh/id_ed25519"),
        service_name=os.getenv("SERVICE_NAME", "cryptomaster"),
        log_lookback_hours=_env_int("LOG_LOOKBACK_HOURS", 24),
        local_report_dir=os.getenv("LOCAL_REPORT_DIR", "reports"),
        project_root=os.getenv("PROJECT_ROOT", "/opt/CryptoMaster_srv"),
        remote_log_glob=os.getenv("REMOTE_LOG_GLOB", "/var/log/cryptomaster/*.log"),
        use_journalctl=_env_bool("USE_JOURNALCTL", True),
        max_log_lines=_env_int("MAX_LOG_LINES", 50000),
        sanitize_secrets=_env_bool("SANITIZE_SECRETS", True),
        enable_remote_write=_env_bool("ENABLE_REMOTE_WRITE", False),
        enable_auto_fix=_env_bool("ENABLE_AUTO_FIX", False),
        llm_provider=os.getenv("LLM_PROVIDER", "none"),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        save_unsanitized_raw_logs=_env_bool("SAVE_UNSANITIZED_RAW_LOGS", False),
    )


def get_report_dir(config: Settings) -> Path:
    """Get dated report directory."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = Path(config.local_report_dir) / today
    report_path.mkdir(parents=True, exist_ok=True)
    return report_path
