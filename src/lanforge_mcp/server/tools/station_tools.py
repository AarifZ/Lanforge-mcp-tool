"""Station group: create/manage virtual WiFi stations and ports."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...errors import CommandError
from ..context import AppContext, tool_errors

#: add_sta security flags (values from py-json/LANforge/add_sta.py).
SECURITY_FLAGS = {
    "open": 0x0,
    "wep": 0x200,
    "wpa": 0x10,
    "wpa2": 0x400,
    "wpa3": 0x10000000000,
}
FLAG_CREATE_ADMIN_DOWN = 0x1000000000

#: set_port flag values (from py-json/LANforge/set_port.py).
SP_USE_DHCP = 0x80000000
SP_IF_DOWN = 0x1
SP_INTEREST_CURRENT_FLAGS = 0x2
SP_INTEREST_DHCP = 0x4000
SP_INTEREST_IFDOWN = 0x800000


def _eid_parts(eid: str) -> tuple[int, int, str]:
    """Split '1.1.sta0000' / '1.sta0000' / 'sta0000' into shelf, resource, port."""
    parts = eid.split(".")
    if len(parts) == 3:
        return int(parts[0]), int(parts[1]), parts[2]
    if len(parts) == 2:
        return 1, int(parts[0]), parts[1]
    return 1, 1, parts[0]


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"stations"})
    @tool_errors
    async def create_stations(
        radio: Annotated[str, Field(description="Parent radio, e.g. 'wiphy0' or '1.1.wiphy0'")],
        ssid: Annotated[str, Field(description="SSID to associate with")],
        num_stations: Annotated[int, Field(description="How many stations to create", ge=1, le=1000)] = 1,
        security: Annotated[Literal["open", "wep", "wpa", "wpa2", "wpa3"], Field(description="Authentication type")] = "wpa2",
        passwd: Annotated[str, Field(description="Passphrase (ignored for open networks)")] = "",
        prefix: Annotated[str, Field(description="Station name prefix; names become e.g. sta0000, sta0001")] = "sta",
        start_id: Annotated[int, Field(description="First station number")] = 0,
        mode: Annotated[int, Field(description="WiFi mode number (0=AUTO; see add_sta docs)")] = 0,
        admin_down: Annotated[bool, Field(description="Create stations without bringing them up")] = False,
        wait_for_ip_sec: Annotated[float, Field(description="Wait up to this long for every station to get a DHCP address (0 = don't wait)")] = 60.0,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Create one or more virtual WiFi stations on a radio and (optionally) wait
        for them to associate and get DHCP addresses.

        Combines add_sta + set_port(DHCP, up) for each station. Use
        station_status afterwards for signal/IP details, and remove_ports to
        clean up.
        """
        if security != "open" and not passwd:
            raise CommandError(f"security='{security}' requires a passphrase (passwd).")
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        shelf, resource, radio_name = _eid_parts(radio)

        flags = SECURITY_FLAGS[security]
        if admin_down:
            flags |= FLAG_CREATE_ADMIN_DOWN
        names = [f"{prefix}{i:04d}" for i in range(start_id, start_id + num_stations)]

        created, errors = [], []
        for name in names:
            res = await api.command(
                "add_sta",
                {
                    "shelf": shelf,
                    "resource": resource,
                    "radio": radio_name,
                    "sta_name": name,
                    "ssid": ssid,
                    "key": passwd if security != "open" else "[BLANK]",
                    "mode": mode,
                    "mac": "xx:xx:xx:xx:*:xx",
                    "flags": flags,
                    "flags_mask": flags or 0xFFFFFFFF,
                },
                system_id=sid,
            )
            if not res.ok:
                errors.append({"station": name, "errors": res.errors})
                continue
            current = SP_USE_DHCP | (SP_IF_DOWN if admin_down else 0)
            up_res = await api.command(
                "set_port",
                {
                    "shelf": shelf,
                    "resource": resource,
                    "port": name,
                    "current_flags": current,
                    "interest": SP_INTEREST_CURRENT_FLAGS | SP_INTEREST_DHCP | SP_INTEREST_IFDOWN,
                },
                system_id=sid,
            )
            created.append(name)
            if not up_res.ok:
                errors.append({"station": name, "errors": up_res.errors, "stage": "set_port"})

        result: dict = {
            "ok": not errors,
            "created": created,
            "eids": [f"{shelf}.{resource}.{n}" for n in created],
            "errors": errors,
        }
        if wait_for_ip_sec > 0 and created and not admin_down and not ctx.safety.config.dry_run:
            result["association"] = await _wait_for_ip(api, shelf, resource, created, wait_for_ip_sec)
        return result

    async def _wait_for_ip(api, shelf: int, resource: int, names: list[str], timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        pending = set(names)
        got_ip: dict[str, str] = {}
        while pending and time.monotonic() < deadline:
            q = await api.query("port", eids=[str(shelf), str(resource), ",".join(pending)])
            for row in q["rows"]:
                alias = str(row.get("alias") or "")
                ip = str(row.get("ip") or "0.0.0.0")
                if alias in pending and ip not in ("0.0.0.0", ""):
                    got_ip[alias] = ip
                    pending.discard(alias)
            if pending:
                await asyncio.sleep(3)
        return {
            "associated": got_ip,
            "no_ip_yet": sorted(pending),
            "all_up": not pending,
        }

    @mcp.tool(tags={"stations"})
    @tool_errors
    async def station_status(
        eids: Annotated[list[str] | None, Field(description="Specific stations, e.g. ['1.1.sta0000']; omit for all WiFi stations")] = None,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Show WiFi station state: IP, associated AP/BSSID, signal, channel, mode.

        Use this to answer 'are my stations connected?' and 'why did stations
        disconnect?' (see also diagnose_stations for reasons per failure).
        """
        diag = await ctx.diagnostics(system_id).diagnose_stations(eids)
        return {"ok": True, **diag}

    @mcp.tool(tags={"stations", "ports"})
    @tool_errors
    async def set_port_state(
        eids: Annotated[list[str], Field(description="Port EIDs, e.g. ['1.1.sta0000', '1.1.eth1']")],
        state: Annotated[Literal["up", "down"], Field(description="Desired admin state")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Bring ports (stations, ethernets, vAPs) admin up or down."""
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        results = []
        for eid in eids:
            shelf, resource, port = _eid_parts(eid)
            res = await api.command(
                "set_port",
                {
                    "shelf": shelf,
                    "resource": resource,
                    "port": port,
                    "current_flags": SP_IF_DOWN if state == "down" else 0,
                    "interest": SP_INTEREST_CURRENT_FLAGS | SP_INTEREST_IFDOWN,
                },
                system_id=sid,
            )
            results.append({"eid": eid, "ok": res.ok, "errors": res.errors})
        return {"ok": all(r["ok"] for r in results), "results": results}

    @mcp.tool(tags={"stations", "ports"})
    @tool_errors
    async def remove_ports(
        eids: Annotated[list[str], Field(description="Virtual port EIDs to delete, e.g. ['1.1.sta0000']")],
        confirm: Annotated[bool, Field(description="Must be true — deleting ports is destructive")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Delete virtual ports (stations, vAPs, MAC-VLANs, 802.1q VLANs, bridges).

        Physical ports cannot be deleted. Requires confirm=true.
        """
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        results = []
        for eid in eids:
            shelf, resource, port = _eid_parts(eid)
            res = await api.command(
                "rm_vlan",
                {"shelf": shelf, "resource": resource, "port": port},
                confirm=confirm,
                system_id=sid,
            )
            results.append({"eid": eid, "ok": res.ok, "errors": res.errors})
        return {"ok": all(r["ok"] for r in results), "results": results}
