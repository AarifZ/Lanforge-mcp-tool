"""Attenuator group: list programmable attenuators and set attenuation.

LANforge attenuators (CT70x) appear as ``shelf.resource.serial`` entities with
up to 8 modules; values are stored in tenths of a dB (ddB) on the wire but
exposed here in plain dB.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...api.json_api import data_rows
from ...errors import CommandError
from ...reports.engine import _to_float
from ..context import AppContext, tool_errors


def _atten_parts(atten_id: str) -> tuple[int, int, str]:
    """Split '1.1.8036' / '8036' into shelf, resource, serial."""
    parts = str(atten_id).split(".")
    if len(parts) == 3:
        return int(parts[0]), int(parts[1]), parts[2]
    if len(parts) == 2:
        return 1, int(parts[0]), parts[1]
    return 1, 1, parts[0]


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"attenuator", "inventory"})
    @tool_errors
    async def attenuators(
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """List programmable RF attenuators with per-module attenuation in dB.

        state 'Phantom' means the attenuator is configured but not currently
        connected; only non-phantom units accept set_attenuation.
        """
        q = await ctx.api(system_id).query("attenuator")
        rows = []
        for r in data_rows(q["rows"]):
            modules = {}
            for i in range(1, 9):
                value = _to_float(r.get(f"module {i}"))
                if value is not None:
                    modules[f"module_{i}"] = value
            rows.append(
                {
                    "atten_id": r.get("entity id") or r.get("name") or r.get("eid"),
                    "state": r.get("state"),
                    "modules_db": modules,
                    "script": r.get("script"),
                }
            )
        return {"ok": True, "count": len(rows), "attenuators": rows}

    @mcp.tool(tags={"attenuator"})
    @tool_errors
    async def set_attenuation(
        atten_id: Annotated[str, Field(description="Attenuator entity id, e.g. '1.1.8036' (see attenuators tool)")],
        attenuation_db: Annotated[float, Field(description="Attenuation in dB (typically 0-95.5 in 0.5 dB steps)", ge=0, le=95.5)],
        module: Annotated[int, Field(description="Module number 1-8, or 0 to set ALL modules", ge=0, le=8)] = 0,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Set RF attenuation on an attenuator module (or all modules).

        The workhorse of rate-vs-range and roaming tests: step attenuation_db
        up to walk a station away from the AP. Values are dB; LANforge stores
        tenths internally. Verify results with the attenuators tool.
        """
        shelf, resource, serial = _atten_parts(atten_id)
        if not serial.isdigit():
            raise CommandError(
                f"'{atten_id}' does not look like an attenuator id; expected e.g. '1.1.8036'.",
                hint="Call the attenuators tool to list valid atten_id values.",
            )
        sid = ctx.system(system_id).config.id
        res = await ctx.api(system_id).command(
            "set_attenuator",
            {
                "shelf": shelf,
                "resource": resource,
                "serno": serial,
                "atten_idx": "all" if module == 0 else module - 1,
                "val": round(attenuation_db * 10),
            },
            system_id=sid,
        )
        return {
            "ok": res.ok,
            "atten_id": f"{shelf}.{resource}.{serial}",
            "module": "all" if module == 0 else module,
            "attenuation_db": attenuation_db,
            "dry_run": res.dry_run,
            "errors": res.errors,
        }
