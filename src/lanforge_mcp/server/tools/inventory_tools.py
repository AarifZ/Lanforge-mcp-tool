"""Inventory group: query any JSON endpoint, discover endpoints, summarize hardware."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"inventory", "discovery"})
    @tool_errors
    async def list_endpoints(
        search: Annotated[str, Field(description="Substring to match against endpoint names and column names; empty lists everything")] = "",
        limit: Annotated[int, Field(description="Maximum results", ge=1, le=100)] = 60,
    ) -> dict:
        """Discover the LANforge JSON GET endpoints usable with the 'query' tool.

        Endpoints are data tables: port (all interfaces incl. WiFi stations),
        cx (Layer-3 connections), endp, layer4, voip, events, alerts,
        radiostatus, resource, wifi_stats, attenuator, chamber, dut, ...
        Entries may carry a 'note' about version-specific quirks.
        """
        hits = ctx.catalog.search_endpoints(search, limit=limit)
        return {"ok": True, "endpoints": hits, "count": len(hits)}

    @mcp.tool(tags={"inventory"})
    @tool_errors
    async def query(
        endpoint: Annotated[str, Field(description="Endpoint name (e.g. 'port', 'cx', 'events') or full path (e.g. '/port/1/1/eth0')")],
        columns: Annotated[list[str] | None, Field(description="Column names to fetch (see list_endpoints); omit for defaults")] = None,
        eids: Annotated[list[str] | None, Field(description="Restrict to these entity IDs, e.g. ['1.1.sta0000','1.1.sta0001']")] = None,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Query ANY LANforge JSON API endpoint and get normalized rows back.

        This is the universal read tool: every table the LANforge GUI shows is
        readable here. Rows are normalized to a flat list of objects with an
        'eid' key.
        """
        result = await ctx.api(system_id).query(endpoint, columns=columns, eids=eids)
        rows = result["rows"]
        return {
            "ok": True,
            "endpoint": result["endpoint"],
            "row_count": result["row_count"],
            "rows": rows[:200],
            "truncated": len(rows) > 200,
        }

    @mcp.tool(tags={"inventory"})
    @tool_errors
    async def inventory(
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
        summary: Annotated[bool, Field(description="Return counts only (no per-item lists) — smaller output")] = False,
    ) -> dict:
        """Summarize the LANforge testbed: resources, radios, ports, stations, traffic.

        Ideal first call after connecting — it tells the AI what hardware is
        available to build tests with. summary=true returns just the counts.
        """
        api = ctx.api(system_id)
        resources = await api.query("resource")
        ports = await api.query("port", columns=["alias", "port type", "phantom", "down", "ip"])
        radios = await api.query("radiostatus")
        cxs = await api.query("cx")

        def _typ(row: dict) -> str:
            return str(row.get("port type") or row.get("port_type") or "").lower()

        stations = [p for p in ports["rows"] if _typ(p) in ("wifi-sta", "sta", "station")]
        out = {
            "ok": True,
            "resource_count": resources["row_count"],
            "radio_count": radios["row_count"],
            "port_count": ports["row_count"],
            "station_count": len(stations),
            "cx_count": cxs["row_count"],
        }
        if summary:
            return out
        return {
            **out,
            "resources": [
                {k: r.get(k) for k in ("eid", "hostname", "hw version", "phantom", "load") if k in r}
                for r in resources["rows"]
            ],
            "radios": [
                {k: r.get(k) for k in ("eid", "driver", "channel", "frequency", "country", "phantom") if k in r}
                for r in radios["rows"]
            ],
            "stations": [
                {"eid": s.get("eid"), "alias": s.get("alias"), "ip": s.get("ip")} for s in stations[:50]
            ],
            "cx_names": [c.get("name") or c.get("eid") for c in cxs["rows"][:50]],
        }
