# User guide

## 1. Install

```bash
git clone https://github.com/lanforge-mcp/lanforge-mcp
cd lanforge-mcp
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e .
```

Verify connectivity to your LANforge (the GUI must be running with its JSON API
on port 8080, which is the default):

```bash
lanforge-mcp check --host 192.168.1.50
```

## 2. Hook it up to your AI client

**Claude Desktop / Claude Code / Cursor / Windsurf / Cline / Continue.dev** — add
to the client's MCP config:

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

**Remote / shared deployments** — run the HTTP transport and point clients at it:

```bash
lanforge-mcp serve --transport http --bind 0.0.0.0 --port 8231 --config config.yaml
# clients connect to http://server:8231/mcp
```

**Docker**: `docker compose up` (set `LANFORGE_HOST` in the environment).

## 3. Configuration

Precedence: CLI flags > `LANFORGE_MCP_*` environment variables > config file >
defaults. Config file search order: `lanforge-mcp.yaml`, `config.yaml`,
`~/.config/lanforge-mcp/config.yaml`. See [examples/config.yaml](../examples/config.yaml)
for every option, including multiple LANforge systems.

To let the AI run the 115+ automation scripts, either:

* set `scripts.local_path` to a checkout of
  [lanforge-scripts](https://github.com/greearb/lanforge-scripts) with its
  dependencies installed in the Python named by `scripts.python_exec`, **or**
* do nothing — the server falls back to running the scripts already installed
  at `/home/lanforge/scripts/py-scripts` on the LANforge box over SSH.

## 4. What to ask the AI

The server's tool instructions teach the model the ropes, so plain English works:

* "Connect to the LANforge at 192.168.1.50 and show me the testbed inventory."
* "Create 10 WPA2 stations on wiphy1 for SSID 'Lab-AP' and tell me when they all
  have IP addresses."
* "Run UDP traffic at 100 Mbps between sta0000 and eth1 for two minutes, then
  give me a throughput report."
* "Why did my stations disconnect?" (event-log pattern analysis)
* "Run the WiFi capacity test script with 32 stations in the background and
  check on it every few minutes."
* "Stop all traffic and clean up everything you created."

See [examples/conversations.md](../examples/conversations.md) for full transcripts.

## 5. Safety modes

* **Confirmation** — destructive operations (`rm_*`, `reset_*`, `reboot`, DB
  `load`, destructive shell commands) fail with a structured error until the
  call is repeated with `confirm=true`. The AI is told this in the error hint.
* **Dry-run** — `set_safety_mode(dry_run=true)` (or `--dry-run`, or
  `LANFORGE_MCP_DRY_RUN=1`): every mutation returns the exact request it would
  have sent. Great for reviewing an AI's plan before letting it loose.
* **Read-only** — `--read-only`: all mutations are blocked; queries,
  monitoring, diagnostics and reports still work.
* **Audit log** — every mutation (including blocked ones) is appended to
  `lanforge-mcp-audit.jsonl` with timestamp, system, parameters and outcome.

## 6. Reports

`generate_report`, the `report` workflow step, and `monitor` outputs feed a
report engine that writes Markdown, standalone HTML (print to PDF from any
browser) and JSON into `reports.output_dir`, each with computed min/avg/max
statistics and an AI-summary block.
