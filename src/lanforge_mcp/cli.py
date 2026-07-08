"""Typer CLI: serve the MCP server, check connectivity, browse catalogs."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import load_config
from .errors import LANforgeMCPError
from .logging_setup import setup_logging

app = typer.Typer(
    name="lanforge-mcp",
    help="MCP server exposing the complete power of Candela LANforge to AI models.",
    no_args_is_help=True,
)
console = Console(stderr=True)


def _build_overrides(
    host: str | None, read_only: bool | None, dry_run: bool | None
) -> dict:
    overrides: dict = {}
    if host:
        overrides["systems"] = [{"id": "default", "host": host}]
    safety = {}
    if read_only is not None:
        safety["read_only"] = read_only
    if dry_run is not None:
        safety["dry_run"] = dry_run
    if safety:
        overrides["safety"] = safety
    return overrides


@app.command()
def serve(
    transport: Annotated[str, typer.Option(help="MCP transport: stdio | http")] = "stdio",
    host: Annotated[str | None, typer.Option(help="LANforge host (quick single-system setup without a config file)")] = None,
    config: Annotated[str | None, typer.Option("--config", "-c", help="Path to config.yaml")] = None,
    bind: Annotated[str, typer.Option(help="HTTP transport bind address")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="HTTP transport port")] = 8231,
    read_only: Annotated[bool | None, typer.Option("--read-only/--no-read-only", help="Block all mutations")] = None,
    dry_run: Annotated[
        bool | None,
        typer.Option("--dry-run/--no-dry-run", help="Mutations return the request instead of sending it"),
    ] = None,
) -> None:
    """Start the MCP server (stdio by default; http for remote deployments)."""
    from .server.app import create_server

    try:
        cfg = load_config(config, overrides=_build_overrides(host, read_only, dry_run))
    except LANforgeMCPError as exc:
        console.print(f"[red]config error:[/red] {exc.message}")
        raise typer.Exit(2) from exc
    setup_logging(cfg.log_level, cfg.log_file)
    mcp, _ctx = create_server(cfg)
    if transport == "http":
        mcp.run(transport="http", host=bind, port=port)
    else:
        mcp.run()


@app.command()
def check(
    host: Annotated[str | None, typer.Option(help="LANforge host to probe")] = None,
    config: Annotated[str | None, typer.Option("--config", "-c", help="Path to config.yaml")] = None,
) -> None:
    """Verify LANforge connectivity (GUI JSON API) for every configured system."""
    from .server.app import create_server

    cfg = load_config(config, overrides=_build_overrides(host, None, None))
    setup_logging(cfg.log_level)
    _mcp, ctx = create_server(cfg)

    async def _run() -> int:
        failures = 0
        systems = ctx.manager.list()
        if not systems:
            console.print("[yellow]no systems configured; pass --host or a config file[/yellow]")
            return 2
        for system in systems:
            # JSON API (the critical path for every tool)
            try:
                status = await ctx.manager.check(system.id)
                console.print(f"[green]OK[/green]   {system.id} json-api: {json.dumps(status)}")
            except LANforgeMCPError as exc:
                failures += 1
                console.print(f"[red]FAIL[/red] {system.id} json-api: {exc.message}")
                if exc.hint:
                    console.print(f"       hint: {exc.hint}")
            # SSH (needed only for shell_command and remote script runs)
            try:
                res = await ctx.manager.get(system.id).ssh.exec("echo lanforge-mcp-ok", timeout=8)
                if "lanforge-mcp-ok" in res.stdout:
                    console.print(f"[green]OK[/green]   {system.id} ssh: connected as {system.ssh_username}")
                else:
                    console.print(f"[yellow]WARN[/yellow] {system.id} ssh: unexpected reply (exit {res.exit_code})")
            except LANforgeMCPError as exc:
                console.print(
                    f"[yellow]WARN[/yellow] {system.id} ssh: {exc.message} "
                    "(shell_command and remote scripts won't work; JSON API tools are unaffected)"
                )
        await ctx.manager.close_all()
        return 1 if failures else 0

    raise typer.Exit(asyncio.run(_run()))


@app.command()
def catalog(
    search: Annotated[str, typer.Argument(help="Substring to search for")] = "",
    endpoints: Annotated[bool, typer.Option("--endpoints", help="Search GET endpoints instead of CLI commands")] = False,
) -> None:
    """Browse the offline command/endpoint catalogs."""
    from .api.catalog import get_catalog

    cat = get_catalog()
    table = Table(show_lines=False)
    if endpoints:
        table.add_column("endpoint")
        table.add_column("columns")
        for hit in cat.search_endpoints(search):
            table.add_row(hit["endpoint"], ", ".join(hit["columns"][:8]) + (" …" if len(hit["columns"]) > 8 else ""))
    else:
        table.add_column("command")
        table.add_column("parameters")
        for hit in cat.search_commands(search):
            table.add_row(hit["command"], ", ".join(hit["parameters"][:8]) + (" …" if len(hit["parameters"]) > 8 else ""))
    console.print(table)


@app.command()
def version() -> None:
    """Print the lanforge-mcp version."""
    typer.echo(__version__)


if __name__ == "__main__":
    app()
