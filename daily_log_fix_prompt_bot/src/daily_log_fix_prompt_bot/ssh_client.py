"""SSH client for Hetzner server log fetching."""

import paramiko
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class SSHClient:
    """SSH client for remote log fetching.

    Defaults to strict SSH host key checking. This prevents silent MITM exposure
    when the audit bot fetches Hetzner logs remotely. For controlled local/dev
    scenarios only, callers may set strict_host_key_checking=False.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        key_path: str,
        known_hosts_path: str = "~/.ssh/known_hosts",
        strict_host_key_checking: bool = True,
    ):
        """Initialize SSH client."""
        self.host = host
        self.port = port
        self.user = user
        self.key_path = Path(key_path).expanduser()
        self.known_hosts_path = Path(known_hosts_path).expanduser()
        self.strict_host_key_checking = strict_host_key_checking
        self.client: Optional[paramiko.SSHClient] = None

    def connect(self) -> bool:
        """Establish SSH connection."""
        try:
            self.client = paramiko.SSHClient()
            self.client.load_system_host_keys()

            if self.known_hosts_path.exists():
                self.client.load_host_keys(str(self.known_hosts_path))
            elif self.strict_host_key_checking:
                log.warning(
                    "Known hosts file does not exist: %s; strict SSH host key "
                    "checking will reject unknown hosts",
                    self.known_hosts_path,
                )

            if self.strict_host_key_checking:
                self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
            else:
                log.warning(
                    "SSH_STRICT_HOST_KEY_CHECKING is disabled; unknown host keys "
                    "will be auto-added. Use only for controlled dev/local runs."
                )
                self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            self.client.connect(
                self.host,
                port=self.port,
                username=self.user,
                key_filename=str(self.key_path),
                timeout=10,
            )
            log.info(f"SSH connected to {self.user}@{self.host}:{self.port}")
            return True
        except Exception as e:
            log.error(f"SSH connection failed: {e}")
            return False

    def execute(self, command: str) -> tuple[str, str, int]:
        """Execute remote command and return stdout, stderr, exit code."""
        if not self.client:
            raise RuntimeError("Not connected; call connect() first")
        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=30)
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            exit_code = stdout.channel.recv_exit_status()
            return out, err, exit_code
        except Exception as e:
            log.error(f"Command execution failed: {e}")
            return "", str(e), 1

    def close(self):
        """Close SSH connection."""
        if self.client:
            self.client.close()
            log.info("SSH connection closed")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, *args):
        """Context manager exit."""
        self.close()
