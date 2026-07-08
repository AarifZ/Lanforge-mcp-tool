"""Safety layer: read-only mode, dry-run, destructive-command confirmation, audit log.

Every mutating operation flows through :class:`SafetyGuard` before it reaches a
LANforge system. The guard can block (read-only), divert (dry-run), demand
confirmation (destructive commands), and always audit-logs the outcome.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import SafetyError
from .models import SafetyConfig

logger = logging.getLogger(__name__)

#: CLI command prefixes that delete state or disrupt the system.
DESTRUCTIVE_PREFIXES = (
    "rm_",
    "del_",
    "reset_",
    "clear_",
    "wipe_",
    "flush_",
)

#: Exact CLI commands that are destructive/disruptive without a rm_/reset_ prefix.
DESTRUCTIVE_COMMANDS = {
    "reboot",
    "shutdown",
    "quit",
    "exit",
    "shutdown_os",
    "reboot_os",
    "load",  # loading a DB replaces the running config
    "admin",
    "set_resource",  # can reboot/shutdown resources via its flags
}

#: Shell fragments that make an SSH command destructive.
DESTRUCTIVE_SHELL_MARKERS = ("rm -rf", "mkfs", "reboot", "shutdown", "poweroff", "dd if=", "> /dev/")


def is_destructive_command(command: str, extra: list[str] | None = None) -> bool:
    cmd = command.strip().lower()
    if cmd in DESTRUCTIVE_COMMANDS or (extra and cmd in {e.lower() for e in extra}):
        return True
    return cmd.startswith(DESTRUCTIVE_PREFIXES)


def is_destructive_shell(shell_command: str) -> bool:
    low = shell_command.lower()
    return any(marker in low for marker in DESTRUCTIVE_SHELL_MARKERS)


class AuditLog:
    """Append-only JSONL audit trail; thread-safe, never raises into callers."""

    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()

    def record(self, event: str, **fields: Any) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, default=str) + "\n")
        except OSError as exc:  # audit failure must not break operations
            logger.warning("audit log write failed: %s", exc)


class SafetyGuard:
    def __init__(self, config: SafetyConfig):
        self.config = config
        self.audit = AuditLog(config.audit_log_path)

    # Runtime toggles (exposed via the set_safety_mode tool).
    def set_modes(self, read_only: bool | None = None, dry_run: bool | None = None) -> dict[str, bool]:
        if read_only is not None:
            self.config.read_only = read_only
        if dry_run is not None:
            self.config.dry_run = dry_run
        self.audit.record("safety_mode_changed", read_only=self.config.read_only, dry_run=self.config.dry_run)
        return {"read_only": self.config.read_only, "dry_run": self.config.dry_run}

    def check_command(self, command: str, params: dict[str, Any], *, confirm: bool, system: str) -> bool:
        """Gate a /cli-json mutation. Returns True if this should be a dry-run."""
        if self.config.read_only:
            self.audit.record("blocked_read_only", kind="command", command=command, system=system)
            raise SafetyError(
                f"Read-only mode is active; refusing to execute '{command}'.",
                details={"command": command},
            )
        if (
            self.config.require_confirmation
            and is_destructive_command(command, self.config.extra_destructive_commands)
            and not confirm
        ):
            self.audit.record("confirmation_required", kind="command", command=command, system=system)
            raise SafetyError(
                f"'{command}' is destructive and requires confirmation.",
                details={"command": command, "params": params},
                hint="Re-issue the call with confirm=true after verifying the target with a query.",
            )
        self.audit.record(
            "command", command=command, params=params, system=system, dry_run=self.config.dry_run
        )
        return self.config.dry_run

    def check_shell(self, shell_command: str, *, confirm: bool, system: str) -> bool:
        """Gate an SSH shell execution. Returns True if this should be a dry-run."""
        if self.config.read_only:
            self.audit.record("blocked_read_only", kind="shell", command=shell_command, system=system)
            raise SafetyError("Read-only mode is active; refusing to run shell commands.")
        if not self.config.allow_shell:
            self.audit.record("blocked_shell_disabled", command=shell_command, system=system)
            raise SafetyError(
                "Shell execution is disabled by configuration (safety.allow_shell=false)."
            )
        if self.config.require_confirmation and is_destructive_shell(shell_command) and not confirm:
            self.audit.record("confirmation_required", kind="shell", command=shell_command, system=system)
            raise SafetyError(
                "This shell command looks destructive and requires confirmation.",
                details={"command": shell_command},
                hint="Re-issue the call with confirm=true if you are certain.",
            )
        self.audit.record("shell", command=shell_command, system=system, dry_run=self.config.dry_run)
        return self.config.dry_run

    def check_script(self, script: str, args: list[str], *, system: str) -> bool:
        """Gate a py-script run. Returns True if this should be a dry-run."""
        if self.config.read_only:
            self.audit.record("blocked_read_only", kind="script", script=script, system=system)
            raise SafetyError(f"Read-only mode is active; refusing to run script '{script}'.")
        self.audit.record("script", script=script, args=args, system=system, dry_run=self.config.dry_run)
        return self.config.dry_run
