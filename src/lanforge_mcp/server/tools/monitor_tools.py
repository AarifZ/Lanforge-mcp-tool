"""Monitoring group: events, alerts, periodic sampling of any table."""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timezone
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"monitoring"})
    @tool_errors
    async def events(
        last: Annotated[int, Field(description="How many recent events to return", ge=1, le=1000)] = 50,
        keyword: Annotated[str, Field(description="Only events whose text contains this (e.g. 'disconnect', 'dhcp', 'radar')")] = "",
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Read the LANforge event log (association, DHCP, link changes, errors).

        The event log is the primary source for answering 'why did X happen?'.
        See analyze_events for automatic pattern grouping.
        """
        q = await ctx.api(system_id).query("events")
        rows = q["rows"]
        if keyword:
            needle = keyword.lower()
            rows = [r for r in rows if needle in " ".join(str(v) for v in r.values()).lower()]
        return {"ok": True, "total": q["row_count"], "events": rows[-last:]}

    @mcp.tool(tags={"monitoring"})
    @tool_errors
    async def alerts(
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """List active LANforge alerts (persistent warning conditions)."""
        q = await ctx.api(system_id).query("alerts")
        return {"ok": True, "count": q["row_count"], "alerts": q["rows"][:100]}

    @mcp.tool(tags={"monitoring"})
    @tool_errors
    async def monitor(
        endpoint: Annotated[str, Field(description="Table to sample: 'cx' (L3 traffic), 'port' (stations/interfaces), 'layer4', 'voip', ...")],
        duration_sec: Annotated[float, Field(description="Total sampling time", gt=0, le=3600)] = 30.0,
        interval_sec: Annotated[float, Field(description="Seconds between samples", ge=1)] = 5.0,
        columns: Annotated[list[str] | None, Field(description="Restrict to these columns (keeps output small)")] = None,
        eids: Annotated[list[str] | None, Field(description="Restrict to these entities")] = None,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
        fastmcp_ctx: Context | None = None,
    ) -> dict:
        """Sample any LANforge table repeatedly and return the time series plus
        computed statistics (min/avg/max per entity per metric).

        This is how the AI watches a running test: monitor('cx', 60) during a
        traffic run yields throughput-over-time with an AI-ready summary.
        The result can be fed straight into generate_report.
        """
        from ...reports.engine import summarize_samples

        api = ctx.api(system_id)
        samples = []
        deadline = time.monotonic() + duration_sec
        total = max(1, int(duration_sec / interval_sec))
        i = 0
        while True:
            t0 = time.monotonic()
            q = await api.query(endpoint, columns=columns, eids=eids)
            samples.append({"t": datetime.now(timezone.utc).isoformat(), "rows": q["rows"]})
            i += 1
            if fastmcp_ctx is not None:
                # Progress reporting is best-effort; never fail the sample loop.
                with contextlib.suppress(Exception):
                    await fastmcp_ctx.report_progress(min(i, total), total)
            if t0 + interval_sec >= deadline:
                break
            await asyncio.sleep(interval_sec)
        stats = summarize_samples(samples)
        return {
            "ok": True,
            "endpoint": endpoint,
            "sample_count": len(samples),
            "interval_sec": interval_sec,
            "stats": stats,
            "samples": samples if len(samples) * len(samples[0].get("rows", [])) <= 400 else samples[-3:],
            "note": "stats cover ALL samples; raw samples may be truncated for size",
        }
