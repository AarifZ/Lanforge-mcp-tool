"""MCP tool groups. Each module contributes one logical group via register()."""

from __future__ import annotations

from fastmcp import FastMCP

from ..context import AppContext
from . import (
    attenuator_tools,
    command_tools,
    connection_tools,
    diagnostic_tools,
    inventory_tools,
    monitor_tools,
    report_tools,
    script_tools,
    station_tools,
    traffic_tools,
    workflow_tools,
)

ALL_MODULES = (
    connection_tools,
    inventory_tools,
    command_tools,
    station_tools,
    traffic_tools,
    attenuator_tools,
    monitor_tools,
    script_tools,
    workflow_tools,
    report_tools,
    diagnostic_tools,
)


def register_all(mcp: FastMCP, ctx: AppContext) -> None:
    for module in ALL_MODULES:
        module.register(mcp, ctx)
