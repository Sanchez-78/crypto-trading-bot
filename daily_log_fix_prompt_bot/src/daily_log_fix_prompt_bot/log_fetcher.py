"""Fetch logs from server or local sources."""

import logging
import subprocess
from pathlib import Path
from typing import Optional
from .config import Settings
from .ssh_client import SSHClient

log = logging.getLogger(__name__)


class LogFetcher:
    """Fetch logs from server or local sources."""

    def __init__(self, config: Settings):
        """Initialize log fetcher."""
        self.config = config
        self.ssh = None
        try:
            self.ssh = SSHClient(config.hetzner_host, config.hetzner_port,
                                config.hetzner_user, config.ssh_key_path)
        except Exception as e:
            log.warning(f"SSH client init failed: {e}; will use local logs only")

    def fetch_logs(self) -> str:
        """Fetch logs from server or local sources."""
        logs = ""

        # Try SSH if available
        if self.ssh:
            try:
                if self.config.use_journalctl:
                    logs += self._fetch_journalctl_remote()
                logs += self._fetch_file_logs_remote()
                if logs:
                    return logs
            except Exception as e:
                log.warning(f"Remote fetch failed: {e}; falling back to local")

        # Fallback to local logs
        logs = self._fetch_local_logs()

        # Limit to max lines
        lines = logs.split("\n")
        if len(lines) > self.config.max_log_lines:
            log.warning(f"Log exceeds {self.config.max_log_lines} lines; truncating")
            lines = lines[-self.config.max_log_lines:]
            logs = "\n".join(lines)

        return logs

    def _fetch_journalctl_remote(self) -> str:
        """Fetch logs from remote journalctl."""
        command = (
            f"journalctl -u {self.config.service_name} "
            f"--since '{self.config.log_lookback_hours} hours ago' "
            f"--no-pager -o short-iso"
        )

        with self.ssh as client:
            out, err, code = client.execute(command)
            if code != 0:
                log.warning(f"journalctl failed: {err}")
                return ""
            log.info(f"Fetched {len(out)} bytes from remote journalctl")
            return out

    def _fetch_file_logs_remote(self) -> str:
        """Fetch logs from remote files."""
        command = f"tail -n {self.config.max_log_lines} {self.config.remote_log_glob} 2>/dev/null"

        with self.ssh as client:
            out, err, code = client.execute(command)
            if code != 0:
                log.warning(f"File log fetch failed: {err}")
                return ""
            log.info(f"Fetched {len(out)} bytes from remote file logs")
            return out

    def _fetch_local_logs(self) -> str:
        """Fetch logs from local bot.log file."""
        local_log = Path("../bot.log")
        if local_log.exists():
            try:
                with open(local_log, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                log.info(f"Fetched {len(content)} bytes from local bot.log")
                return content
            except Exception as e:
                log.warning(f"Failed to read local logs: {e}")
        return ""
