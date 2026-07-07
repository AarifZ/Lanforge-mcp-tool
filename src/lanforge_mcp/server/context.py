"""Shared application context handed to every tool module.

Wires the layers together per LANforge system and caches the composed objects
(JsonApi, ShellExecutor, ScriptRunner, WorkflowEngine) so connection pools and
background-run registries persist across tool calls.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..api.catalog import Catalog
from ..api.json_api import JsonApi
from ..cliwrap.executor import ShellExecutor
from ..connection.manager import ConnectionManager, ManagedSystem
from ..diagnostics.analyzer import Diagnostics
from ..errors import LANforgeMCPError
from ..models import AppConfig
from ..reports.engine import ReportEngine
from ..safety import SafetyGuard
from ..scripts.discovery import ScriptRegistry
from ..scripts.runner import ScriptRunner
from ..workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)


@dataclass
class AppContext:
    config: AppConfig
    manager: ConnectionManager
    catalog: Catalog
    safety: SafetyGuard
    reports: ReportEngine
    _apis: dict[str, JsonApi] = field(default_factory=dict)
    _shells: dict[str, ShellExecutor] = field(default_factory=dict)
    _runners: dict[str, ScriptRunner] = field(default_factory=dict)
    _workflows: dict[str, WorkflowEngine] = field(default_factory=dict)
    _registries: dict[str, ScriptRegistry] = field(default_factory=dict)

    def system(self, system_id: str | None = None) -> ManagedSystem:
        return self.manager.get(system_id)

    def api(self, system_id: str | None = None) -> JsonApi:
        managed = self.system(system_id)
        sid = managed.config.id
        if sid not in self._apis:
            self._apis[sid] = JsonApi(managed.http, self.catalog, self.safety)
        return self._apis[sid]

    def shell(self, system_id: str | None = None) -> ShellExecutor:
        managed = self.system(system_id)
        sid = managed.config.id
        if sid not in self._shells:
            self._shells[sid] = ShellExecutor(managed.ssh, self.safety)
        return self._shells[sid]

    def script_registry(self, system_id: str | None = None) -> ScriptRegistry:
        managed = self.system(system_id)
        sid = managed.config.id
        if sid not in self._registries:
            self._registries[sid] = ScriptRegistry(self.config.scripts, ssh=managed.ssh)
        return self._registries[sid]

    def script_runner(self, system_id: str | None = None) -> ScriptRunner:
        managed = self.system(system_id)
        sid = managed.config.id
        if sid not in self._runners:
            self._runners[sid] = ScriptRunner(
                registry=self.script_registry(sid),
                config=self.config.scripts,
                safety=self.safety,
                ssh=managed.ssh,
                mgr_host=managed.config.host,
                system_id=sid,
            )
        return self._runners[sid]

    def workflow_engine(self, system_id: str | None = None) -> WorkflowEngine:
        managed = self.system(system_id)
        sid = managed.config.id
        if sid not in self._workflows:
            self._workflows[sid] = WorkflowEngine(
                api=self.api(sid),
                shell=self.shell(sid),
                scripts=self.script_runner(sid),
                reports=self.reports,
                system_id=sid,
            )
        return self._workflows[sid]

    def diagnostics(self, system_id: str | None = None) -> Diagnostics:
        return Diagnostics(self.api(system_id))

    def forget_system(self, system_id: str) -> None:
        for cache in (self._apis, self._shells, self._runners, self._workflows, self._registries):
            cache.pop(system_id, None)


def tool_errors(fn: Callable) -> Callable:
    """Convert LANforgeMCPError into a structured, LLM-friendly payload.

    Tools never raise raw tracebacks at the model; they return
    ``{"ok": false, "error": {type, message, hint, details}}`` so the model can
    self-correct (wrong endpoint name, missing confirmation, etc.).
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except LANforgeMCPError as exc:
            logger.info("tool %s returned error: %s", fn.__name__, exc.message)
            return {"ok": False, "error": exc.to_dict()}
        except Exception as exc:
            logger.exception("tool %s crashed", fn.__name__)
            return {
                "ok": False,
                "error": {
                    "type": "internal_error",
                    "message": f"{type(exc).__name__}: {exc}",
                    "hint": "This is a lanforge-mcp bug; the server itself is still healthy.",
                },
            }

    return wrapper
