"""Reports group: turn collected data into Markdown/HTML/JSON reports."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"reports"})
    @tool_errors
    async def generate_report(
        title: Annotated[str, Field(description="Report title")],
        data: Annotated[Any, Field(description=(
            "Data to report on. Best: the output of 'monitor' or a workflow 'sample' step "
            "(dict with 'samples'). Also accepts a list of rows or any JSON blob."
        ))],
        formats: Annotated[list[Literal["markdown", "html", "json"]], Field(description="Output formats to write")] = ["markdown", "html", "json"],  # noqa: B006 — schema default
    ) -> dict:
        """Generate a report (Markdown + standalone HTML + JSON) with an AI summary.

        Time-series data gets per-entity min/avg/max statistics; the HTML file
        is print/PDF-ready. Returns the file paths and the AI summary lines.
        """
        result = ctx.reports.generate(title=title, data=data, formats=list(formats))
        return {"ok": True, **result}
