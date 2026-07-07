"""Command group: dynamic gateway to all 600+ LANforge CLI commands + SSH shell."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ...errors import CommandError
from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"cli", "discovery"})
    @tool_errors
    async def list_commands(
        search: Annotated[str, Field(description="Substring matched against command names, parameters and descriptions (e.g. 'wanlink', 'sta', 'attenuator')")] = "",
        limit: Annotated[int, Field(description="Maximum results")] = 50,
    ) -> dict:
        """Search the catalog of LANforge CLI commands executable via 'run_command'.

        LANforge has 600+ commands covering everything: stations (add_sta),
        virtual APs (add_vap), Layer-3 (add_endp/add_cx), Layer-4 HTTP/FTP
        (add_l4_endp), VoIP (add_voip_endp), WAN emulation (add_wl_endp),
        attenuators (set_attenuator), chambers (add_chamber), and more.
        """
        hits = ctx.catalog.search_commands(search, limit=limit)
        return {"ok": True, "commands": hits, "count": len(hits)}

    @mcp.tool(tags={"cli", "discovery"})
    @tool_errors
    async def command_help(
        command: Annotated[str, Field(description="CLI command name, e.g. 'add_sta'")],
        live: Annotated[bool, Field(description="Also fetch live documentation from the connected GUI (more authoritative)")] = False,
        system_id: Annotated[str | None, Field(description="Which system (needed only with live=true)")] = None,
    ) -> dict:
        """Get parameter documentation for one CLI command.

        Returns the offline schema (parameter names/types) and, with live=true,
        the connected GUI's own help text for the exact installed version.
        """
        schema = ctx.catalog.command_schema(command)
        out: dict[str, Any] = {"ok": True, "schema": schema}
        if schema is None:
            out["note"] = (
                f"'{command}' is not in the offline catalog; it may still exist on a newer "
                "LANforge — try live=true or run_command directly."
            )
        if live:
            out["live_help"] = await ctx.api(system_id).help_text(command)
        return out

    @mcp.tool(tags={"cli"})
    @tool_errors
    async def run_command(
        command: Annotated[str, Field(description="CLI command name, e.g. 'add_sta', 'set_port', 'add_endp'")],
        params: Annotated[dict[str, Any], Field(description="Command parameters as documented by command_help")],
        confirm: Annotated[bool, Field(description="Required true for destructive commands (rm_*, reset_*, reboot, ...)")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Execute ANY LANforge CLI command through the JSON API (POST /cli-json/<command>).

        This is the universal write tool — anything the LANforge CLI can do is
        available here. Unknown commands are forwarded to the GUI (which is the
        authority), so newer LANforge features work without a server upgrade.
        """
        sid = ctx.system(system_id).config.id
        result = await ctx.api(system_id).command(command, params, confirm=confirm, system_id=sid)
        return {"ok": result.ok, **result.model_dump(exclude={"ok"})}

    @mcp.tool(tags={"cli"})
    @tool_errors
    async def raw_cli(
        line: Annotated[str, Field(description="Complete one-line CLI command, e.g. 'reset_port 1 1 sta0000'")],
        confirm: Annotated[bool, Field(description="Required true when the first word is a destructive command")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Execute a raw one-line LANforge CLI command (POST /cli-json/raw).

        Useful for command lines copied from LANforge DB files or documentation
        cookbooks. Prefer run_command with named params when possible.
        """
        sid = ctx.system(system_id).config.id
        result = await ctx.api(system_id).raw(line, confirm=confirm, system_id=sid)
        return {"ok": result.ok, **result.model_dump(exclude={"ok"})}

    @mcp.tool(tags={"cli", "system"})
    @tool_errors
    async def shell_command(
        command: Annotated[str, Field(description="Shell command to run on the LANforge OS, e.g. 'iw dev', 'cat /var/log/messages | tail -50'")],
        timeout_sec: Annotated[float, Field(description="Kill the command after this many seconds")] = 60.0,
        confirm: Annotated[bool, Field(description="Required true for destructive-looking commands")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Run an arbitrary shell command on the LANforge system over SSH.

        Returns structured stdout/stderr/exit_code. Use for OS-level debugging
        (iw, ethtool, dmesg, log files) and the classic Perl scripts in
        /home/lanforge/scripts.
        """
        if not command.strip():
            raise CommandError("Empty shell command.")
        sid = ctx.system(system_id).config.id
        result = await ctx.shell(system_id).run(
            command, timeout=timeout_sec, confirm=confirm, system_id=sid
        )
        return {"ok": result.exit_code == 0, **result.model_dump()}
