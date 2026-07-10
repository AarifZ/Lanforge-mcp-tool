# Changelog

## 0.1.2 — 2026-07-11

Integrates findings from the first validation run against real hardware
(LANforge 5.5.2.1 / JsonVersion 1.0.37131); see docs/field-notes.md.

Fixed:
- `station_status` / `diagnose_stations` with no EIDs misclassified associated
  stations as failed: the bulk `/port` view omits dynamic WiFi columns
  (ip/ap/signal/channel/mode) unless requested. Diagnostics now request an
  explicit, catalog-verified column set. (Found and first patched during the
  live run; the GUI rejects unknown field names, e.g. `rssi` is not a column.)
- Workflow `wait_for` steps now always request the condition field as a column,
  so conditions can't silently pass/fail on a missing key.
- `create_stations` association polling requests explicit columns.
- Numeric parsing now understands unit-suffixed LANforge values ("-31 dBm",
  "80 MHz", "97%") in reports, monitoring stats and signal-strength checks.

Improved:
- `query('stations')` 404s on some builds even though the API client documents
  the endpoint: the error now carries a hint to use `port` instead, and
  `list_endpoints` annotates the entry with a version-quirk note.
- `remove_ports` safety errors name the high-level tool and target EID instead
  of only the internal `rm_vlan` command.
- Schema ergonomics: `list_endpoints(limit=)`, `list_scripts(limit=)`,
  `inventory(summary=true)`.
- Mock LANforge now emulates the sparse bulk `/port` view and rejects unknown
  field names, so these behaviors are regression-tested (65 tests).

## 0.1.1 — 2026-07-11

- Python floor lowered to 3.10 (vermin-verified) for older LANforge-box Pythons;
  `datetime.UTC` replaced with `timezone.utc`.
- LANforge pre-encoded column names (`port+type`, `%28us%29`) are decoded before
  the request so `fields=` reaches the GUI encoded exactly once.
- Keyed single-row responses (`/radiostatus` `"1.1.wiphy0"`) keep their EID.
- HTTP retry exhaustion returns the GUI's real error instead of a fake outage.
- `lanforge-mcp check` probes the JSON API and SSH separately.

## 0.1.0 — 2026-07-11

Initial release: six-layer architecture, 44 MCP tools (curated operator tools +
dynamic gateways to 600+ CLI commands, 41 JSON endpoints, 115+ py-scripts),
workflow engine with templates, report engine, diagnostics, safety layer,
mock-LANforge test suite, Docker, CI, documentation.
