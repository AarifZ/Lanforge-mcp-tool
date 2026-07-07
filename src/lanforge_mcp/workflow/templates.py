"""Built-in workflow templates — reusable test recipes.

Each template is a plain WorkflowSpec dict with ``${variable}`` placeholders
and documented default variables. The LLM can list them, inspect them, run
them as-is, or copy and modify the steps.
"""

from __future__ import annotations

from typing import Any

from ..errors import WorkflowError
from ..models import WorkflowSpec

TEMPLATES: dict[str, dict[str, Any]] = {
    "sta_connect_smoke": {
        "name": "sta_connect_smoke",
        "description": (
            "Create one WiFi station, wait until it associates and gets an IP via DHCP, "
            "then clean it up. Fast sanity check that an AP/SSID is joinable. "
            "Variables: resource, radio, sta_name, ssid, passwd."
        ),
        "variables": {
            "resource": 1,
            "radio": "wiphy0",
            "sta_name": "sta0000",
            "ssid": "test-ssid",
            "passwd": "password",
        },
        "steps": [
            {
                "action": "command",
                "name": "create station",
                "command": "add_sta",
                "params": {
                    "shelf": 1,
                    "resource": "${resource}",
                    "radio": "${radio}",
                    "sta_name": "${sta_name}",
                    "ssid": "${ssid}",
                    "key": "${passwd}",
                    "mode": 0,
                    "mac": "xx:xx:xx:xx:*:xx",
                    "flags": 1024,  # use WPA2
                },
            },
            {
                "action": "command",
                "name": "set DHCP and bring port up",
                "command": "set_port",
                "params": {
                    "shelf": 1,
                    "resource": "${resource}",
                    "port": "${sta_name}",
                    "current_flags": 0x80000000,  # use_dhcp, admin-up (down bit clear)
                    "interest": 0x804002,  # current_flags | dhcp | ifdown
                },
            },
            {
                "action": "wait_for",
                "name": "wait for DHCP address",
                "endpoint": "port",
                "eids": ["1", "${resource}", "${sta_name}"],
                "until": {"field": "ip", "op": "ne", "value": "0.0.0.0"},
                "timeout_sec": 120,
                "interval_sec": 3,
                "register": "assoc",
            },
            {
                "action": "report",
                "name": "connection report",
                "title": "Station connect smoke test: ${sta_name} on ${ssid}",
                "data": "${assoc}",
            },
            {
                "action": "command",
                "name": "remove station",
                "command": "rm_vlan",
                "params": {"shelf": 1, "resource": "${resource}", "port": "${sta_name}"},
                "confirm": True,
                "on_error": "continue",
            },
        ],
    },
    "l3_throughput": {
        "name": "l3_throughput",
        "description": (
            "Create a bidirectional Layer-3 connection between two existing ports, run "
            "traffic, sample throughput, stop and clean up, and produce a report. "
            "Variables: resource, port_a, port_b, cx_name, cx_type "
            "(lf_udp|lf_tcp), rate_a_bps, rate_b_bps, duration_sec."
        ),
        "variables": {
            "resource": 1,
            "port_a": "eth1",
            "port_b": "eth2",
            "cx_name": "mcp-l3",
            "cx_type": "lf_udp",
            "rate_a_bps": 1000000,
            "rate_b_bps": 1000000,
            "duration_sec": 60,
        },
        "steps": [
            {
                "action": "command",
                "name": "endpoint A",
                "command": "add_endp",
                "params": {
                    "alias": "${cx_name}-A",
                    "shelf": 1,
                    "resource": "${resource}",
                    "port": "${port_a}",
                    "type": "${cx_type}",
                    "ip_port": -1,
                    "min_rate": "${rate_a_bps}",
                    "max_rate": 0,
                },
            },
            {
                "action": "command",
                "name": "endpoint B",
                "command": "add_endp",
                "params": {
                    "alias": "${cx_name}-B",
                    "shelf": 1,
                    "resource": "${resource}",
                    "port": "${port_b}",
                    "type": "${cx_type}",
                    "ip_port": -1,
                    "min_rate": "${rate_b_bps}",
                    "max_rate": 0,
                },
            },
            {
                "action": "command",
                "name": "cross-connect",
                "command": "add_cx",
                "params": {
                    "alias": "${cx_name}",
                    "test_mgr": "default_tm",
                    "tx_endp": "${cx_name}-A",
                    "rx_endp": "${cx_name}-B",
                },
            },
            {
                "action": "command",
                "name": "start traffic",
                "command": "set_cx_state",
                "params": {"test_mgr": "default_tm", "cx_name": "${cx_name}", "cx_state": "RUNNING"},
            },
            {
                "action": "sample",
                "name": "sample throughput",
                "endpoint": "cx",
                "interval_sec": 5,
                "duration_sec": "${duration_sec}",
                "register": "stats",
            },
            {
                "action": "command",
                "name": "stop traffic",
                "command": "set_cx_state",
                "params": {"test_mgr": "default_tm", "cx_name": "${cx_name}", "cx_state": "STOPPED"},
                "on_error": "continue",
            },
            {
                "action": "report",
                "name": "throughput report",
                "title": "L3 ${cx_type} throughput: ${port_a} <-> ${port_b}",
                "data": "${stats}",
            },
            {
                "action": "command",
                "name": "remove cx",
                "command": "rm_cx",
                "params": {"test_mgr": "default_tm", "cx_name": "${cx_name}"},
                "confirm": True,
                "on_error": "continue",
            },
            {
                "action": "command",
                "name": "remove endpoint A",
                "command": "rm_endp",
                "params": {"endp_name": "${cx_name}-A"},
                "confirm": True,
                "on_error": "continue",
            },
            {
                "action": "command",
                "name": "remove endpoint B",
                "command": "rm_endp",
                "params": {"endp_name": "${cx_name}-B"},
                "confirm": True,
                "on_error": "continue",
            },
        ],
    },
    "l4_http_load": {
        "name": "l4_http_load",
        "description": (
            "Create a Layer-4 HTTP endpoint on an existing port that repeatedly fetches a "
            "URL, run it, sample results, and clean up. Variables: resource, port, "
            "endp_name, url, urls_per_10min, duration_sec."
        ),
        "variables": {
            "resource": 1,
            "port": "eth1",
            "endp_name": "mcp-http",
            "url": "http://10.0.0.1/index.html",
            "urls_per_10min": 600,
            "duration_sec": 60,
        },
        "steps": [
            {
                "action": "command",
                "name": "create HTTP endpoint",
                "command": "add_l4_endp",
                "params": {
                    "alias": "${endp_name}",
                    "shelf": 1,
                    "resource": "${resource}",
                    "port": "${port}",
                    "type": "l4_generic",
                    "timeout": 10000,
                    "url_rate": "${urls_per_10min}",
                    "url": "dl ${url} /dev/null",
                },
            },
            {
                "action": "command",
                "name": "cross-connect",
                "command": "add_cx",
                "params": {
                    "alias": "CX_${endp_name}",
                    "test_mgr": "default_tm",
                    "tx_endp": "${endp_name}",
                    "rx_endp": "NA",
                },
            },
            {
                "action": "command",
                "name": "start",
                "command": "set_cx_state",
                "params": {"test_mgr": "default_tm", "cx_name": "CX_${endp_name}", "cx_state": "RUNNING"},
            },
            {
                "action": "sample",
                "name": "sample L4 stats",
                "endpoint": "layer4",
                "interval_sec": 5,
                "duration_sec": "${duration_sec}",
                "register": "stats",
            },
            {
                "action": "command",
                "name": "stop",
                "command": "set_cx_state",
                "params": {"test_mgr": "default_tm", "cx_name": "CX_${endp_name}", "cx_state": "STOPPED"},
                "on_error": "continue",
            },
            {
                "action": "report",
                "name": "L4 report",
                "title": "L4 HTTP load: ${url}",
                "data": "${stats}",
            },
            {
                "action": "command",
                "name": "remove cx",
                "command": "rm_cx",
                "params": {"test_mgr": "default_tm", "cx_name": "CX_${endp_name}"},
                "confirm": True,
                "on_error": "continue",
            },
            {
                "action": "command",
                "name": "remove endpoint",
                "command": "rm_endp",
                "params": {"endp_name": "${endp_name}"},
                "confirm": True,
                "on_error": "continue",
            },
        ],
    },
    "stop_all_traffic": {
        "name": "stop_all_traffic",
        "description": "Stop every running cross-connect and clear counters. No variables.",
        "variables": {},
        "steps": [
            {
                "action": "raw",
                "name": "stop all cx",
                "line": "set_cx_state all all STOPPED",
            },
            {"action": "wait", "name": "settle", "seconds": 2},
            {
                "action": "query",
                "name": "verify",
                "endpoint": "cx",
                "register": "cx_after",
            },
        ],
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {"template": name, "description": t["description"], "variables": list(t["variables"])}
        for name, t in TEMPLATES.items()
    ]


def get_template(name: str, variables: dict[str, Any] | None = None) -> WorkflowSpec:
    if name not in TEMPLATES:
        raise WorkflowError(
            f"Unknown workflow template '{name}'.",
            details={"available": list(TEMPLATES)},
        )
    raw = dict(TEMPLATES[name])
    merged_vars = {**raw.get("variables", {}), **(variables or {})}
    return WorkflowSpec.model_validate({**raw, "variables": merged_vars})
