# Example AI conversations

Real interaction patterns between a user, an MCP-connected AI, and lanforge-mcp.
(Tool calls shown inline; any MCP client behaves equivalently.)

---

## 1. First contact with a testbed

> **User:** Connect to my LANforge at 192.168.1.50 and tell me what I have to work with.

```
AI → connect(host="192.168.1.50")
   ← {ok: true, system: "default", gui_info: {build_version: "5.5.1"}}
AI → inventory()
   ← {resources: [{eid: "1.1", hostname: "ct523c-lab"}],
      radios: [{eid: "1.1.wiphy0", channel: "36"}, {eid: "1.1.wiphy1", channel: "6"}],
      port_count: 7, station_count: 0, cx_count: 0, ...}
```

> **AI:** You have one chassis (ct523c-lab) with two radios — wiphy0 on channel 36
> (5 GHz) and wiphy1 on channel 6 (2.4 GHz) — plus eth1 free as an upstream port.
> No stations or traffic connections exist yet. What would you like to test?

---

## 2. Station bring-up with diagnosis

> **User:** Create 5 WPA2 stations on wiphy0 for SSID "Lab-AP" password "lab-pass-99" and make sure they all connect.

```
AI → create_stations(radio="1.1.wiphy0", ssid="Lab-AP", passwd="lab-pass-99",
                     num_stations=5, wait_for_ip_sec=60)
   ← {ok: true, created: [sta0000..sta0004],
      association: {associated: {sta0000: "10.1.1.101", ...}, no_ip_yet: ["sta0003"], all_up: false}}
AI → diagnose_stations(eids=["1.1.sta0003"])
   ← {failed_stations: [{station: "1.1.sta0003", problems: ["not associated to any AP",
      "no IP address (DHCP not complete or not associated)"]}]}
AI → analyze_events(keyword="sta0003")
   ← {pattern_counts: {disconnect: 3}, samples: {disconnect: [
      {event description: "sta0003 deauthenticated, reason 15 (4-way handshake timeout)"}]}}
```

> **AI:** 4 of 5 stations connected and got DHCP addresses. sta0003 failed the WPA2
> 4-way handshake three times (reason 15), which almost always means a key/AP-side
> issue rather than RF — the other stations on the same radio associate fine. Want
> me to retry sta0003, or check the AP's client limit?

---

## 3. Throughput test as one workflow

> **User:** Run 60 seconds of UDP at 50 Mbps each way between sta0000 and eth1 and give me a report.

```
AI → run_workflow_template(template="l3_throughput",
        variables={port_a: "sta0000", port_b: "eth1", cx_name: "udp-lab",
                   rate_a_bps: 50000000, rate_b_bps: 50000000, duration_sec: 60})
   ← {ok: true, state: "finished", steps: [ ... sample step ... ,
      report: {files: {html: "lanforge-reports/.../report.html"},
               ai_summary: ["udp-lab · bps rx a: avg 4.71e7, min 4.4e7, max 4.9e7 (n=12)", ...]}]}
```

> **AI:** Done — the connection sustained ~47 Mbps download / ~46 Mbps upload
> against the 50 Mbps offered load (≈94% efficiency), with no drops recorded.
> The full report (HTML/Markdown/JSON) is in lanforge-reports/…/report.html.
> Everything I created was cleaned up afterwards.

---

## 4. Reaching beyond the curated tools (dynamic gateway)

> **User:** Set up a WAN emulation link with 30ms latency between eth1 and eth2.

```
AI → list_commands(search="wanlink")
   ← {commands: [{command: "add_wl_endp", parameters: [alias, shelf, resource, port, latency, ...]}, ...]}
AI → command_help(command="add_wl_endp", live=true)
   ← {schema: {...}, live_help: "add_wl_endp: alias, shelf, resource, port, latency (ms), max_rate (bps)..."}
AI → run_command(command="add_wl_endp", params={alias: "wan-A", shelf: 1, resource: 1,
                 port: "eth1", latency: 30, max_rate: 1000000000})
AI → run_command(command="add_wl_endp", params={alias: "wan-B", ..., port: "eth2", latency: 30, ...})
AI → run_command(command="add_cx", params={alias: "wan-1", test_mgr: "default_tm",
                 tx_endp: "wan-A", rx_endp: "wan-B"})
```

> **AI:** WAN link "wan-1" is up: eth1↔eth2 with 30 ms latency each direction.
> I discovered the `add_wl_endp` command through the catalog — no dedicated
> "wanlink tool" was needed.

---

## 5. Long test in the background (scripts)

> **User:** Kick off the WiFi capacity test with up to 32 stations against Lab-AP and check on it as it runs.

```
AI → list_scripts(search="capacity")
   ← {scripts: [{script: "lf_wifi_capacity_test", location: "remote"}]}
AI → script_schema(script="lf_wifi_capacity_test")
   ← {summary: "This script runs LANforge GUI-based WiFi Capacity test.",
      schema: {properties: {radio, ssid, paswd, upstream, batch_size, ...}}}
AI → run_script(script="lf_wifi_capacity_test",
                args={radio: "wiphy0", ssid: "Lab-AP", paswd: "lab-pass-99",
                      upstream: "1.1.eth1", batch_size: "1,8,16,32"},
                background=true, timeout_sec=3600)
   ← {run_id: "9f3c2ab114e0", state: "running"}
... later ...
AI → script_status(run_id="9f3c2ab114e0")
   ← {state: "running", output_tail: "...batch 16: 412 Mbps aggregate..."}
```

> **AI:** The capacity test is at the 16-station batch, currently 412 Mbps
> aggregate. I'll pull the final report when it finishes.

---

## 6. Guardrails in action

> **User:** Wipe all the ports.

```
AI → run_command(command="rm_vlan", params={shelf: 1, resource: 1, port: "sta0000"})
   ← {ok: false, error: {type: "safety_blocked",
       message: "'rm_vlan' is destructive and requires confirmation.",
       hint: "Re-issue the call with confirm=true after verifying the target with a query."}}
AI → query(endpoint="port")   # verifies what actually exists first
```

> **AI:** Deleting ports is destructive, so I checked first: there are 5 stations
> (sta0000–sta0004) I created earlier, plus physical ports eth0–eth2 that can't
> be removed. Shall I delete the 5 stations? I'll need to confirm each removal.

> **User:** Yes, go ahead.

```
AI → remove_ports(eids=["1.1.sta0000", ..., "1.1.sta0004"], confirm=true)
   ← {ok: true, results: [...]}
```

> **AI:** All 5 stations removed. The audit log recorded each deletion.
