"""Diagnostic analyzers.

Read-only helpers that turn raw LANforge tables into judgments an operator
would make: which stations are unhealthy and why, which connections are not
passing traffic, what disconnect/roam patterns show up in the event log, and
how two throughput samples compare.
"""

from __future__ import annotations

import logging
from typing import Any

from ..api.json_api import JsonApi
from ..reports.engine import _to_float, summarize_samples

logger = logging.getLogger(__name__)

LOW_RSSI_DBM = -75.0


def _f(row: dict[str, Any], *names: str) -> Any:
    """First present field among aliases (LANforge column names vary by version)."""
    for n in names:
        if n in row:
            return row[n]
    return None


class Diagnostics:
    def __init__(self, api: JsonApi):
        self.api = api

    async def health_check(self) -> dict[str, Any]:
        """Overall system health: resources, phantom ports, alerts."""
        issues: list[str] = []
        out: dict[str, Any] = {"ok": True}

        resources = await self.api.query("resource")
        down = [
            r.get("eid") or r.get("hostname")
            for r in resources["rows"]
            if str(_f(r, "phantom")).lower() == "true"
        ]
        out["resources_total"] = resources["row_count"]
        if down:
            issues.append(f"{len(down)} resource(s) phantom/offline: {down}")

        ports = await self.api.query("port", columns=["alias", "phantom", "down", "ip"])
        phantom_ports = [p.get("eid") for p in ports["rows"] if str(_f(p, "phantom")).lower() == "true"]
        out["ports_total"] = ports["row_count"]
        if phantom_ports:
            issues.append(f"{len(phantom_ports)} phantom port(s): {phantom_ports[:20]}")

        try:
            alerts = await self.api.query("alerts")
            active = alerts["rows"]
            if active:
                issues.append(f"{len(active)} active alert(s); first: {active[0]}")
            out["alerts"] = len(active)
        except Exception:
            out["alerts"] = "unavailable"

        out["ok"] = not issues
        out["issues"] = issues
        return out

    async def diagnose_stations(self, eids: list[str] | None = None) -> dict[str, Any]:
        """Per-station health with a human-readable reason for each problem."""
        q = await self.api.query("port", eids=eids)
        stations = [
            r for r in q["rows"]
            if str(_f(r, "port type", "port_type", "type") or "").lower() in ("wifi-sta", "sta", "station")
            or str(r.get("alias", "")).startswith("sta")
        ]
        healthy, problems = [], []
        for s in stations:
            eid = s.get("eid") or s.get("alias")
            reasons = []
            if str(_f(s, "phantom")).lower() == "true":
                reasons.append("phantom: no hardware backing this port")
            if str(_f(s, "down")).lower() == "true":
                reasons.append("admin down")
            ip = str(_f(s, "ip") or "0.0.0.0")
            if ip in ("0.0.0.0", ""):
                reasons.append("no IP address (DHCP not complete or not associated)")
            ap = str(_f(s, "ap") or "")
            if ap in ("", "Not-Associated", "NA"):
                reasons.append("not associated to any AP")
            rssi = _to_float(_f(s, "signal", "rssi", "avg chain rssi"))
            if rssi is not None and rssi < LOW_RSSI_DBM:
                reasons.append(f"weak signal ({rssi:g} dBm < {LOW_RSSI_DBM:g} dBm)")
            entry = {
                "station": eid,
                "ip": ip,
                "ap": ap,
                "signal": _f(s, "signal", "rssi"),
                "channel": _f(s, "channel"),
                "mode": _f(s, "mode"),
            }
            if reasons:
                problems.append({**entry, "problems": reasons})
            else:
                healthy.append(entry)
        return {
            "stations_total": len(stations),
            "healthy": len(healthy),
            "failed": len(problems),
            "failed_stations": problems,
            "healthy_stations": healthy[:50],
        }

    async def diagnose_traffic(self) -> dict[str, Any]:
        """Find cross-connects that exist but aren't moving traffic properly."""
        q = await self.api.query("cx")
        findings = []
        for cx in q["rows"]:
            name = cx.get("name") or cx.get("eid")
            state = str(_f(cx, "state") or "")
            bps_rx_a = _to_float(_f(cx, "bps rx a", "bps_rx_a")) or 0.0
            bps_rx_b = _to_float(_f(cx, "bps rx b", "bps_rx_b")) or 0.0
            drops_a = _to_float(_f(cx, "rx drop % a", "rx_drop_%_a")) or 0.0
            drops_b = _to_float(_f(cx, "rx drop % b", "rx_drop_%_b")) or 0.0
            issues = []
            if state.upper() == "RUN" or state.upper() == "RUNNING":
                if bps_rx_a == 0 and bps_rx_b == 0:
                    issues.append("running but zero throughput both directions")
                elif bps_rx_a == 0 or bps_rx_b == 0:
                    issues.append("running but one direction has zero throughput")
            if max(drops_a, drops_b) > 1.0:
                issues.append(f"packet drops {max(drops_a, drops_b):g}%")
            if issues:
                findings.append(
                    {"cx": name, "state": state, "bps_rx_a": bps_rx_a, "bps_rx_b": bps_rx_b,
                     "issues": issues}
                )
        return {"cx_total": q["row_count"], "problem_count": len(findings), "problems": findings}

    async def analyze_events(self, last: int = 200, keyword: str = "") -> dict[str, Any]:
        """Group recent event-log entries into disconnect/roam/DHCP patterns."""
        q = await self.api.query("events")
        rows = q["rows"][-last:]
        buckets: dict[str, list[dict[str, Any]]] = {}
        patterns = {
            "disconnect": ("disconnect", "deauth", "disassoc", "link down"),
            "connect": ("connect", "associated", "link up"),
            "roam": ("roam",),
            "dhcp": ("dhcp",),
            "dfs_radar": ("dfs", "radar"),
            "error": ("error", "fail"),
        }
        needle = keyword.lower()
        for row in rows:
            text = " ".join(str(v) for v in row.values()).lower()
            if needle and needle not in text:
                continue
            for bucket, keys in patterns.items():
                if any(k in text for k in keys):
                    buckets.setdefault(bucket, []).append(
                        {k: row.get(k) for k in ("time", "time-stamp", "event description",
                                                 "event_description", "name", "entity id") if k in row}
                    )
                    break
        return {
            "events_scanned": len(rows),
            "pattern_counts": {k: len(v) for k, v in buckets.items()},
            "samples": {k: v[-5:] for k, v in buckets.items()},
        }

    @staticmethod
    def compare_samples(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """Compare two 'sample' step outputs (e.g. yesterday vs today)."""
        stats_a = summarize_samples(before.get("samples", []))
        stats_b = summarize_samples(after.get("samples", []))
        deltas = []
        for entity in sorted(set(stats_a) & set(stats_b)):
            for metric in sorted(set(stats_a[entity]) & set(stats_b[entity])):
                a, b = stats_a[entity][metric]["avg"], stats_b[entity][metric]["avg"]
                if a == 0 and b == 0:
                    continue
                change = ((b - a) / abs(a) * 100) if a else float("inf")
                deltas.append(
                    {"entity": entity, "metric": metric, "before_avg": a, "after_avg": b,
                     "change_pct": round(change, 1)}
                )
        deltas.sort(key=lambda d: abs(d["change_pct"]), reverse=True)
        return {"compared_entities": len(set(stats_a) & set(stats_b)), "top_changes": deltas[:25]}
