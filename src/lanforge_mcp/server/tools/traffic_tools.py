"""Traffic group: Layer-3 and Layer-4 connections, start/stop, statistics."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from ..context import AppContext, tool_errors
from .station_tools import _eid_parts

#: Layer-3 endpoint types accepted by add_endp.
L3_TYPES = ("lf_udp", "lf_tcp", "lf_udp6", "lf_tcp6", "mc_udp", "mc_udp6")


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"traffic", "layer3"})
    @tool_errors
    async def create_l3_traffic(
        name: Annotated[str, Field(description="Connection name, e.g. 'udp-test'")],
        port_a: Annotated[str, Field(description="Side A port EID, e.g. '1.1.sta0000'")],
        port_b: Annotated[str, Field(description="Side B port EID, usually the upstream, e.g. '1.1.eth1'")],
        traffic_type: Annotated[Literal["lf_udp", "lf_tcp", "lf_udp6", "lf_tcp6", "mc_udp", "mc_udp6"], Field(description="Layer-3 protocol")] = "lf_udp",
        rate_a_bps: Annotated[int, Field(description="Transmit rate from side A in bits/sec")] = 1_000_000,
        rate_b_bps: Annotated[int, Field(description="Transmit rate from side B in bits/sec")] = 1_000_000,
        packet_size: Annotated[int, Field(description="Payload size in bytes (-1 = LANforge default)")] = -1,
        start: Annotated[bool, Field(description="Start the traffic immediately after creating it")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Create a bidirectional Layer-3 connection (UDP/TCP, v4/v6, unicast/multicast)
        between two ports. Creates endpoint A, endpoint B and the cross-connect.

        Monitor with traffic_stats; control with start_traffic / stop_traffic;
        clean up with remove_traffic.
        """
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        sides = []
        for suffix, eid, rate in (("A", port_a, rate_a_bps), ("B", port_b, rate_b_bps)):
            shelf, resource, port = _eid_parts(eid)
            params = {
                "alias": f"{name}-{suffix}",
                "shelf": shelf,
                "resource": resource,
                "port": port,
                "type": traffic_type,
                "ip_port": -1,
                "min_rate": rate,
                "max_rate": 0,
            }
            if packet_size > 0:
                params["min_pkt"] = packet_size
                params["max_pkt"] = 0
            res = await api.command("add_endp", params, system_id=sid)
            sides.append(res)
            if not res.ok:
                return {"ok": False, "stage": f"add_endp {suffix}", "errors": res.errors}
        cx = await api.command(
            "add_cx",
            {"alias": name, "test_mgr": "default_tm", "tx_endp": f"{name}-A", "rx_endp": f"{name}-B"},
            system_id=sid,
        )
        if not cx.ok:
            return {"ok": False, "stage": "add_cx", "errors": cx.errors}
        out = {"ok": True, "cx": name, "endpoints": [f"{name}-A", f"{name}-B"], "started": False}
        if start:
            run = await api.command(
                "set_cx_state",
                {"test_mgr": "default_tm", "cx_name": name, "cx_state": "RUNNING"},
                system_id=sid,
            )
            out["started"] = run.ok
        return out

    @mcp.tool(tags={"traffic", "layer4"})
    @tool_errors
    async def create_l4_traffic(
        name: Annotated[str, Field(description="Endpoint name, e.g. 'http-test'")],
        port: Annotated[str, Field(description="Port EID that generates the requests, e.g. '1.1.sta0000'")],
        url: Annotated[str, Field(description="Target URL, e.g. 'http://192.168.1.1/index.html' (http/https/ftp)")],
        urls_per_10min: Annotated[int, Field(description="Request rate: URLs per 10 minutes (600 = 1/sec)")] = 600,
        start: Annotated[bool, Field(description="Start immediately after creating")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Create a Layer-4 endpoint (HTTP/HTTPS/FTP GET load) on a port.

        Stats appear on the 'layer4' endpoint (use query('layer4') or
        traffic_stats). The cross-connect is named 'CX_<name>'.
        """
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        shelf, resource, port_name = _eid_parts(port)
        res = await api.command(
            "add_l4_endp",
            {
                "alias": name,
                "shelf": shelf,
                "resource": resource,
                "port": port_name,
                "type": "l4_generic",
                "timeout": 10000,
                "url_rate": urls_per_10min,
                "url": f"dl {url} /dev/null",
            },
            system_id=sid,
        )
        if not res.ok:
            return {"ok": False, "stage": "add_l4_endp", "errors": res.errors}
        cx = await api.command(
            "add_cx",
            {"alias": f"CX_{name}", "test_mgr": "default_tm", "tx_endp": name, "rx_endp": "NA"},
            system_id=sid,
        )
        out = {"ok": cx.ok, "cx": f"CX_{name}", "endpoint": name, "started": False}
        if start and cx.ok:
            run = await api.command(
                "set_cx_state",
                {"test_mgr": "default_tm", "cx_name": f"CX_{name}", "cx_state": "RUNNING"},
                system_id=sid,
            )
            out["started"] = run.ok
        return out

    async def _set_cx_state(state: str, cx_names: list[str], system_id: str | None) -> dict:
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        results = []
        for cx in cx_names:
            res = await api.command(
                "set_cx_state",
                {"test_mgr": "default_tm", "cx_name": cx, "cx_state": state},
                system_id=sid,
            )
            results.append({"cx": cx, "ok": res.ok, "errors": res.errors})
        return {"ok": all(r["ok"] for r in results), "state": state, "results": results}

    @mcp.tool(tags={"traffic"})
    @tool_errors
    async def start_traffic(
        cx_names: Annotated[list[str], Field(description="Cross-connect names; use ['all'] for every connection")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Start (RUN) the named Layer-3/Layer-4 cross-connects."""
        return await _set_cx_state("RUNNING", cx_names, system_id)

    @mcp.tool(tags={"traffic"})
    @tool_errors
    async def stop_traffic(
        cx_names: Annotated[list[str], Field(description="Cross-connect names; use ['all'] for every connection")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Stop the named cross-connects (traffic pauses; config is kept)."""
        return await _set_cx_state("STOPPED", cx_names, system_id)

    @mcp.tool(tags={"traffic"})
    @tool_errors
    async def remove_traffic(
        cx_names: Annotated[list[str], Field(description="Cross-connect names to delete")],
        confirm: Annotated[bool, Field(description="Must be true — deleting connections is destructive")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Delete cross-connects and their endpoints. Requires confirm=true."""
        api = ctx.api(system_id)
        sid = ctx.system(system_id).config.id
        results = []
        for cx in cx_names:
            res = await api.command(
                "rm_cx", {"test_mgr": "default_tm", "cx_name": cx}, confirm=confirm, system_id=sid
            )
            entry: dict[str, Any] = {"cx": cx, "rm_cx_ok": res.ok, "endpoints": []}
            for suffix in ("-A", "-B"):
                endp = await api.command(
                    "rm_endp", {"endp_name": f"{cx}{suffix}"}, confirm=confirm, system_id=sid
                )
                entry["endpoints"].append({"endp": f"{cx}{suffix}", "ok": endp.ok})
            results.append(entry)
        return {"ok": all(r["rm_cx_ok"] for r in results), "results": results}

    @mcp.tool(tags={"traffic", "monitoring"})
    @tool_errors
    async def traffic_stats(
        cx_names: Annotated[list[str] | None, Field(description="Limit to these connections; omit for all")] = None,
        layer: Annotated[Literal["l3", "l4", "voip"], Field(description="Which traffic table to read")] = "l3",
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Current throughput/latency/drop statistics for traffic connections.

        l3 reads the 'cx' table (bps, latency, drops per direction), l4 reads
        'layer4' (URLs/sec, bytes, timeouts), voip reads 'voip' (MOS, jitter).
        """
        endpoint = {"l3": "cx", "l4": "layer4", "voip": "voip"}[layer]
        q = await ctx.api(system_id).query(endpoint)
        rows = q["rows"]
        if cx_names:
            wanted = {c.lower() for c in cx_names}
            rows = [r for r in rows if str(r.get("name") or r.get("eid") or "").lower() in wanted]
        return {"ok": True, "layer": layer, "row_count": len(rows), "rows": rows[:100]}
