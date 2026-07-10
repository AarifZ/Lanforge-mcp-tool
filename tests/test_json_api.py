"""JSON API wrapper against the mock LANforge: query, command, safety, raw."""

from __future__ import annotations

import pytest

from lanforge_mcp.api.json_api import normalize_rows
from lanforge_mcp.errors import SafetyError


def test_normalize_list_of_keyed_rows():
    rows = normalize_rows({"interfaces": [{"1.1.eth0": {"alias": "eth0"}}, {"1.1.eth1": {"alias": "eth1"}}]})
    assert rows == [{"alias": "eth0", "eid": "1.1.eth0"}, {"alias": "eth1", "eid": "1.1.eth1"}]


def test_normalize_single_row():
    rows = normalize_rows({"interface": {"alias": "sta0000", "ip": "1.2.3.4"}, "uri": "port"})
    assert rows == [{"alias": "sta0000", "ip": "1.2.3.4"}]


def test_normalize_toplevel_keyed_rows():
    rows = normalize_rows({"handler": "x", "uri": "cx", "udp-1": {"name": "udp-1", "state": "RUN"}})
    assert rows == [{"name": "udp-1", "state": "RUN"}]


def test_normalize_dotted_section_becomes_eid():
    # /radiostatus style: the section key IS the entity id.
    rows = normalize_rows({"handler": "x", "1.1.wiphy0": {"driver": "ath10k", "channel": "36"}})
    assert rows == [{"driver": "ath10k", "channel": "36", "eid": "1.1.wiphy0"}]


async def test_query_ports(ctx):
    api = ctx.api()
    result = await api.query("port")
    assert result["row_count"] == 3
    aliases = {r["alias"] for r in result["rows"]}
    assert {"eth0", "eth1", "wiphy0"} <= aliases


async def test_query_with_eids(ctx):
    result = await ctx.api().query("port", eids=["1", "1", "eth0"])
    assert result["row_count"] == 1
    assert result["rows"][0]["alias"] == "eth0"


async def test_query_decodes_lanforge_encoded_columns(ctx, state):
    # The catalog documents columns pre-encoded ("port+type", "%28us%29"); the
    # wire must carry them decoded exactly once, however the caller wrote them.
    await ctx.api().query("port", columns=["alias", "port+type"])
    assert state.last_fields == "alias,port type"

    await ctx.api().query("port", columns=["port type"])
    assert state.last_fields == "port type"

    # %-encoded catalog forms decode too (mock rejects the unknown column, but
    # the request that reached the wire must already be decoded).
    with pytest.raises(Exception):  # noqa: B017 — only the wire format matters here
        await ctx.api().query("port", columns=["4way+time+%28us%29"])
    assert state.last_fields == "4way time (us)"


async def test_command_creates_station(ctx, state):
    res = await ctx.api().command(
        "add_sta",
        {"shelf": 1, "resource": 1, "radio": "wiphy0", "sta_name": "sta0000", "ssid": "x", "key": "y"},
    )
    assert res.ok
    assert "1.1.sta0000" in state.ports


async def test_unknown_command_forwarded_with_warning(ctx, state):
    res = await ctx.api().command("future_cmd_xyz", {"a": 1})
    assert res.ok  # mock accepts everything unknown
    assert any("not in the local catalog" in w for w in res.warnings)
    assert state.commands_received[-1]["cmd"] == "future_cmd_xyz"


async def test_command_error_translated(ctx):
    res = await ctx.api().command("set_cx_state", {"test_mgr": "default_tm", "cx_name": "nope", "cx_state": "RUNNING"})
    assert not res.ok
    assert res.errors


async def test_destructive_requires_confirm(ctx):
    with pytest.raises(SafetyError):
        await ctx.api().command("rm_cx", {"test_mgr": "default_tm", "cx_name": "x"})


async def test_destructive_with_confirm_passes(ctx, state):
    await ctx.api().command("add_cx", {"alias": "c1", "test_mgr": "default_tm", "tx_endp": "a", "rx_endp": "b"})
    res = await ctx.api().command("rm_cx", {"test_mgr": "default_tm", "cx_name": "c1"}, confirm=True)
    assert res.ok
    assert "c1" not in state.cxs


async def test_read_only_blocks_mutations(ctx):
    ctx.safety.set_modes(read_only=True)
    try:
        with pytest.raises(SafetyError):
            await ctx.api().command("add_sta", {"sta_name": "s"})
    finally:
        ctx.safety.set_modes(read_only=False)


async def test_dry_run_returns_plan(ctx, state):
    ctx.safety.set_modes(dry_run=True)
    try:
        before = len(state.commands_received)
        res = await ctx.api().command("add_sta", {"sta_name": "s", "radio": "wiphy0"})
        assert res.dry_run and res.ok
        assert len(state.commands_received) == before  # nothing sent
    finally:
        ctx.safety.set_modes(dry_run=False)


async def test_raw_command(ctx, state):
    res = await ctx.api().raw("set_cx_state all all STOPPED")
    assert res.ok
    assert state.commands_received[-1]["cmd"] == "raw"


async def test_bulk_port_omits_dynamic_fields_like_real_gui(ctx):
    # Live LANforge 5.5.2.1: bulk /port without ?fields= has no ip/ap/signal.
    result = await ctx.api().query("port")
    assert result["rows"] and all("ip" not in row for row in result["rows"])


async def test_unknown_field_rejected_like_real_gui(ctx):
    # Live GUIs reject unknown field names (observed with 'rssi').
    with pytest.raises(Exception, match=r"(?i)unknown field|400"):
        await ctx.api().query("port", columns=["alias", "rssi"])


async def test_stations_404_gets_actionable_hint(ctx):
    from lanforge_mcp.errors import QueryError

    with pytest.raises(QueryError) as exc_info:
        await ctx.api().query("stations")
    assert "port" in exc_info.value.hint
    assert "station_status" in exc_info.value.hint


async def test_help_text_stripped(ctx):
    text = await ctx.api().help_text("add_sta")
    assert "Mock help for add_sta" in text
    assert "<" not in text


async def test_audit_log_written(ctx, app_config):
    await ctx.api().command("add_sta", {"sta_name": "audit-test", "radio": "wiphy0"})
    from pathlib import Path

    content = Path(app_config.safety.audit_log_path).read_text(encoding="utf-8")
    assert "audit-test" in content
