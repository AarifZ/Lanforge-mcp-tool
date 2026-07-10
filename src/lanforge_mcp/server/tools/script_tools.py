"""Scripts group: dynamic discovery and execution of lanforge-scripts py-scripts."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"scripts", "discovery"})
    @tool_errors
    async def list_scripts(
        search: Annotated[str, Field(description="Substring to match against script names (e.g. 'wifi_capacity', 'roam', 'dataplane', 'mesh', 'ftp')")] = "",
        refresh: Annotated[bool, Field(description="Re-scan the scripts directory (picks up newly added scripts)")] = False,
        limit: Annotated[int, Field(description="Maximum results", ge=1, le=200)] = 40,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Discover the 115+ automation scripts from lanforge-scripts (py-scripts).

        These cover full test suites: lf_wifi_capacity_test, lf_dataplane_test,
        lf_roam_test, lf_mesh_test, lf_rvr_test (rate-vs-range), test_l3,
        lf_ftp, lf_webpage, throughput_qos, lf_tr398_test and many more.
        Scripts are discovered automatically — new scripts appear without any
        server change.
        """
        registry = ctx.script_registry(system_id)
        if refresh:
            await registry.discover(refresh=True)
        hits = await registry.search(search, limit=limit)
        return {"ok": True, "scripts": hits, "count": len(hits)}

    @mcp.tool(tags={"scripts", "discovery"})
    @tool_errors
    async def script_schema(
        script: Annotated[str, Field(description="Script name, e.g. 'lf_wifi_capacity_test' (with or without .py)")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Get a script's purpose and full argument schema (parsed from its argparse).

        Call this before run_script to learn the arguments. '--mgr' is injected
        automatically at run time, so you don't need to pass it.
        """
        info = await ctx.script_registry(system_id).load_schema(script)
        return {
            "ok": True,
            "script": info.name,
            "location": info.location,
            "summary": info.summary,
            "schema": info.schema,
        }

    @mcp.tool(tags={"scripts"})
    @tool_errors
    async def run_script(
        script: Annotated[str, Field(description="Script name from list_scripts")],
        args: Annotated[dict[str, Any], Field(description="Arguments keyed by schema property name (e.g. {'radio': 'wiphy0', 'ssid': 'test', 'num_stations': 5}); booleans toggle flags")] = {},  # noqa: B006 — schema default
        timeout_sec: Annotated[float, Field(description="Kill the script after this many seconds")] = 600.0,
        background: Annotated[bool, Field(description="Return immediately with a run_id; poll with script_status")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Run ANY lanforge-scripts py-script, locally or on the LANforge box.

        Long tests (wifi capacity, dataplane, TR-398) should use
        background=true, then script_status / script_output / cancel_script.
        """
        out = await ctx.script_runner(system_id).run(
            script, args, timeout=timeout_sec, background=background
        )
        return {"ok": True, **out}

    @mcp.tool(tags={"scripts"})
    @tool_errors
    async def script_status(
        run_id: Annotated[str, Field(description="run_id returned by run_script")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Check a background script run: state, exit code, output tail."""
        return {"ok": True, **ctx.script_runner(system_id).status(run_id)}

    @mcp.tool(tags={"scripts"})
    @tool_errors
    async def script_output(
        run_id: Annotated[str, Field(description="run_id returned by run_script")],
        max_chars: Annotated[int, Field(description="Maximum output characters to return (from the end)")] = 20000,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Fetch the (tail of the) captured output of a script run."""
        return {"ok": True, **ctx.script_runner(system_id).result(run_id, max_chars=max_chars)}

    @mcp.tool(tags={"scripts"})
    @tool_errors
    async def cancel_script(
        run_id: Annotated[str, Field(description="run_id returned by run_script")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Cancel a running background script."""
        return {"ok": True, **await ctx.script_runner(system_id).cancel(run_id)}

    @mcp.tool(tags={"scripts"})
    @tool_errors
    async def list_script_runs(
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """List all script runs of this session with their states."""
        return {"ok": True, "runs": ctx.script_runner(system_id).list_runs()}
