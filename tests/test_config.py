"""Config loading: precedence, env vars, validation errors."""

from __future__ import annotations

import pytest

from lanforge_mcp.config import load_config
from lanforge_mcp.errors import ConfigError


def test_defaults_are_empty():
    cfg = load_config(config_path=None)
    assert cfg.systems == []
    assert cfg.safety.require_confirmation is True


def test_yaml_loading(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(
        "systems:\n  - id: lab\n    host: 10.0.0.5\n    port: 8081\nsafety:\n  read_only: true\n",
        encoding="utf-8",
    )
    cfg = load_config(str(path))
    assert cfg.systems[0].host == "10.0.0.5"
    assert cfg.systems[0].port == 8081
    assert cfg.safety.read_only is True


def test_env_overrides_yaml(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("log_level: DEBUG\n", encoding="utf-8")
    monkeypatch.setenv("LANFORGE_MCP_HOST", "192.168.9.9")
    monkeypatch.setenv("LANFORGE_MCP_READ_ONLY", "true")
    monkeypatch.setenv("LANFORGE_MCP_LOG_LEVEL", "WARNING")
    cfg = load_config(str(path))
    assert cfg.systems[0].host == "192.168.9.9"
    assert cfg.safety.read_only is True
    assert cfg.log_level == "WARNING"


def test_cli_overrides_win(monkeypatch):
    monkeypatch.setenv("LANFORGE_MCP_HOST", "1.1.1.1")
    cfg = load_config(overrides={"systems": [{"id": "default", "host": "2.2.2.2"}]})
    assert cfg.systems[0].host == "2.2.2.2"


def test_ssh_credentials_default_to_api_credentials():
    cfg = load_config(
        overrides={"systems": [{"id": "s", "host": "h", "username": "admin", "password": "pw"}]}
    )
    assert cfg.systems[0].ssh_username == "admin"
    assert cfg.systems[0].ssh_password == "pw"


def test_missing_config_file_errors():
    with pytest.raises(ConfigError):
        load_config("/nonexistent/nope.yaml")


def test_invalid_yaml_errors(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("systems: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(str(path))
