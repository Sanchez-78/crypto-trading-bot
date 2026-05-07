"""SSH client for Hetzner server log fetching."""

import paramiko
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


class SSHClient:
    """SSH client for remote log fetching."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        key_path: str,
        known_hosts_path: str = "~/.ssh/known_hosts",
        strict_host_key_checking: bool = True,
    ):
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
            if self.strict_host_key_checking:
                # Load system-wide and user known_hosts; reject unknown keys.
                self.client.load_system_host_keys()
                if self.known_hosts_path.exists():
                    self.client.load_host_keys(str(self.known_hosts_path))
                self.client.set_missing_host_key_policy(paramiko.RejectPolicy())
            else:
                # Only acceptable in isolated test/local environments.
                log.warning(
                    "SSH host key checking disabled (SSH_STRICT_HOST_KEY_CHECKING=false)"
                    " — MITM attacks will not be detected"
                )
                self.client.set_missing_host_key_policy(paramiko.WarningPolicy())
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
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()
