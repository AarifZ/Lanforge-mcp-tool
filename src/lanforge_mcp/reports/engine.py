"""Layer 6 — the report engine.

Takes data collected by workflows/monitoring (time-series samples, tables,
key-value blobs) and produces Markdown, standalone HTML (PDF-ready), and JSON.
Every report leads with an *AI summary*: computed min/avg/max/first/last per
numeric metric so an LLM can reason about results without re-parsing tables.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import ReportsConfig

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")

#: Row fields that identify a row rather than measure something.
_ID_FIELDS = ("eid", "name", "alias", "port", "entity id")


def _slug(title: str) -> str:
    return _SLUG_RE.sub("-", title.lower()).strip("-")[:60] or "report"


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _row_key(row: dict[str, Any]) -> str:
    for f in _ID_FIELDS:
        if row.get(f):
            return str(row[f])
    return "row"


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn [{t, rows:[...]}, ...] into per-entity per-metric statistics."""
    series: dict[str, dict[str, list[float]]] = {}
    for sample in samples:
        for row in sample.get("rows", []):
            key = _row_key(row)
            for field_name, value in row.items():
                num = _to_float(value)
                if num is None:
                    continue
                series.setdefault(key, {}).setdefault(field_name, []).append(num)
    stats: dict[str, Any] = {}
    for key, metrics in series.items():
        stats[key] = {}
        for metric, values in metrics.items():
            # Constant columns (ids, config) add noise; keep only real movement,
            # but always keep zero-vs-nonzero info for rates.
            if all(v == values[0] for v in values) and (not values or values[0] == 0.0):
                continue
            stats[key][metric] = {
                "min": min(values),
                "max": max(values),
                "avg": round(sum(values) / len(values), 3),
                "first": values[0],
                "last": values[-1],
                "n": len(values),
            }
    return stats


