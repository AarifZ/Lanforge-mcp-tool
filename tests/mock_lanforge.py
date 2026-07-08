"""In-process mock of the LANforge GUI JSON API.

A Starlette ASGI app that emulates the real GUI's quirky response shapes:
``POST /newsession`` issues an ``X-LFJson-Session`` header, GET tables return
LANforge-style keyed rows, and ``POST /cli-json/<cmd>`` mutates an in-memory
testbed (ports, stations, cross-connects, events). Used with
``httpx.ASGITransport`` so integration tests need no network or hardware.
"""

from __future__ import annotations

import itertools
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

SESSION_HEADER = "X-LFJson-Session"


class MockState:
    def __init__(self) -> None:
        self.session_counter = itertools.count(1)
        self.ip_counter = itertools.count(100)
        self.ports: dict[str, dict[str, Any]] = {
            "1.1.eth0": self._port("eth0", "Ethernet", ip="192.168.1.10"),
            "1.1.eth1": self._port("eth1", "Ethernet", ip="10.0.0.1"),
            "1.1.wiphy0": self._port("wiphy0", "Radio"),
        }
        self.endps: dict[str, dict[str, Any]] = {}
        self.cxs: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = [
            {"time": "2026-07-08 10:00:00", "event description": "System started", "name": "system"},
        ]
        self.commands_received: list[dict[str, Any]] = []
        self.last_fields: str | None = None

    @staticmethod
    def _port(alias: str, ptype: str, ip: str = "0.0.0.0") -> dict[str, Any]:
        return {
            "alias": alias,
            "port type": ptype,
            "ip": ip,
            "phantom": False,
            "down": False,
            "ap": "",
            "signal": "",
            "channel": "",
            "mode": "",
        }

    def add_event(self, text: str, name: str = "mock") -> None:
        self.events.append({"time": "2026-07-08 12:00:00", "event description": text, "name": name})


