"""Configuration loading: defaults < config.yaml < environment < CLI overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from .errors import ConfigError
from .models import AppConfig, SystemConfig

ENV_PREFIX = "LANFORGE_MCP_"

DEFAULT_CONFIG_LOCATIONS = (
    "lanforge-mcp.yaml",
    "config.yaml",
    "~/.config/lanforge-mcp/config.yaml",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Top level of {path} must be a mapping")
    return data


def _env_overrides() -> dict[str, Any]:
    """Read LANFORGE_MCP_* variables.

    Flat variables map to a single default system (HOST, PORT, USERNAME,
    PASSWORD, PROTOCOL, SSH_PORT) and to top-level flags (READ_ONLY, DRY_RUN,
    LOG_LEVEL, SCRIPTS_PATH, REPORTS_DIR, AUDIT_LOG).
    """
    env = {k[len(ENV_PREFIX):].lower(): v for k, v in os.environ.items() if k.startswith(ENV_PREFIX)}
    out: dict[str, Any] = {}
    system: dict[str, Any] = {}
    for key, target in (
        ("host", "host"),
        ("port", "port"),
        ("protocol", "protocol"),
        ("username", "username"),
        ("password", "password"),
        ("ssh_port", "ssh_port"),
        ("ssh_username", "ssh_username"),
        ("ssh_password", "ssh_password"),
        ("ssh_key_file", "ssh_key_file"),
    ):
        if key in env:
            system[target] = env[key]
    if system:
        system.setdefault("id", "default")
        out["systems"] = [system]

    def _bool(v: str) -> bool:
        return v.strip().lower() in ("1", "true", "yes", "on")

    safety: dict[str, Any] = {}
    if "read_only" in env:
        safety["read_only"] = _bool(env["read_only"])
    if "dry_run" in env:
        safety["dry_run"] = _bool(env["dry_run"])
    if "audit_log" in env:
        safety["audit_log_path"] = env["audit_log"]
    if safety:
        out["safety"] = safety

    if "scripts_path" in env:
        out["scripts"] = {"local_path": env["scripts_path"]}
    if "reports_dir" in env:
        out["reports"] = {"output_dir": env["reports_dir"]}
    if "log_level" in env:
        out["log_level"] = env["log_level"]
    return out


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: str | None = None, overrides: dict[str, Any] | None = None) -> AppConfig:
    """Assemble the effective AppConfig.

    Precedence (lowest to highest): built-in defaults, config.yaml,
    LANFORGE_MCP_* environment variables, explicit CLI ``overrides``.
    """
    data: dict[str, Any] = {}

    path: Path | None = None
    if config_path:
        path = Path(config_path).expanduser()
        if not path.is_file():
            raise ConfigError(f"Config file not found: {path}")
    else:
        for candidate in DEFAULT_CONFIG_LOCATIONS:
            p = Path(candidate).expanduser()
            if p.is_file():
                path = p
                break
    if path is not None:
        data = _load_yaml(path)

    data = _deep_merge(data, _env_overrides())
    if overrides:
        data = _deep_merge(data, overrides)

    try:
        return AppConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def make_system(host: str, **kwargs: Any) -> SystemConfig:
    """Convenience constructor used by the 'connect' tool."""
    try:
        return SystemConfig(host=host, **{k: v for k, v in kwargs.items() if v is not None})
    except ValidationError as exc:
        raise ConfigError(f"Invalid system parameters: {exc}") from exc
