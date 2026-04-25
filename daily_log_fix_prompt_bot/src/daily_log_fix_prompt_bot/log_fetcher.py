"""Fetch logs from Hetzner server."""

import logging
from typing import Optional
from .config import Settings
from .ssh_client import SSHClient

log = logging.getLogger(__name__)


class LogFetcher:
    """Fetch logs from remote server."""

    def __init__(self, config: Settings):
        """Initialize log fetcher."""
        self.config = config
        self.ssh = SSHClient(config.hetzner_host, config.hetzner_port,
                            config.hetzner_user, config.ssh_key_path)

    def fetch_logs(self) -> str:
        """Fetch logs from server using journalctl or file globbing."""
        logs = ""

        if self.config.use_journalctl:
            logs += self._fetch_journalctl()

        logs += self._fetch_file_logs()

        # Limit to max lines
        lines = logs.split("\n")
        if len(lines) > self.config.max_log_lines:
            log.warning(f"Log exceeds {self.config.max_log_lines} lines; truncating")
            lines = lines[-self.config.max_log_lines:]
            logs = "\n".join(lines)

        return logs

    def _fetch_journalctl(self) -> str:
        """Fetch logs from journalctl."""
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

            log.info(f"Fetched {len(out)} bytes from journalctl")
            return out

    def _fetch_file_logs(self) -> str:
        """Fetch logs from file glob."""
        command = f"tail -n {self.config.max_log_lines} {self.config.remote_log_glob} 2>/dev/null"

        with self.ssh as client:
            out, err, code = client.execute(command)
            if code != 0:
                log.warning(f"File log fetch failed: {err}")
                return ""

            log.info(f"Fetched {len(out)} bytes from file logs")
            return out
