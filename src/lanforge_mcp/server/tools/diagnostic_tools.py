"""Diagnostics group: reasoned analysis, not just raw data."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ...diagnostics.analyzer import Diagnostics
from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"diagnostics"})
    @tool_errors
    async def diagnose_stations(
        eids: Annotated[list[str] | None, Field(description="Specific stations; omit for all")] = None,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Answer 'which stations are failing and why?'.

        Classifies every WiFi station as healthy or failed with concrete
        reasons: phantom, admin down, not associated, no DHCP address, weak
        signal (< -75 dBm).
        """
        return {"ok": True, **await ctx.diagnostics(system_id).diagnose_stations(eids)}

    @mcp.tool(tags={"diagnostics"})
    @tool_errors
    async def diagnose_traffic(
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Answer 'why is my traffic not flowing?'.

        Flags cross-connects that are running with zero throughput (one or both
        directions) and connections with packet drops above 1%.
        """
        return {"ok": True, **await ctx.diagnostics(system_id).diagnose_traffic()}

    @mcp.tool(tags={"diagnostics"})
    @tool_errors
    async def analyze_events(
        last: Annotated[int, Field(description="How many recent events to analyze", ge=10, le=2000)] = 200,
        keyword: Annotated[str, Field(description="Pre-filter events by this text before grouping")] = "",
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Group the event log into patterns: disconnects, connects, roams, DHCP,
        DFS/radar hits, errors — with counts and recent examples per pattern.

        This is the tool for 'why did my stations disconnect?' and 'analyze
        roaming failures'.
        """
        return {"ok": True, **await ctx.diagnostics(system_id).analyze_events(last=last, keyword=keyword)}

    @mcp.tool(tags={"diagnostics"})
    @tool_errors
    async def compare_throughput(
        before: Annotated[dict[str, Any], Field(description="Earlier sample set: output of 'monitor' or a workflow 'sample' step (dict containing 'samples')")],
        after: Annotated[dict[str, Any], Field(description="Later sample set of the same shape")],
    ) -> dict:
        """Compare two monitoring sample sets (e.g. yesterday vs today) and rank
        the biggest per-entity metric changes in percent.

        Use monitor(...) twice (or load a saved report.json) to produce inputs.
        """
        return {"ok": True, **Diagnostics.compare_samples(before, after)}