def create_mock_app(state: MockState | None = None) -> tuple[Starlette, MockState]:
    st = state or MockState()

    async def newsession(_: Request) -> JSONResponse:
        return JSONResponse(
            {"session": "created"}, headers={SESSION_HEADER: f"mock-{next(st.session_counter)}"}
        )

    async def root(_: Request) -> JSONResponse:
        return JSONResponse({"VersionInfo": {"build_version": "5.5.1-mock"}})

    async def get_port(request: Request) -> JSONResponse:
        st.last_fields = request.query_params.get("fields")
        rest = request.path_params.get("rest", "")
        rows = []
        if rest:
            parts = rest.strip("/").split("/")
            if len(parts) >= 3:
                names = parts[2].split(",")
                wanted = {f"{parts[0]}.{parts[1]}.{n}" for n in names}
                selected = {k: v for k, v in st.ports.items() if k in wanted}
            else:
                selected = st.ports
        else:
            selected = st.ports
        for eid, port in selected.items():
            rows.append({eid: port})
        if len(rows) == 1:
            return JSONResponse({"interface": next(iter(rows[0].values())), "uri": "port"})
        return JSONResponse({"interfaces": rows, "uri": "port"})

    async def get_cx(_: Request) -> JSONResponse:
        payload: dict[str, Any] = {"handler": "candela", "uri": "cx"}
        for name, cx in st.cxs.items():
            payload[name] = cx
        return JSONResponse(payload)

    async def get_endp(_: Request) -> JSONResponse:
        return JSONResponse({"endpoint": [{name: e} for name, e in st.endps.items()], "uri": "endp"})

    async def get_events(_: Request) -> JSONResponse:
        return JSONResponse({"events": [{str(i): e} for i, e in enumerate(st.events)], "uri": "events"})

    async def get_alerts(_: Request) -> JSONResponse:
        return JSONResponse({"alerts": [], "uri": "alerts"})

    async def get_resource(_: Request) -> JSONResponse:
        return JSONResponse(
            {"resources": [{"1.1": {"eid": "1.1", "hostname": "mock-lf", "phantom": False}}]}
        )

    async def get_radiostatus(_: Request) -> JSONResponse:
        return JSONResponse(
            {"radios": [{"1.1.wiphy0": {"eid": "1.1.wiphy0", "driver": "mock80211", "channel": "36"}}]}
        )

    async def get_layer4(_: Request) -> JSONResponse:
        return JSONResponse({"endpoint": [], "uri": "layer4"})

    async def help_cmd(request: Request) -> PlainTextResponse:
        cmd = request.path_params["cmd"]
        return PlainTextResponse(f"<html><body><h1>{cmd}</h1><p>Mock help for {cmd}.</p></body></html>")

    async def cli_json(request: Request) -> JSONResponse:
        cmd = request.path_params["cmd"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        st.commands_received.append({"cmd": cmd, "params": body})

        if cmd == "add_sta":
            eid = f"{body.get('shelf', 1)}.{body.get('resource', 1)}.{body['sta_name']}"
            port = MockState._port(body["sta_name"], "WIFI-STA")
            port["ap"] = "aa:bb:cc:dd:ee:ff"
            port["signal"] = "-45"
            st.ports[eid] = port
            st.add_event(f"Station {body['sta_name']} created")
        elif cmd == "set_port":
            eid = f"{body.get('shelf', 1)}.{body.get('resource', 1)}.{body['port']}"
            if eid in st.ports:
                current = int(body.get("current_flags", 0))
                if current & 0x80000000:  # use_dhcp -> instantly "associate"
                    st.ports[eid]["ip"] = f"10.1.1.{next(st.ip_counter)}"
                st.ports[eid]["down"] = bool(current & 0x1)
        elif cmd == "add_endp":
            st.endps[body["alias"]] = {
                "name": body["alias"],
                "type": body.get("type", "lf_udp"),
                "min_rate": body.get("min_rate", 0),
            }
        elif cmd == "add_cx":
            st.cxs[body["alias"]] = {
                "name": body["alias"],
                "type": "LF/UDP",
                "state": "STOPPED",
                "bps rx a": 0,
                "bps rx b": 0,
                "rx drop % a": 0,
                "rx drop % b": 0,
            }
        elif cmd == "set_cx_state":
            name = body.get("cx_name")
            if name == "all":
                for cx in st.cxs.values():
                    cx["state"] = "STOPPED" if body.get("cx_state") == "STOPPED" else body.get("cx_state")
            elif name in st.cxs:
                state = body.get("cx_state", "STOPPED")
                st.cxs[name]["state"] = "RUN" if state == "RUNNING" else state
                if state == "RUNNING":
                    st.cxs[name]["bps rx a"] = 950_000
                    st.cxs[name]["bps rx b"] = 940_000
            else:
                return JSONResponse({"errors": [f"Could not find CX: {name}"]}, status_code=404)
        elif cmd == "rm_cx":
            if not st.cxs.pop(body.get("cx_name", ""), None):
                return JSONResponse({"errors": ["Could not find that CX."]}, status_code=404)
        elif cmd == "rm_endp":
            st.endps.pop(body.get("endp_name", ""), None)
        elif cmd == "rm_vlan":
            eid = f"{body.get('shelf', 1)}.{body.get('resource', 1)}.{body['port']}"
            if not st.ports.pop(eid, None):
                return JSONResponse({"errors": [f"Port {eid} not found, shelf/resource wrong?"]}, status_code=404)
            st.add_event(f"Port {body['port']} removed")
        elif cmd == "raw":
            line = str(body.get("cmd", ""))
            st.add_event(f"raw: {line}")
            if line.startswith("set_cx_state all all"):
                for cx in st.cxs.values():
                    cx["state"] = "STOPPED"
        elif cmd == "explode":
            return JSONResponse({"errors": ["Unknown command: explode"]}, status_code=400)
        return JSONResponse({"status": "OK", "cmd": cmd})

    routes = [
        Route("/newsession", newsession, methods=["POST"]),
        Route("/", root),
        Route("/port", get_port),
        Route("/port/{rest:path}", get_port),
        Route("/cx", get_cx),
        Route("/endp", get_endp),
        Route("/events", get_events),
        Route("/alerts", get_alerts),
        Route("/resource", get_resource),
        Route("/radiostatus", get_radiostatus),
        Route("/layer4", get_layer4),
        Route("/help/{cmd}", help_cmd),
        Route("/cli-json/{cmd}", cli_json, methods=["POST"]),
    ]
    return Starlette(routes=routes), st
