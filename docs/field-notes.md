# Field notes — verified LANforge GUI behavior

Observations from validation against real hardware. Version-specific quirks the
code depends on live here; each has a regression test against the mock.

## LANforge 5.5.2.1 (JsonVersion 1.0.37131), CT523c pair — 2026-07-08

1. **Bulk `/port` omits dynamic WiFi columns.** `GET /port` without `?fields=`
   returns only basic fields (alias/phantom/down/…) — no `ip`, `ap`, `signal`,
   `channel`, `mode`. An explicit-EID lookup (`/port/1/2/sta0000`) returns the
   full row. Consequence: anything that reads station state from the bulk view
   must pass `?fields=`. (This misclassified an associated station — IP
   192.168.1.191, −31 dBm — as failed until diagnostics requested explicit
   columns.)

2. **Unknown field names are rejected, not ignored.** Requesting
   `?fields=rssi` errors: `rssi` is not a `/port` column (`signal` is). Only
   request catalog-verified names — see `data/endpoints.json`.

3. **`/stations` is documented but not served.** The official API client lists
   a `/stations` endpoint; this GUI build returns 404 for it. WiFi stations are
   `/port` rows (`port type == WIFI-STA`). `query('stations')` returns a hint,
   and `list_endpoints` carries a note.

4. **Values carry units.** Port/station tables return strings like `-31 dBm`
   and modes like `802.11an-BE 80 2x2`. `reports.engine._to_float` parses
   number-plus-unit strings but deliberately rejects identifier-like strings
   (`1.1.eth0`).

5. **`/newsession` + `X-LFJson-Session` works as documented**, GUI info comes
   from `GET /` (`BuildVersion 5.5.2.1`), and read-only safety blocked every
   attempted mutation (`run_command`, `raw_cli`, `shell_command`,
   `remove_ports`, `create_l3_traffic`) with no artifacts left on the system.

## LANforge 5.5.2 (JsonVersion 1.0.36887), CT523c ct523c-69cb — 2026-07-11

Direct testing through the MCP tools (station lifecycle, attenuator control,
remote script execution all verified end-to-end on this unit).

6. **Nine endpoints use dash-separated URLs** (`/wifi-stats`, `/status-msg`,
   `/test-group`, `/wifi-msgs`, `/ws-msg`, `/gui-cli`, `/arm-endp`,
   `/voip-endp`, `/wl-endp`) — the underscore forms 404. The catalog now
   records real URLs and `query()` resolves names through it.

7. **Every table carries a `candela.lanforge.Http*` pseudo-row** (HttpPort,
   HttpEvents, HttpResource, HttpAttenuator, …) describing the API handler
   itself. The HttpEvents row shows up in `/alerts` and looks like an active
   alert. Diagnostics/inventory filter these (`json_api.data_rows`).

8. **Bulk views are even sparser here**: default `/port` rows contain only
   `eid` + `duration`. Explicit `?fields=` everywhere is mandatory.

9. **New ports are phantom for a few seconds** while the kernel netdev is
   created; `set_port` during that window fails with
   `rv: 22 (Invalid argument)`. Wait for `phantom == false` first (the
   `create_stations` tool and `sta_connect_smoke` template do). `set_port`
   also wants the LFUtils request shape: `interest` masks plus `report_timer`.

10. **Nonexistent EIDs return 404**, not empty rows: after `rm_vlan`,
    `GET /port/1/1/<name>` 404s — that's the "confirmed deleted" signal.

11. **The attenuator table lags writes by a few seconds.** `set_attenuator`
    (val in ddB, `atten_idx` 0-7 or 'all') returns success immediately;
    re-reading `/attenuator` right away may show stale values.

12. **`/scan` returns HTTP 500** (GUI NullPointerException) when no scan
    results exist.

13. Responses may carry the warning `LFHttp: No license terms registered yet`
    — unrelated to the request; ignore it.

14. **A cross-connect is not runnable immediately after `add_cx`.** An instant
    `set_cx_state RUNNING` returns not-ok; poll the `cx` table until the
    connection appears (a second or two), then start it.

15. **The `cx` bulk view is sparse too** — `state`, `bps rx a/b`, drops are
    null unless requested via `?fields=`. Same for most tables; always pass
    columns when reading dynamic values.

16. **AP-in-a-box works well**: a WPA2 VAP (add_vap + static-IP set_port) on one
    radio and a station on another associate and pass traffic even on the same
    chassis; 5 GHz keeps clear of a 2.4 GHz external AP. Verified ~50 Mbps/dir
    L3 UDP at 0% loss, station↔VAP ping ~5 ms.

When you hit a new version-specific quirk: add it here, teach the mock in
`tests/mock_lanforge.py` to emulate it, and pin it with a test.
