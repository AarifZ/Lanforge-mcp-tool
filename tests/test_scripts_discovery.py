"""Script discovery: argparse -> JSON schema extraction and registry scanning."""

from __future__ import annotations

import pytest

from lanforge_mcp.errors import ScriptError
from lanforge_mcp.models import ScriptsConfig
from lanforge_mcp.scripts.discovery import (
    ScriptRegistry,
    extract_argparse_schema,
    extract_summary,
)

SAMPLE = '''
"""
NAME: sample_test.py

PURPOSE: Run a sample test against an AP.
"""
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mgr", default="localhost", help="LANforge manager")
    parser.add_argument("--num_stations", type=int, default=2, help="how many stations")
    parser.add_argument("--security", choices=["open", "wpa2", "wpa3"], default="wpa2")
    parser.add_argument("--enable_thing", action="store_true", help="turn the thing on")
    parser.add_argument("--ssid", required=True, help="the SSID")
    parser.add_argument("-d", "--debug", action="store_true")
'''


def test_schema_extraction():
    schema = extract_argparse_schema(SAMPLE)
    props = schema["properties"]
    assert props["num_stations"]["type"] == "integer"
    assert props["num_stations"]["default"] == 2
    assert props["security"]["choices"] == ["open", "wpa2", "wpa3"]
    assert props["enable_thing"]["is_flag"] is True
    assert schema["required"] == ["ssid"]
    assert props["debug"]["flag"] == "--debug"


def test_summary_extraction():
    assert extract_summary(SAMPLE) == "Run a sample test against an AP."


def test_syntax_error_raises():
    with pytest.raises(ScriptError):
        extract_argparse_schema("def broken(:\n")


async def test_local_discovery(tmp_path):
    (tmp_path / "my_test.py").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    registry = ScriptRegistry(ScriptsConfig(local_path=str(tmp_path)))
    scripts = await registry.discover()
    assert [s.name for s in scripts] == ["my_test"]

    info = await registry.load_schema("my_test")
    assert info.schema is not None
    assert "ssid" in info.schema["properties"]
    assert info.summary.startswith("Run a sample test")


async def test_unknown_script_raises(tmp_path):
    registry = ScriptRegistry(ScriptsConfig(local_path=str(tmp_path)))
    with pytest.raises(ScriptError):
        await registry.get("does_not_exist")


async def test_build_argv(tmp_path, app_config):
    from lanforge_mcp.safety import SafetyGuard
    from lanforge_mcp.scripts.runner import ScriptRunner

    (tmp_path / "my_test.py").write_text(SAMPLE, encoding="utf-8")
    registry = ScriptRegistry(ScriptsConfig(local_path=str(tmp_path)))
    runner = ScriptRunner(
        registry=registry,
        config=ScriptsConfig(local_path=str(tmp_path)),
        safety=SafetyGuard(app_config.safety),
        mgr_host="192.168.1.50",
    )
    _info, argv = await runner.build_argv(
        "my_test", {"ssid": "lab", "num_stations": 5, "enable_thing": True, "debug": False}
    )
    assert "--ssid" in argv and "lab" in argv
    assert "--num_stations" in argv and "5" in argv
    assert "--enable_thing" in argv
    assert "--debug" not in argv
    # --mgr auto-injected
    assert "--mgr" in argv and "192.168.1.50" in argv
