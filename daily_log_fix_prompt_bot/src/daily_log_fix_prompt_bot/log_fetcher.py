"""Fetch logs from server or local sources."""

import logging
import subprocess
from pathlib import Path
from .config import Settings
from .ssh_client import SSHClient

log = logging.getLogger(__name__)


class LogFetcher:
    """Fetch logs from server or local sources.

    Fetch order:
    1. Remote Hetzner journalctl/file logs over SSH when configured.
    2. Local systemd journalctl when this bot runs directly on Hetzner.
    3. Local bot.log fallback.
    """

    def __init__(self, config: Settings):
        """Initialize log fetcher."""
        self.config = config
        self.ssh = None
        self.last_source = "none"
        try:
            self.ssh = SSHClient(config.hetzner_host, config.hetzner_port,
                                config.hetzner_user, config.ssh_key_path)
        except Exception as e:
            log.warning(f"SSH client init failed: {e}; will use local logs only")

    def fetch_logs(self) -> str:
        """Fetch logs from remote or local sources."""
        logs = ""

        # Remote path: useful if audit bot runs outside Hetzner with SSH access.
        if self.ssh:
            try:
                if self.config.use_journalctl:
                    logs += self._fetch_journalctl_remote()
                logs += self._fetch_file_logs_remote()
                if logs:
                    self.last_source = "remote"
                    return self._limit_lines(logs)
            except Exception as e:
                log.warning(f"Remote fetch failed: {e}; falling back to local")

        # Local Hetzner path: lets scheduled audit run on the server with no user bash.
        if self.config.use_journalctl:
            logs = self._fetch_journalctl_local()
            if logs:
                self.last_source = "local_journalctl"
                return self._limit_lines(logs)

        # Last fallback: local file.
        logs = self._fetch_local_logs()
        if logs:
            self.last_source = "local_file"
        else:
            self.last_source = "empty"
        return self._limit_lines(logs)

    def _limit_lines(self, logs: str) -> str:
        """Limit logs to max_log_lines, keeping newest lines."""
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
                log.warning(f"Remote journalctl failed: {err}")
                return ""
            log.info(f"Fetched {len(out)} bytes from remote journalctl")
            return out

    def _fetch_file_logs_remote(self) -> str:
        """Fetch logs from remote files."""
        command = f"tail -n {self.config.max_log_lines} {self.config.remote_log_glob} 2>/dev/null"

        with self.ssh as client:
            out, err, code = client.execute(command)
            if code != 0:
                log.warning(f"Remote file log fetch failed: {err}")
                return ""
            log.info(f"Fetched {len(out)} bytes from remote file logs")
            return out

    def _fetch_journalctl_local(self) -> str:
        """Fetch logs from local systemd journalctl.

        Used when the audit bot is deployed on the same Hetzner server as the
        cryptomaster service. Returns empty string if journalctl is unavailable
        or cannot read the target service.
        """
        command = [
            "journalctl",
            "-u",
            self.config.service_name,
            "--since",
            f"{self.config.log_lookback_hours} hours ago",
            "--no-pager",
            "-o",
            "short-iso",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except FileNotFoundError:
            log.warning("Local journalctl unavailable; falling back to local file logs")
            return ""
        except subprocess.TimeoutExpired:
            log.warning("Local journalctl timed out; falling back to local file logs")
            return ""
        except Exception as e:
            log.warning(f"Local journalctl failed: {e}; falling back to local file logs")
            return ""

        if result.returncode != 0:
            log.warning(f"Local journalctl failed: {result.stderr.strip()}")
            return ""
        log.info(f"Fetched {len(result.stdout)} bytes from local journalctl")
        return result.stdout

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
