"""Configuration for daily log fix prompt bot."""

from pathlib import Path
from dataclasses import dataclass
import os


@dataclass
class Settings:
    """Bot configuration from environment."""

    hetzner_host: str = "127.0.0.1"
    hetzner_port: int = 22
    hetzner_user: str = "root"
    ssh_key_path: str = "~/.ssh/id_ed25519"
    ssh_known_hosts_path: str = "~/.ssh/known_hosts"
    ssh_strict_host_key_checking: bool = True
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


def load_config() -> Settings:
    """Load configuration from environment."""
    return Settings(
        hetzner_host=os.getenv("HETZNER_HOST", "127.0.0.1"),
        hetzner_port=int(os.getenv("HETZNER_PORT", "22")),
        hetzner_user=os.getenv("HETZNER_USER", "root"),
        ssh_key_path=os.getenv("SSH_KEY_PATH", "~/.ssh/id_ed25519"),
        ssh_known_hosts_path=os.getenv("SSH_KNOWN_HOSTS_PATH", "~/.ssh/known_hosts"),
        ssh_strict_host_key_checking=os.getenv(
            "SSH_STRICT_HOST_KEY_CHECKING", "true"
        ).lower() not in ("false", "0", "no", "off"),
        service_name=os.getenv("SERVICE_NAME", "cryptomaster"),
        log_lookback_hours=int(os.getenv("LOG_LOOKBACK_HOURS", "24")),
        local_report_dir=os.getenv("LOCAL_REPORT_DIR", "reports"),
    )


def get_report_dir(config: Settings) -> Path:
    """Get dated report directory."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = Path(config.local_report_dir) / today
    report_path.mkdir(parents=True, exist_ok=True)
    return report_path
