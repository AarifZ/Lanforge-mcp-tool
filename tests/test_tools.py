"""End-to-end MCP integration: call tools through a real FastMCP client session."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client


def result_json(result) -> dict:
    """Extract the structured payload from a CallToolResult."""
    if result.structured_content is not None:
        data = result.structured_content
        return data.get("result", data) if isinstance(data, dict) else data
    return json.loads(result.content[0].text)


@pytest.fixture()
def client(server):
    mcp, _ctx, _state = server
    return Client(mcp)


async def test_tool_catalog_is_complete(client):
    async with client:
        tools = {t.name for t in await client.list_tools()}
    expected = {
        "connect", "systems", "health_check", "inventory", "query", "list_endpoints",
        "list_commands", "command_help", "run_command", "raw_cli", "shell_command",
        "create_stations", "station_status", "remove_ports", "create_l3_traffic",
        "start_traffic", "stop_traffic", "traffic_stats", "monitor", "events",
        "list_scripts", "script_schema", "run_script", "run_workflow",
        "run_workflow_template", "generate_report", "diagnose_stations",
        "diagnose_traffic", "analyze_events", "set_safety_mode",
    }
    assert expected <= tools


async def test_inventory_tool(client):
    async with client:
        data = result_json(await client.call_tool("inventory", {}))
    assert data["ok"] is True
    assert data["port_count"] == 3
    assert any(r["eid"] == "1.1.wiphy0" for r in data["radios"])


async def test_create_stations_and_diagnose(client, state):
    async with client:
        data = result_json(
            await client.call_tool(
                "create_stations",
                {"radio": "1.1.wiphy0", "ssid": "lab", "passwd": "secret", "num_stations": 2,
                 "wait_for_ip_sec": 5},
            )
        )
        assert data["ok"], data
        assert data["created"] == ["sta0000", "sta0001"]
        assert data["association"]["all_up"] is True

        diag = result_json(await client.call_tool("diagnose_stations", {}))
        assert diag["stations_total"] == 2
        assert diag["failed"] == 0


async def test_l3_lifecycle(client, state):
    async with client:
        created = result_json(
            await client.call_tool(
                "create_l3_traffic",
                {"name": "udp-x", "port_a": "1.1.eth0", "port_b": "1.1.eth1", "start": True},
            )
        )
        assert created["ok"] and created["started"]
        assert state.cxs["udp-x"]["state"] == "RUN"

        stats = result_json(await client.call_tool("traffic_stats", {"cx_names": ["udp-x"]}))
        assert stats["row_count"] == 1

        stopped = result_json(await client.call_tool("stop_traffic", {"cx_names": ["udp-x"]}))
        assert stopped["ok"]

        removed = result_json(
            await client.call_tool("remove_traffic", {"cx_names": ["udp-x"], "confirm": True})
        )
        assert removed["ok"]
        assert "udp-x" not in state.cxs


async def test_destructive_without_confirm_returns_structured_error(client):
    async with client:
        data = result_json(
            await client.call_tool("run_command", {"command": "rm_cx", "params": {"cx_name": "x"}})
        )
    assert data["ok"] is False
    assert data["error"]["type"] == "safety_blocked"
    assert "confirm" in data["error"]["hint"]


async def test_query_unknown_endpoint_returns_hint(client):
    async with client:
        data = result_json(await client.call_tool("query", {"endpoint": "not_a_table"}))
    assert data["ok"] is False
    assert data["error"]["type"] == "query_error"


async def test_run_workflow_template_dry_run(client, state):
    async with client:
        before = len(state.commands_received)
        data = result_json(
            await client.call_tool(
                "run_workflow_template", {"template": "l3_throughput", "dry_run": True}
            )
        )
    assert data["dry_run"] is True
    assert len(state.commands_received) == before


async def test_monitor_and_report(client, tmp_path):
    async with client:
        mon = result_json(
            await client.call_tool(
                "monitor", {"endpoint": "port", "duration_sec": 1, "interval_sec": 1}
            )
        )
        assert mon["ok"] and mon["sample_count"] >= 1
        rep = result_json(
            await client.call_tool("generate_report", {"title": "Ports", "data": mon})
        )
        assert rep["ok"] and rep["files"]


async def test_events_and_analyze(client):
    async with client:
        ev = result_json(await client.call_tool("events", {"last": 10}))
        assert ev["ok"]
        an = result_json(await client.call_tool("analyze_events", {}))
        assert an["ok"] and "pattern_counts" in an