def _ai_summary_lines(stats: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    interesting = ("bps", "rate", "rx", "tx", "drop", "latency", "rtt", "signal", "retr")
    for entity, metrics in stats.items():
        picked = {
            m: s for m, s in metrics.items() if any(k in m.lower() for k in interesting)
        }
        for metric, s in list(picked.items())[:6]:
            lines.append(
                f"{entity} · {metric}: avg {s['avg']:g}, min {s['min']:g}, max {s['max']:g} (n={s['n']})"
            )
    if not lines:
        lines.append("No time-varying numeric metrics detected in the collected data.")
    return lines


class ReportEngine:
    def __init__(self, config: ReportsConfig):
        self.config = config

    # ----------------------------------------------------------------- public

    def generate(
        self,
        title: str,
        data: Any,
        formats: list[str] | None = None,
    ) -> dict[str, Any]:
        """Render ``data`` into the requested formats; returns files + summary."""
        formats = formats or ["markdown", "html", "json"]
        now = datetime.now(UTC)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        out_dir = Path(self.config.output_dir).expanduser() / f"{stamp}-{_slug(title)}"
        out_dir.mkdir(parents=True, exist_ok=True)

        sections = self._build_sections(data)
        stats = sections.get("stats", {})
        summary_lines = _ai_summary_lines(stats) if stats else ["No sampled metrics in this report."]

        files: dict[str, str] = {}
        if "json" in formats:
            payload = {
                "title": title,
                "generated_at": now.isoformat(),
                "ai_summary": summary_lines,
                "stats": stats,
                "data": data,
            }
            path = out_dir / "report.json"
            path.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
            files["json"] = str(path)
        if "markdown" in formats:
            path = out_dir / "report.md"
            path.write_text(self._render_markdown(title, now, summary_lines, sections), encoding="utf-8")
            files["markdown"] = str(path)
        if "html" in formats:
            path = out_dir / "report.html"
            path.write_text(self._render_html(title, now, summary_lines, sections), encoding="utf-8")
            files["html"] = str(path)

        return {
            "title": title,
            "generated_at": now.isoformat(),
            "files": files,
            "ai_summary": summary_lines,
            "stats_entities": list(stats),
        }

    # --------------------------------------------------------------- sections

    def _build_sections(self, data: Any) -> dict[str, Any]:
        sections: dict[str, Any] = {}
        if isinstance(data, dict) and isinstance(data.get("samples"), list):
            sections["stats"] = summarize_samples(data["samples"])
            sections["sample_count"] = len(data["samples"])
            last = data["samples"][-1] if data["samples"] else {}
            sections["final_table"] = last.get("rows", [])
        elif isinstance(data, dict) and isinstance(data.get("rows"), list):
            sections["final_table"] = data["rows"]
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            sections["final_table"] = data
        else:
            sections["blob"] = data
        return sections

    # -------------------------------------------------------------- markdown

    def _render_markdown(
        self, title: str, now: datetime, summary: list[str], sections: dict[str, Any]
    ) -> str:
        out = [f"# {title}", "", f"Generated: {now.isoformat()}", "", "## AI summary", ""]
        out += [f"- {line}" for line in summary]
        stats = sections.get("stats")
        if stats:
            out += ["", "## Metric statistics", ""]
            out += ["| Entity | Metric | Min | Avg | Max | First | Last | Samples |",
                    "|---|---|---|---|---|---|---|---|"]
            for entity, metrics in stats.items():
                for metric, s in metrics.items():
                    out.append(
                        f"| {entity} | {metric} | {s['min']:g} | {s['avg']:g} | {s['max']:g} "
                        f"| {s['first']:g} | {s['last']:g} | {s['n']} |"
                    )
        table = sections.get("final_table")
        if table:
            out += ["", "## Final state", ""]
            cols = self._table_columns(table)
            out.append("| " + " | ".join(cols) + " |")
            out.append("|" + "---|" * len(cols))
            for row in table[:100]:
                out.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        if "blob" in sections:
            out += ["", "## Data", "", "```json", json.dumps(sections["blob"], indent=1, default=str)[:8000], "```"]
        out.append("")
        return "\n".join(out)

    # ------------------------------------------------------------------ html

    def _render_html(
        self, title: str, now: datetime, summary: list[str], sections: dict[str, Any]
    ) -> str:
        esc = html_mod.escape
        parts = [
            "<meta charset='utf-8'>",
            "<style>",
            "body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:60rem;color:#111}",
            "h1{border-bottom:2px solid #0a6;padding-bottom:.3rem}",
            "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.9rem}",
            "th,td{border:1px solid #ccc;padding:.35rem .5rem;text-align:left}",
            "th{background:#f0f6f3}",
            ".summary{background:#f6fbf8;border-left:4px solid #0a6;padding:.8rem 1rem}",
            "@media print{body{margin:0}}",
            "</style>",
            f"<title>{esc(title)}</title>",
            f"<h1>{esc(title)}</h1>",
            f"<p>Generated: {esc(now.isoformat())}</p>",
            "<div class='summary'><strong>AI summary</strong><ul>",
        ]
        parts += [f"<li>{esc(line)}</li>" for line in summary]
        parts.append("</ul></div>")
        stats = sections.get("stats")
        if stats:
            parts.append("<h2>Metric statistics</h2><table><tr><th>Entity</th><th>Metric</th>"
                         "<th>Min</th><th>Avg</th><th>Max</th><th>First</th><th>Last</th><th>N</th></tr>")
            for entity, metrics in stats.items():
                for metric, s in metrics.items():
                    parts.append(
                        f"<tr><td>{esc(entity)}</td><td>{esc(metric)}</td><td>{s['min']:g}</td>"
                        f"<td>{s['avg']:g}</td><td>{s['max']:g}</td><td>{s['first']:g}</td>"
                        f"<td>{s['last']:g}</td><td>{s['n']}</td></tr>"
                    )
            parts.append("</table>")
        table = sections.get("final_table")
        if table:
            cols = self._table_columns(table)
            parts.append("<h2>Final state</h2><table><tr>")
            parts += [f"<th>{esc(c)}</th>" for c in cols]
            parts.append("</tr>")
            for row in table[:100]:
                parts.append("<tr>" + "".join(f"<td>{esc(str(row.get(c, '')))}</td>" for c in cols) + "</tr>")
            parts.append("</table>")
        if "blob" in sections:
            parts.append(
                "<h2>Data</h2><pre>"
                + esc(json.dumps(sections["blob"], indent=1, default=str)[:8000])
                + "</pre>"
            )
        return "\n".join(parts)

    @staticmethod
    def _table_columns(table: list[dict[str, Any]], limit: int = 12) -> list[str]:
        """Pick a stable, id-first subset of columns for display."""
        seen: list[str] = []
        for row in table[:20]:
            for key in row:
                if key not in seen:
                    seen.append(key)
        ids = [c for c in seen if c in _ID_FIELDS]
        rest = [c for c in seen if c not in _ID_FIELDS]
        return (ids + rest)[:limit]
