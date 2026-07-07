"""Shared fixtures: a mock LANforge wired into the full server stack."""

from __future__ import annotations

import httpx
import pytest

from lanforge_mcp.config import load_config
from lanforge_mcp.models import AppConfig
from lanforge_mcp.server.app import create_server
from lanforge_mcp.server.context import AppContext

from .mock_lanforge import MockState, create_mock_app


@pytest.fixture()
def mock_lf() -> tuple:
    """(ASGI app, MockState) pair emulating a LANforge GUI."""
    return create_mock_app()


@pytest.fixture()
def app_config(tmp_path) -> AppConfig:
    return load_config(
        overrides={
            "systems": [{"id": "default", "host": "mock-lf", "retries": 0}],
            "safety": {"audit_log_path": str(tmp_path / "audit.jsonl")},
            "reports": {"output_dir": str(tmp_path / "reports")},
        }
    )


@pytest.fixture()
def server(mock_lf, app_config) -> tuple:
    """(FastMCP app, AppContext, MockState) with HTTP routed to the mock."""
    app, state = mock_lf

    def transport_factory(_system):
        return httpx.ASGITransport(app=app)

    mcp, ctx = create_server(app_config, transport_factory=transport_factory)
    return mcp, ctx, state


@pytest.fixture()
def ctx(server) -> AppContext:
    return server[1]


@pytest.fixture()
def state(server) -> MockState:
    return server[2]
