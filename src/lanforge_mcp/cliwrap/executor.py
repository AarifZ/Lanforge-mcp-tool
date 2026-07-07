"""Execute arbitrary shell commands on the LANforge system, safely.

Returns structured JSON (stdout / stderr / exit_code / duration) and is gated
by the safety layer: read-only mode blocks it, destructive-looking commands
require confirmation, and everything is audit-logged.
"""

from __future__ import annotations

import logging

from ..connection.ssh_client import LFSshClient
from ..models import ShellResult
from ..safety import SafetyGuard

logger = logging.getLogger(__name__)


class ShellExecutor:
    def __init__(self, ssh: LFSshClient, safety: SafetyGuard):
        self.ssh = ssh
        self.safety = safety

    async def run(
        self,
        command: str,
        *,
        timeout: float = 60.0,
        confirm: bool = False,
        system_id: str = "",
    ) -> ShellResult:
        dry = self.safety.check_shell(command, confirm=confirm, system=system_id)
        if dry:
            return ShellResult(
                command=command,
                stdout="(dry-run: command not executed)",
                stderr="",
                exit_code=0,
                duration_ms=0,
            )
        return await self.ssh.exec(command, timeout=timeout)
