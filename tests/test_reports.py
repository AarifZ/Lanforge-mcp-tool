"""Report engine: statistics, AI summaries, file rendering."""

from __future__ import annotations

import json
from pathlib import Path

from lanforge_mcp.models import ReportsConfig
from lanforge_mcp.reports.engine import ReportEngine, summarize_samples

SAMPLES = [
    {"t": "t0", "rows": [{"eid": "cx-1", "bps rx a": "1000", "state": "RUN"}]},
    {"t": "t1", "rows": [{"eid": "cx-1", "bps rx a": "3000", "state": "RUN"}]},
    {"t": "t2", "rows": [{"eid": "cx-1", "bps rx a": "2000", "state": "RUN"}]},
]


def test_to_float_accepts_lanforge_units():
    from lanforge_mcp.reports.engine import _to_float

    assert _to_float("-31 dBm") == -31.0
    assert _to_float("80 MHz") == 80.0
    assert _to_float("97%") == 97.0
    assert _to_float("3.25 Gbps") == 3.25
    assert _to_float("1000") == 1000.0
    # Identifier-like strings must NOT parse (they'd pollute report stats).
    assert _to_float("1.1.eth0") is None
    assert _to_float("802.11an-BE 80 2x2") is None
    assert _to_float(True) is None


def test_summarize_samples():
    stats = summarize_samples(SAMPLES)
    s = stats["cx-1"]["bps rx a"]
    assert s["min"] == 1000 and s["max"] == 3000 and s["avg"] == 2000 and s["n"] == 3


def test_generate_all_formats(tmp_path):
    engine = ReportEngine(ReportsConfig(output_dir=str(tmp_path)))
    result = engine.generate("L3 test", {"samples": SAMPLES})
    assert set(result["files"]) == {"markdown", "html", "json"}
    md = Path(result["files"]["markdown"]).read_text(encoding="utf-8")
    assert "# L3 test" in md and "bps rx a" in md
    html = Path(result["files"]["html"]).read_text(encoding="utf-8")
    assert "<h1>L3 test</h1>" in html
    payload = json.loads(Path(result["files"]["json"]).read_text(encoding="utf-8"))
    assert payload["ai_summary"]
    assert any("bps rx a" in line for line in result["ai_summary"])


def test_generate_from_plain_rows(tmp_path):
    engine = ReportEngine(ReportsConfig(output_dir=str(tmp_path)))
    result = engine.generate("Table", [{"eid": "1.1.sta0", "ip": "10.0.0.5"}], formats=["markdown"])
    md = Path(result["files"]["markdown"]).read_text(encoding="utf-8")
    assert "10.0.0.5" in md


def test_compare_samples():
    from lanforge_mcp.diagnostics.analyzer import Diagnostics

    before = {"samples": SAMPLES}
    after = {
        "samples": [
            {"t": "t0", "rows": [{"eid": "cx-1", "bps rx a": "4000"}]},
            {"t": "t1", "rows": [{"eid": "cx-1", "bps rx a": "4000"}]},
        ]
    }
    result = Diagnostics.compare_samples(before, after)
    top = result["top_changes"][0]
    assert top["metric"] == "bps rx a"
    assert top["change_pct"] == 100.0
