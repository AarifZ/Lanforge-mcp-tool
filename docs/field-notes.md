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

When you hit a new version-specific quirk: add it here, teach the mock in
`tests/mock_lanforge.py` to emulate it, and pin it with a test.
