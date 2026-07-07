# Security guide

## Threat model

An MCP server hands an AI model real control over network test hardware. The
risks: the model deleting test configuration, disrupting running tests,
rebooting resources, running arbitrary shell commands, or a remote attacker
reaching the MCP HTTP endpoint.

## Controls

| Control | Default | Where |
|---|---|---|
| Destructive-command confirmation (`rm_*`, `reset_*`, `reboot`, DB `load`, destructive shell) | on | `safety.require_confirmation` |
| Dry-run mode (mutations return the planned request) | off | `safety.dry_run`, `--dry-run`, `set_safety_mode` |
| Read-only mode (all mutations blocked) | off | `safety.read_only`, `--read-only` |
| Shell execution kill-switch | on (allowed) | `safety.allow_shell: false` |
| Audit log of every mutation, JSONL | on | `safety.audit_log_path` |
| Extra destructive commands | — | `safety.extra_destructive_commands` |

Recommended posture for unattended/agentic use: `read_only: true` for analysis
sessions; `dry_run: true` when reviewing AI-generated test plans; full access
only on isolated lab networks.

## Credentials

* LANforge ships with `lanforge`/`lanforge` — change it, and set per-system
  credentials in `config.yaml` or `LANFORGE_MCP_PASSWORD`.
* Prefer SSH keys (`ssh_key_file`) over passwords.
* The config file may contain secrets: keep it out of version control and mount
  it read-only in containers.
* HTTPS to the GUI sends HTTP Basic auth; enable `verify_ssl: true` when the
  GUI has a real certificate.

## Network exposure

* The default transport is **stdio** — no listening socket at all.
* The HTTP transport binds `127.0.0.1` by default. If you bind `0.0.0.0`, put
  it behind a reverse proxy with TLS + authentication; the MCP endpoint itself
  performs no client authentication.
* The server needs to reach the LANforge GUI (8080/tcp) and SSH (22/tcp) only.
  Run it inside the lab network; don't NAT LANforge to the internet.

## Prompt-injection surface

Tool results include text originating from the testbed (port aliases, event
descriptions, script output). A hostile DUT could try to smuggle instructions
through those strings. Mitigations: confirmation gating on destructive actions
regardless of what the model "believes", read-only/dry-run modes, and the audit
log for after-the-fact review.
