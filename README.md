# lanforge-mcp

**The complete power of [Candela LANforge](https://www.candelatech.com/) for any MCP-compatible AI model.**

`lanforge-mcp` is a production-grade [Model Context Protocol](https://modelcontextprotocol.io) server that turns an LLM into an intelligent LANforge operator. It works with Claude, ChatGPT, Gemini, Cursor, Windsurf, VS Code, Continue.dev, Cline, RooCode, OpenHands, OpenWebUI, Ollama-hosted models — anything that speaks MCP.

## What the AI can do with it

- **Create and run any test**: WiFi stations (WPA/WPA2/WPA3/Enterprise), Layer-3 UDP/TCP/multicast, Layer-4 HTTP/HTTPS/FTP, VoIP, WAN emulation, roaming, DFS, mesh, MU-MIMO/OFDMA, dataplane, chamber automation, Bluetooth — everything LANforge itself can do.
- **Execute any of the 600+ CLI commands** through the JSON API (`run_command`, `raw_cli`), discovered dynamically (`list_commands`, `command_help`).
- **Query every LANforge data table** (`query`, `list_endpoints`): ports, stations, connections, events, alerts, radios, WiFi stats, attenuators, chambers, DUTs…
- **Run any of the 115+ [lanforge-scripts](https://github.com/greearb/lanforge-scripts) py-scripts** (`list_scripts`, `script_schema`, `run_script`) — argument schemas are extracted automatically from the scripts' argparse, so new scripts appear without any server change.
- **Run whole test campaigns as one call** with the workflow engine: create → associate → traffic → sample → report → cleanup, with variables, condition polling, retries and dry-run.
- **Diagnose problems**: `diagnose_stations` (who failed and why), `diagnose_traffic` (zero-throughput/drops), `analyze_events` (disconnect/roam/DFS patterns), `compare_throughput` (today vs yesterday).
- **Produce reports**: Markdown + print-ready HTML + JSON with computed statistics and AI-friendly summaries.
- **Stay safe**: dry-run mode, read-only mode, mandatory `confirm=true` for destructive operations, JSONL audit logging of every mutation.

## Quick start

```bash
pip install -e .                       # from a checkout (Python 3.12+)
lanforge-mcp check --host 192.168.1.50 # verify connectivity
lanforge-mcp serve --host 192.168.1.50 # stdio MCP server, single system
```

### Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "lanforge": {
      "command": "lanforge-mcp",
      "args": ["serve", "--host", "192.168.1.50"]
    }
  }
}
```

### Remote (HTTP) deployment

```bash
lanforge-mcp serve --transport http --bind 0.0.0.0 --port 8231 --config config.yaml
# or: docker compose up
```

### Configuration

`config.yaml` (see [examples/config.yaml](examples/config.yaml)):

```yaml
systems:
  - id: testbed-1
    host: 192.168.1.50        # LANforge GUI JSON API host
    port: 8080
    username: lanforge         # also used for SSH
    password: lanforge
  - id: testbed-2
    host: 192.168.1.60
safety:
  read_only: false
  dry_run: false
  require_confirmation: true
  audit_log_path: lanforge-mcp-audit.jsonl
scripts:
  local_path: ~/lanforge-scripts   # optional local checkout; falls back to
  remote_path: /home/lanforge/scripts/py-scripts   # the LANforge box via SSH
reports:
  output_dir: lanforge-reports
```

Environment variables override the file: `LANFORGE_MCP_HOST`, `LANFORGE_MCP_USERNAME`, `LANFORGE_MCP_PASSWORD`, `LANFORGE_MCP_READ_ONLY`, `LANFORGE_MCP_DRY_RUN`, `LANFORGE_MCP_SCRIPTS_PATH`, `LANFORGE_MCP_REPORTS_DIR`, `LANFORGE_MCP_LOG_LEVEL`, …

## Design: ~40 curated tools + a dynamic gateway to everything

Instead of one MCP tool per LANforge command (600+ tools no model selects from reliably), the server exposes high-level operator tools plus discovery/invocation gateways:

| Group | Tools |
|---|---|
| Connection | `connect`, `disconnect`, `systems`, `health_check`, `set_safety_mode` |
| Inventory | `inventory`, `query`, `list_endpoints` |
| CLI gateway | `list_commands`, `command_help`, `run_command`, `raw_cli`, `shell_command` |
| Stations | `create_stations`, `station_status`, `set_port_state`, `remove_ports` |
| Traffic | `create_l3_traffic`, `create_l4_traffic`, `start_traffic`, `stop_traffic`, `remove_traffic`, `traffic_stats` |
| Monitoring | `events`, `alerts`, `monitor` |
| Scripts | `list_scripts`, `script_schema`, `run_script`, `script_status`, `script_output`, `cancel_script`, `list_script_runs` |
| Workflows | `list_workflow_templates`, `workflow_template_spec`, `run_workflow_template`, `run_workflow`, `workflow_status`, `cancel_workflow` |
| Reports | `generate_report` |
| Diagnostics | `diagnose_stations`, `diagnose_traffic`, `analyze_events`, `compare_throughput` |

When LANforge is upgraded, new commands/endpoints/scripts show up in the discovery tools automatically — the offline catalogs (generated from the official `lanforge_api.py` by `tools/generate_catalog.py`) are advisory only, and unknown commands are forwarded to the GUI unchanged.

## Documentation

- [Architecture](docs/architecture.md) — the six layers and how they compose
- [Tool reference](docs/tools.md)
- [User guide](docs/user-guide.md) · [Developer guide](docs/developer-guide.md)
- [Security guide](docs/security.md) · [Troubleshooting](docs/troubleshooting.md)
- [Example AI conversations](examples/conversations.md)

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                 # unit + integration tests against a mock LANforge
ruff check src tests   # lint
mypy src               # types
python tools/generate_catalog.py --repo /path/to/lanforge-scripts  # refresh catalogs
```

## License

MIT. LANforge and lanforge-scripts are products of Candela Technologies; this project is an independent open-source integration.
