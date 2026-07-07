"""SSH access to the LANforge OS, wrapped for async use.

paramiko is synchronous, so every blocking call is pushed onto a worker thread
via ``anyio.to_thread`` — the MCP event loop never blocks on the network.
"""

from __future__ import annotations

import logging
import threading
import time

import anyio
import paramiko

from ..errors import SshError, TimeoutError_
from ..models import ShellResult, SystemConfig

logger = logging.getLogger(__name__)

MAX_CAPTURE_BYTES = 512 * 1024  # keep tool responses LLM-sized


class LFSshClient:
    def __init__(self, system: SystemConfig):
        self.system = system
        self._client: paramiko.SSHClient | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- sync core

    def _connect_sync(self) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs: dict = {
            "hostname": self.system.host,
            "port": self.system.ssh_port,
            "username": self.system.ssh_username,
            "timeout": self.system.connect_timeout_sec,
            "allow_agent": False,
            "look_for_keys": False,
        }
        if self.system.ssh_key_file:
            kwargs["key_filename"] = self.system.ssh_key_file
        else:
            kwargs["password"] = self.system.ssh_password
        try:
            client.connect(**kwargs)
        except (paramiko.SSHException, OSError) as exc:
            raise SshError(
                f"SSH connection to {self.system.host}:{self.system.ssh_port} failed: {exc}",
                details={"system": self.system.id},
            ) from exc
        return client

    def _get_client_sync(self) -> paramiko.SSHClient:
        with self._lock:
            if self._client is not None:
                transport = self._client.get_transport()
                if transport is not None and transport.is_active():
                    return self._client
                self._client.close()
                self._client = None
            self._client = self._connect_sync()
            return self._client

    def _exec_sync(self, command: str, timeout: float) -> ShellResult:
        client = self._get_client_sync()
        started = time.monotonic()
        try:
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            channel = stdout.channel
            out = stdout.read(MAX_CAPTURE_BYTES)
            err = stderr.read(MAX_CAPTURE_BYTES)
            truncated = len(out) >= MAX_CAPTURE_BYTES or len(err) >= MAX_CAPTURE_BYTES
            exit_code = channel.recv_exit_status()
        except TimeoutError as exc:  # paramiko raises socket.timeout (alias of TimeoutError)
            raise TimeoutError_(
                f"SSH command timed out after {timeout}s: {command[:120]}",
                details={"system": self.system.id},
            ) from exc
        except (paramiko.SSHException, OSError) as exc:
            # Connection likely dropped; forget it so next call reconnects.
            with self._lock:
                if self._client is not None:
                    self._client.close()
                    self._client = None
            raise SshError(f"SSH execution failed: {exc}", details={"command": command[:200]}) from exc
        return ShellResult(
            command=command,
            stdout=out.decode("utf-8", errors="replace"),
            stderr=err.decode("utf-8", errors="replace"),
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            truncated=truncated,
        )

    def _read_file_sync(self, path: str, max_bytes: int = 2 * 1024 * 1024) -> str:
        client = self._get_client_sync()
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open(path, "r") as fh:
                    data = fh.read(max_bytes)
            finally:
                sftp.close()
        except (paramiko.SSHException, OSError) as exc:
            raise SshError(f"SFTP read of {path} failed: {exc}") from exc
        return data.decode("utf-8", errors="replace")

    # ------------------------------------------------------------ async API

    async def exec(self, command: str, timeout: float = 60.0) -> ShellResult:
        return await anyio.to_thread.run_sync(self._exec_sync, command, timeout)

    async def read_file(self, path: str) -> str:
        return await anyio.to_thread.run_sync(self._read_file_sync, path)

    async def close(self) -> None:
        def _close() -> None:
            with self._lock:
                if self._client is not None:
                    self._client.close()
                    self._client = None

        await anyio.to_thread.run_sync(_close)
