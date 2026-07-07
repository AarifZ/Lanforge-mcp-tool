"""Connection group: register/inspect LANforge systems, health, safety modes."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...config import make_system
from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"connection"})
    @tool_errors
    async def connect(
        host: Annotated[str, Field(description="LANforge hostname or IP address")],
        port: Annotated[int, Field(description="LANforge GUI JSON API port")] = 8080,
        protocol: Annotated[Literal["http", "https"], Field(description="API protocol")] = "http",
        username: Annotated[str, Field(description="Login for HTTPS API auth and SSH")] = "lanforge",
        password: Annotated[str, Field(description="Password for HTTPS API auth and SSH")] = "lanforge",
        ssh_port: Annotated[int, Field(description="SSH port on the LANforge OS")] = 22,
        system_id: Annotated[str, Field(description="Identifier for this system (use distinct ids to manage several LANforge boxes)")] = "default",
    ) -> dict:
        """Register a LANforge system and verify the GUI JSON API is reachable.

        With the default credentials (lanforge/lanforge) only the host is
        needed. Registering the same system_id again replaces the old entry.
        """
        config = make_system(
            host=host, port=port, protocol=protocol, username=username,
            password=password, ssh_port=ssh_port, id=system_id,
        )
        ctx.forget_system(system_id)
        ctx.manager.register(config)
        status = await ctx.manager.check(system_id)
        return {"ok": True, **status}

    @mcp.tool(tags={"connection"})
    @tool_errors
    async def disconnect(
        system_id: Annotated[str, Field(description="System to remove from the registry")],
    ) -> dict:
        """Unregister a LANforge system and drop its pooled connections."""
        ctx.forget_system(system_id)
        removed = ctx.manager.remove(system_id)
        return {"ok": removed, "removed": system_id if removed else None}

    @mcp.tool(tags={"connection"})
    @tool_errors
    async def systems() -> dict:
        """List every configured LANforge system and its reachability."""
        out = []
        for cfg in ctx.manager.list():
            entry = {"system_id": cfg.id, "url": cfg.base_url, "ssh_port": cfg.ssh_port}
            try:
                status = await ctx.manager.check(cfg.id)
                entry["reachable"] = True
                entry["gui_info"] = status.get("gui_info", {})
            except Exception as exc:
                entry["reachable"] = False
                entry["error"] = str(exc)[:200]
            out.append(entry)
        return {"ok": True, "systems": out, "count": len(out)}

    @mcp.tool(tags={"connection", "diagnostics"})
    @tool_errors
    async def health_check(
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Overall health: GUI reachable, resources up, phantom ports, alerts."""
        status = await ctx.manager.check(system_id)
        health = await ctx.diagnostics(system_id).health_check()
        return {"ok": health["ok"], "connection": status, **health}

    @mcp.tool(tags={"connection", "safety"})
    @tool_errors
    async def set_safety_mode(
        read_only: Annotated[bool | None, Field(description="Block all mutating operations")] = None,
        dry_run: Annotated[bool | None, Field(description="Mutating calls return the request they WOULD send instead of sending it")] = None,
    ) -> dict:
        """Toggle read-only and/or dry-run safety modes at runtime.

        Destructive commands (rm_*, reset_*, reboot, ...) additionally require
        confirm=true on the individual call regardless of these modes.
        """
        modes = ctx.safety.set_modes(read_only=read_only, dry_run=dry_run)
        return {"ok": True, **modes}
