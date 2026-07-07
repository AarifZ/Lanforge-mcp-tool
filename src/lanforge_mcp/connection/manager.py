"""Registry of LANforge systems and their pooled HTTP/SSH clients."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from ..errors import SystemNotFoundError
from ..models import SystemConfig
from .http_client import LFHttpClient
from .ssh_client import LFSshClient

logger = logging.getLogger(__name__)


@dataclass
class ManagedSystem:
    config: SystemConfig
    http: LFHttpClient
    ssh: LFSshClient = field(init=False)

    def __post_init__(self) -> None:
        self.ssh = LFSshClient(self.config)


class ConnectionManager:
    """Holds every configured LANforge system; resolves the default one."""

    def __init__(self, transport_factory=None):
        # transport_factory lets tests inject an httpx.ASGITransport per system.
        self._systems: dict[str, ManagedSystem] = {}
        self._transport_factory = transport_factory

    def register(self, config: SystemConfig, replace: bool = True) -> ManagedSystem:
        if config.id in self._systems:
            if not replace:
                return self._systems[config.id]
            # Replacing: old clients are closed lazily by close_all / GC.
            logger.info("replacing system %s", config.id)
        transport: httpx.AsyncBaseTransport | None = None
        if self._transport_factory is not None:
            transport = self._transport_factory(config)
        managed = ManagedSystem(config=config, http=LFHttpClient(config, transport=transport))
        self._systems[config.id] = managed
        return managed

    def get(self, system_id: str | None = None) -> ManagedSystem:
        if system_id:
            if system_id not in self._systems:
                raise SystemNotFoundError(
                    f"No LANforge system registered with id '{system_id}'.",
                    details={"known_systems": list(self._systems)},
                )
            return self._systems[system_id]
        if len(self._systems) == 1:
            return next(iter(self._systems.values()))
        if not self._systems:
            raise SystemNotFoundError(
                "No LANforge system is configured. Use the 'connect' tool "
                "(host, optional port/credentials) or add one to config.yaml."
            )
        raise SystemNotFoundError(
            "Multiple systems are configured; specify system_id.",
            details={"known_systems": list(self._systems)},
        )

    def remove(self, system_id: str) -> bool:
        return self._systems.pop(system_id, None) is not None

    def list(self) -> list[SystemConfig]:
        return [m.config for m in self._systems.values()]

    async def check(self, system_id: str | None = None) -> dict:
        """Probe GUI reachability and report session state."""
        managed = self.get(system_id)
        await managed.http.ensure_session()
        # A cheap endpoint that exists on every LANforge GUI.
        data = await managed.http.get_json("/")
        info = {}
        if isinstance(data, dict):
            info = {
                k: data.get(k)
                for k in ("VersionInfo", "candela", "build_date", "build_version")
                if k in data
            }
        return {
            "system": managed.config.id,
            "url": managed.config.base_url,
            "reachable": True,
            "session": bool(managed.http.session_id),
            "gui_info": info,
        }

    async def close_all(self) -> None:
        for managed in self._systems.values():
            await managed.http.close()
            await managed.ssh.close()
        self._systems.clear()
