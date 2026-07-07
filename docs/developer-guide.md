# Developer guide

## Setup

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest          # 56 tests against the in-process mock LANforge
ruff check src tests tools
mypy src
```

## Code map

```
src/lanforge_mcp/
├── config.py        # yaml + env + CLI override merging -> AppConfig
├── models.py        # every Pydantic model (config, results, workflow specs)
├── errors.py        # exception hierarchy; all errors serialize to LLM-friendly JSON
├── safety.py        # SafetyGuard: read-only / dry-run / confirm / audit JSONL
├── connection/      # L1: httpx pool + session header, paramiko-in-thread SSH
├── api/             # L2: JsonApi (query/command/raw/help) + offline catalogs
├── cliwrap/         # L3: ShellExecutor (SSH, structured results)
├── scripts/         # L4: ast-based argparse discovery + local/remote runner
├── workflow/        # L5: engine (substitution, wait_for, sample) + templates
├── reports/         # L6: markdown/html/json rendering + stats
├── diagnostics/     # station/traffic/event analyzers
└── server/          # FastMCP assembly; tools/ has one module per tool group
```

## Design rules

1. **Tools never raise at the model.** Wrap tool bodies with `@tool_errors`;
   `LANforgeMCPError` subclasses become `{"ok": false, "error": {type, message,
   hint}}` so the LLM can self-correct. Everything else is caught, logged with
   traceback, and reported as `internal_error` — the server never crashes.
2. **The GUI is the authority.** The offline catalogs are hints for discovery
   and validation; `run_command` forwards unknown commands unchanged so a newer
   LANforge keeps working.
3. **Mutations go through `SafetyGuard`.** If you add a new mutating path, call
   `check_command` / `check_shell` / `check_script` first.
4. **paramiko never blocks the loop.** All SSH work runs via
   `anyio.to_thread.run_sync` inside `LFSshClient`.
5. **Keep tool output LLM-sized.** Truncate long rows/logs and say so in the
   payload (`truncated: true`, `note: ...`).

## Adding a tool

Add a function inside the matching `server/tools/*_tools.py` `register()`:

```python
@mcp.tool(tags={"traffic"})
@tool_errors
async def my_tool(
    param: Annotated[str, Field(description="Shown to the model — be specific")],
    system_id: Annotated[str | None, Field(description="Which system")] = None,
) -> dict:
    """One-line summary the model sees first.

    Longer guidance: when to use it, what it returns, related tools.
    """
    api = ctx.api(system_id)
    ...
    return {"ok": True, ...}
```

Then regenerate the docs: `python tools/generate_tool_docs.py`.

## Regenerating the catalogs

When Candela updates `lanforge_api.py`:

```bash
git clone --depth 1 https://github.com/greearb/lanforge-scripts /tmp/lfs
python tools/generate_catalog.py --repo /tmp/lfs
```

The generator is pure `ast` parsing — it never imports or executes the
lanforge-scripts code.

## Testing

`tests/mock_lanforge.py` is a Starlette app emulating the GUI: session header,
LANforge-style keyed-row GET responses, and stateful `/cli-json/*` handlers
(`add_sta` creates ports, `set_port` with the DHCP flag "associates" them,
`set_cx_state` moves traffic counters…). The `server` fixture wires it into the
full stack via `httpx.ASGITransport`, and `test_tools.py` exercises tools
through a real in-memory FastMCP client session. Extend the mock when you need
new endpoints — keep its response shapes faithful to real LANforge quirks.
