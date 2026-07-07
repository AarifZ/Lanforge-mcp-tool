"""Offline catalogs and destructive-command classification."""

from __future__ import annotations

from lanforge_mcp.api.catalog import get_catalog
from lanforge_mcp.safety import is_destructive_command, is_destructive_shell


def test_catalog_has_core_commands():
    cat = get_catalog()
    for cmd in ("add_sta", "add_endp", "add_cx", "set_port", "rm_cx", "add_l4_endp", "add_vap"):
        assert cat.has_command(cmd), cmd


def test_catalog_has_core_endpoints():
    cat = get_catalog()
    names = set(cat.endpoint_names)
    assert {"port", "stations", "cx", "endp", "events", "alerts"} <= names


def test_command_schema_includes_parameters():
    schema = get_catalog().command_schema("add_sta")
    assert schema is not None
    assert "ssid" in schema["properties"]
    assert "radio" in schema["properties"]
    assert schema["endpoint"] == "/cli-json/add_sta"


def test_search_commands():
    hits = get_catalog().search_commands("wanlink")
    assert any("wanlink" in h["command"] for h in hits)


def test_destructive_detection():
    assert is_destructive_command("rm_cx")
    assert is_destructive_command("reset_port")
    assert is_destructive_command("reboot")
    assert not is_destructive_command("add_sta")
    assert not is_destructive_command("set_port")
    assert is_destructive_shell("sudo rm -rf /home/lanforge/foo")
    assert not is_destructive_shell("iw dev")
