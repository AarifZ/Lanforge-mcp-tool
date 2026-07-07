"""Workflow engine: substitution, conditions, error policy, dry-run, templates."""

from __future__ import annotations

import pytest

from lanforge_mcp.errors import WorkflowError
from lanforge_mcp.models import Condition, WorkflowSpec
from lanforge_mcp.workflow.engine import check_condition, substitute
from lanforge_mcp.workflow.templates import get_template, list_templates


def test_substitute_string_and_nested():
    context = {"name": "udp-1", "stats": {"rows": [{"bps": 950}]}}
    assert substitute("cx is ${name}", context) == "cx is udp-1"
    assert substitute("${stats.rows[0].bps}", context) == 950  # type preserved
    assert substitute({"k": ["${name}"]}, context) == {"k": ["udp-1"]}


def test_substitute_missing_raises():
    with pytest.raises(WorkflowError):
        substitute("${nope}", {})


def test_check_condition_numeric_and_string():
    rows = [{"ip": "10.0.0.1", "bps": "1000"}, {"ip": "0.0.0.0", "bps": "0"}]
    assert check_condition(rows, Condition(field="ip", op="ne", value="0.0.0.0", match="any"))
    assert not check_condition(rows, Condition(field="ip", op="ne", value="0.0.0.0", match="all"))
    assert check_condition(rows, Condition(field="bps", op="ge", value=1000, match="any"))
    assert not check_condition([], Condition(field="x", op="eq", value=1))


def test_templates_validate():
    names = [t["template"] for t in list_templates()]
    assert "l3_throughput" in names and "sta_connect_smoke" in names
    for name in names:
        spec = get_template(name)
        assert isinstance(spec, WorkflowSpec)
        assert spec.steps


def test_template_variable_override():
    spec = get_template("l3_throughput", {"cx_name": "custom", "duration_sec": 5})
    assert spec.variables["cx_name"] == "custom"
    assert spec.variables["port_a"] == "eth1"  # default kept


async def test_full_l3_workflow_against_mock(ctx, state):
    spec = get_template(
        "l3_throughput",
        {"duration_sec": 0.2, "cx_name": "wf-test"},
    )
    # Speed up sampling for the test.
    for step in spec.steps:
        if step.action == "sample":
            step.interval_sec = 0.1
    engine = ctx.workflow_engine()
    result = await engine.run(spec)
    assert result.state == "finished", [s.error for s in result.steps if not s.ok]
    assert result.ok
    # cx was created, run, sampled, stopped and removed on the mock
    assert "wf-test" not in state.cxs
    report_step = next(s for s in result.steps if s.action == "report")
    assert report_step.result["files"]


async def test_workflow_abort_on_error(ctx):
    spec = WorkflowSpec.model_validate(
        {
            "name": "fail-fast",
            "steps": [
                {"action": "command", "command": "explode", "params": {}},
                {"action": "log", "message": "never reached"},
            ],
        }
    )
    result = await ctx.workflow_engine().run(spec)
    assert result.state == "failed"
    assert len(result.steps) == 1


async def test_workflow_continue_policy(ctx):
    spec = WorkflowSpec.model_validate(
        {
            "name": "keep-going",
            "steps": [
                {"action": "command", "command": "explode", "params": {}, "on_error": "continue"},
                {"action": "log", "message": "reached"},
            ],
        }
    )
    result = await ctx.workflow_engine().run(spec)
    assert result.state == "finished"
    assert result.steps[1].ok


async def test_workflow_dry_run_touches_nothing(ctx, state):
    before = len(state.commands_received)
    spec = get_template("l3_throughput")
    result = await ctx.workflow_engine().run(spec, dry_run=True)
    assert result.dry_run
    assert len(state.commands_received) == before


async def test_wait_for_satisfied(ctx):
    spec = WorkflowSpec.model_validate(
        {
            "name": "wait",
            "steps": [
                {
                    "action": "wait_for",
                    "endpoint": "port",
                    "until": {"field": "ip", "op": "ne", "value": "0.0.0.0", "match": "any"},
                    "timeout_sec": 5,
                    "interval_sec": 0.1,
                }
            ],
        }
    )
    result = await ctx.workflow_engine().run(spec)
    assert result.ok
