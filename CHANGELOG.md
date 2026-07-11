# Changelog

## 0.1.5 — 2026-07-11

Verified live end-to-end on LANforge 5.5.2: created a WPA2 VAP (5 GHz ch36),
associated a station to it, ran bidirectional L3 UDP, and produced a report
showing ~50 Mbps/direction at 0% loss — the full create → associate →
traffic → monitor → report pipeline over real WiFi.

Fixed:
- `create_l3_traffic(start=True)` reported `started=False`: a cross-connect is
  not immediately runnable after add_cx on this build, so the instant
  set_cx_state RUNNING failed. It now polls for the cx to register, then
  starts (and returns start_errors if it still fails).
- The `cx` bulk view omits state/throughput columns (same sparse-view quirk as
  port). `traffic_stats`, `diagnose_traffic` and `monitor('cx')` now request an
  explicit cx column set, so throughput/state actually come back.
- Report AI-summary separator changed from '·' to '-' to avoid mojibake in
  non-UTF-8 terminals/viewers.

## 0.1.4 — 2026-07-11

Found live while setting up a macvlan-upstream WiFi capacity test.

Fixed:
- EID path segments are now URL-encoded. Virtual-port names contain characters
  that are special in URLs — macvlans use '#' (a fragment separator!), so
  `query(eids=["1.1.eth0#1"])` requested `/port/1/1/eth0#1`, which the client
  truncated at '#' and silently returned the parent `eth0` instead. Macvlan,
  QVLAN and similar EIDs now resolve correctly.

Verified live (LANforge 5.5.2): macvlan created on eth0 via add_mvlan +
DHCP set_port obtained a lease (192.168.217.175); readable back through the
fixed EID path.

## 0.1.3 — 2026-07-11

Verified end-to-end against live hardware (LANforge 5.5.2, CT523c): station
create → diagnose → remove, attenuator list/set/restore, remote script
discovery + execution, all through the real MCP tools. New quirks recorded in
docs/field-notes.md.

Fixed:
- Catalog URL extraction missed every documented URL variant (regex lacked
  re.MULTILINE); nine endpoints (wifi_stats, status_msg, test_group, wifi_msg,
  ws_msg, gui_cli, arm_endp, voip_endp, wl_endp) now map to their real
  dash-separated paths, and `query()` resolves names through the catalog.
- `create_stations` failed `set_port` with EINVAL on live systems: new ports
  stay phantom for a few seconds and this build also requires the LFUtils
  request shape (interest masks + report_timer). Stations are now created,
  awaited until non-phantom, then configured. Template updated likewise.
- Diagnostics/inventory/health treated the GUI's `candela.lanforge.Http*`
  handler pseudo-rows as data (a bogus "active alert", a bogus resource).
  They are filtered everywhere summaries are produced.
- health_check semantics: real alerts drive ok=false; phantom resources/ports
  (often intentional on testbeds) are reported as notes.
- inventory requests explicit resource/radio columns (bulk views on 5.5.2
  return only eid+duration) and now returns radio driver/channel details.
- EID-specific queries that 404 (entity deleted / typo) now say so with an
  actionable hint instead of a generic 404.

Added:
- Attenuator tool group: `attenuators` (per-module dB listing) and
  `set_attenuation` (dB, module 1-8 or all) — verified on a CT-style
  attenuator live, including restore.
- Mock emulates phantom materialization, set_port-EINVAL-on-phantom, pseudo
  rows, the attenuator table, and /wifi-stats (68 tests).

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
