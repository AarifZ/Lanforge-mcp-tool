# Troubleshooting

## Connection

**`connection_error: Cannot reach LANforge GUI`**
The JSON API is served by the LANforge *GUI*, not the OS. Check that the GUI is
running on the LANforge machine and listening on 8080 (`curl http://LF_IP:8080/`
should return JSON). Headless systems can run the GUI with `-daemon`.

**`ssh_error`** — verify `ssh lanforge@LF_IP` works by hand; set `ssh_username`
/ `ssh_password` / `ssh_key_file` per system if you changed the defaults.

**Multiple systems: `system_not_found`** — every tool accepts `system_id`; when
more than one system is configured it must be provided. `systems()` lists ids.

## Commands

**`safety_blocked ... requires confirmation`** — expected for `rm_*`, `reset_*`,
`reboot`, etc. Repeat the call with `confirm=true` (this is per-call, not a mode).

**Command "succeeds" but nothing happens** — check `warnings` in the result: an
unknown command is forwarded as-is and the GUI may have ignored it. Use
`command_help(command, live=true)` to check the installed version's parameters.

**`'X' is not a valid command name; use raw_cli for full command lines`** —
`run_command` takes a bare command name plus `params`; whole lines like
`"reset_port 1 1 sta0"` go to `raw_cli`.

## Queries

**`query_error: 404`** — the endpoint doesn't exist on this LANforge version;
`list_endpoints()` shows what the catalog knows, and bare `/` lists what the GUI
itself serves.

**Empty rows for a specific station** — EIDs must include shelf and resource:
`1.1.sta0000`, not `sta0000` (bare names assume `1.1.`).

## Scripts

**`list_scripts` returns nothing** — set `scripts.local_path` to a
lanforge-scripts checkout, or ensure SSH works so the server can list
`/home/lanforge/scripts/py-scripts` remotely. Use `list_scripts(refresh=true)`
after installing new scripts.

**Local script run fails immediately** — the interpreter in
`scripts.python_exec` must have the lanforge-scripts dependencies installed
(`pip install -r requirements.txt` in that repo). Remote mode avoids this: the
LANforge box already has them.

**Long tests time out** — pass `timeout_sec` explicitly, or use
`background=true` + `script_status`.

## Workflows

**`wait_for timed out`** — the error includes the last rows polled; check the
`field` name matches a real column (`query` the endpoint once to see columns)
and that `match: any` vs `all` is what you meant.

**`Variable path '${x}' not found`** — a step referenced a variable that no
earlier step `register`ed; check step order and `register` spelling.

## Server

**No output / client can't connect over stdio** — nothing may print to stdout;
lanforge-mcp logs to stderr by design. If you wrapped the command in a script,
make sure it doesn't echo.

**Where are reports/audit logs?** — `reports.output_dir` (default
`lanforge-reports/`) and `safety.audit_log_path` (default
`lanforge-mcp-audit.jsonl`), relative to the server's working directory.
