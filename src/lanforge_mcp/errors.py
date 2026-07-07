"""Exception hierarchy for lanforge-mcp.

Every error carries enough structure to be returned to an LLM as JSON: a stable
``type``, a human-readable ``message``, optional ``details`` and a ``hint`` that
tells the model what to try next. Tools never let raw tracebacks escape.
"""

from __future__ import annotations

from typing import Any


class LANforgeMCPError(Exception):
    """Base class for every error raised by lanforge-mcp."""

    error_type = "internal_error"
    default_hint = ""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        self.hint = hint or self.default_hint

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.error_type, "message": self.message}
        if self.details:
            out["details"] = self.details
        if self.hint:
            out["hint"] = self.hint
        return out


class ConfigError(LANforgeMCPError):
    error_type = "config_error"
    default_hint = "Check config.yaml / LANFORGE_MCP_* environment variables."


class SystemNotFoundError(LANforgeMCPError):
    error_type = "system_not_found"
    default_hint = "Use the 'connect' tool to register a system, or 'systems' to list configured ones."


class LFConnectionError(LANforgeMCPError):
    error_type = "connection_error"
    default_hint = (
        "Verify the LANforge GUI is running and reachable (default port 8080), "
        "the host/port are correct, and no firewall is blocking the connection."
    )


class SshError(LANforgeMCPError):
    error_type = "ssh_error"
    default_hint = "Verify SSH credentials (default lanforge/lanforge) and that sshd is running on the LANforge system."


class QueryError(LANforgeMCPError):
    error_type = "query_error"
    default_hint = "Use 'list_endpoints' to see valid endpoints and their columns."


class CommandError(LANforgeMCPError):
    error_type = "command_error"
    default_hint = "Use 'command_help' for the command's parameters, or 'list_commands' to search for the right command."


class ScriptError(LANforgeMCPError):
    error_type = "script_error"
    default_hint = "Use 'list_scripts' and 'script_schema' to check the script name and its arguments."


class WorkflowError(LANforgeMCPError):
    error_type = "workflow_error"
    default_hint = "Inspect the per-step results to find the failing step; steps support on_error: continue|retry."


class SafetyError(LANforgeMCPError):
    error_type = "safety_blocked"
    default_hint = (
        "The operation was blocked by a safety policy. Destructive operations need confirm=true; "
        "read-only mode blocks all mutations."
    )


class TimeoutError_(LANforgeMCPError):
    error_type = "timeout"
    default_hint = "Increase the timeout parameter, or check whether the LANforge system is overloaded."


def translate_lanforge_message(text: str) -> str:
    """Turn common terse LANforge GUI error strings into actionable messages."""
    t = text.strip()
    low = t.lower()
    if "not found" in low and "shelf" in low:
        return f"{t} — the EID (shelf.resource.port) does not exist; query the 'port' endpoint to list valid EIDs."
    if "phantom" in low:
        return f"{t} — the port exists in config but has no live hardware backing it."
    if "no radio" in low or ("wiphy" in low and "unknown" in low):
        return f"{t} — the radio name is wrong; query the 'radiostatus' endpoint for valid radios."
    if "unknown command" in low:
        return f"{t} — the CLI command is not recognized by this LANforge version; check 'list_commands'."
    return t
