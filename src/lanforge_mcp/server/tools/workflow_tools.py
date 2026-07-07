"""Workflow group: chain LANforge operations into one declarative run."""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field, ValidationError

from ...errors import WorkflowError
from ...models import WorkflowSpec
from ...workflow.templates import get_template, list_templates
from ..context import AppContext, tool_errors


def register(mcp: FastMCP, ctx: AppContext) -> None:
    @mcp.tool(tags={"workflow", "discovery"})
    @tool_errors
    async def list_workflow_templates() -> dict:
        """List built-in workflow templates (reusable test recipes) and their variables.

        Templates: sta_connect_smoke (station bring-up check), l3_throughput
        (create/run/sample/report/cleanup), l4_http_load, stop_all_traffic.
        Use workflow_template_spec to inspect steps, run_workflow_template to run.
        """
        return {"ok": True, "templates": list_templates()}

    @mcp.tool(tags={"workflow", "discovery"})
    @tool_errors
    async def workflow_template_spec(
        template: Annotated[str, Field(description="Template name from list_workflow_templates")],
    ) -> dict:
        """Show a template's full step list — copy and modify it for custom workflows."""
        spec = get_template(template)
        return {"ok": True, "spec": spec.model_dump(by_alias=True)}

    @mcp.tool(tags={"workflow"})
    @tool_errors
    async def run_workflow_template(
        template: Annotated[str, Field(description="Template name from list_workflow_templates")],
        variables: Annotated[dict[str, Any], Field(description="Override template variables, e.g. {'radio': 'wiphy1', 'ssid': 'MyAP'}")] = {},  # noqa: B006 — schema default
        dry_run: Annotated[bool, Field(description="Show what every step WOULD do without touching LANforge")] = False,
        background: Annotated[bool, Field(description="Return a workflow_id immediately; poll with workflow_status")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Run a built-in workflow template end-to-end (create → run → sample →
        report → cleanup as one operation)."""
        spec = get_template(template, variables)
        result = await ctx.workflow_engine(system_id).run(spec, dry_run=dry_run, background=background)
        return {"ok": result.ok or result.state == "running", **result.model_dump()}

    @mcp.tool(tags={"workflow"})
    @tool_errors
    async def run_workflow(
        steps: Annotated[list[dict[str, Any]], Field(description=(
            "Ordered steps. Each step has an 'action': "
            "command {command, params, confirm?} | raw {line} | query {endpoint, columns?, eids?} | "
            "shell {shell} | script {script, args} | wait {seconds} | "
            "wait_for {endpoint, eids?, until:{field,op,value,match}, timeout_sec, interval_sec} | "
            "sample {endpoint, interval_sec, duration_sec} | report {title, data} | log {message}. "
            "Common fields: name, register (save result as variable), on_error (abort|continue|retry), retries. "
            "Strings support ${variable} substitution, including ${registered.path[0].field}."
        ))],
        variables: Annotated[dict[str, Any], Field(description="Initial variables for ${...} substitution")] = {},  # noqa: B006 — schema default
        name: Annotated[str, Field(description="Workflow name (used in reports/logs)")] = "custom-workflow",
        dry_run: Annotated[bool, Field(description="Validate and show the plan without executing")] = False,
        background: Annotated[bool, Field(description="Return a workflow_id immediately; poll with workflow_status")] = False,
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Execute a custom workflow: any chain of commands, queries, waits,
        condition polls, stat sampling, scripts, shell steps and reports.

        Example — bring up traffic, watch it, report, tear down:
        steps=[
          {"action":"command","command":"set_cx_state","params":{"test_mgr":"default_tm","cx_name":"udp-1","cx_state":"RUNNING"}},
          {"action":"sample","endpoint":"cx","interval_sec":5,"duration_sec":60,"register":"stats"},
          {"action":"command","command":"set_cx_state","params":{"test_mgr":"default_tm","cx_name":"udp-1","cx_state":"STOPPED"}},
          {"action":"report","title":"UDP soak","data":"${stats}"}
        ]
        """
        try:
            spec = WorkflowSpec.model_validate({"name": name, "variables": variables, "steps": steps})
        except ValidationError as exc:
            raise WorkflowError(f"Invalid workflow: {exc}") from exc
        result = await ctx.workflow_engine(system_id).run(spec, dry_run=dry_run, background=background)
        return {"ok": result.ok or result.state == "running", **result.model_dump()}

    @mcp.tool(tags={"workflow"})
    @tool_errors
    async def workflow_status(
        workflow_id: Annotated[str, Field(description="workflow_id returned by run_workflow / run_workflow_template")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Progress and per-step results of a workflow run."""
        result = ctx.workflow_engine(system_id).status(workflow_id)
        return {"ok": True, **result.model_dump()}

    @mcp.tool(tags={"workflow"})
    @tool_errors
    async def cancel_workflow(
        workflow_id: Annotated[str, Field(description="workflow_id to cancel")],
        system_id: Annotated[str | None, Field(description="Which system (omit when only one is configured)")] = None,
    ) -> dict:
        """Cancel a running background workflow."""
        result = await ctx.workflow_engine(system_id).cancel(workflow_id)
        return {"ok": True, **result.model_dump()}
