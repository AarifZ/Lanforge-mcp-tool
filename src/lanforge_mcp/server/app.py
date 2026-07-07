"""FastMCP server assembly."""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from .. import __version__
from ..api.catalog import get_catalog
from ..connection.manager import ConnectionManager
from ..models import AppConfig
from ..reports.engine import ReportEngine
from ..safety import SafetyGuard
from .context import AppContext
from .tools import register_all

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
lanforge-mcp exposes Candela LANforge traffic generators to AI models.

Getting started:
1. connect(host=...) — register a LANforge system (defaults: port 8080, lanforge/lanforge).
2. inventory() — see radios, ports, stations and existing traffic.
3. High-level tools: create_stations, create_l3_traffic, start_traffic, monitor,
   generate_report, diagnose_stations, run_workflow_template.
4. EVERYTHING else in LANforge is reachable through the dynamic gateway tools:
   list_commands/command_help + run_command (600+ CLI commands),
   list_endpoints + query (all JSON tables),
   list_scripts/script_schema + run_script (115+ automation scripts),
   shell_command (LANforge OS shell over SSH).

Safety: destructive operations (rm_*, reset_*, reboot...) need confirm=true.
set_safety_mode can enable read_only or dry_run. All mutations are audit-logged.
"""


def create_server(config: AppConfig, transport_factory=None) -> tuple[FastMCP, AppContext]:
    """Build the FastMCP app with every tool group registered.

    ``transport_factory`` lets tests inject in-process ASGI transports for the
    HTTP clients (mock LANforge).
    """
    manager = ConnectionManager(transport_factory=transport_factory)
    for system in config.systems:
        manager.register(system)
        logger.info("registered LANforge system %s (%s)", system.id, system.base_url)

    ctx = AppContext(
        config=config,
        manager=manager,
        catalog=get_catalog(),
        safety=SafetyGuard(config.safety),
        reports=ReportEngine(config.reports),
    )

    mcp: FastMCP = FastMCP(
        name="lanforge-mcp",
        version=__version__,
        instructions=INSTRUCTIONS,
    )
    register_all(mcp, ctx)
    return mcp, ctx
