#!/usr/bin/env python3
"""Parse a sitespeed.io baseline directory into populated TEMPLATE.md rows.

Walks docs/perf-baselines/<date>-<sha>/ for cells named
`s<N>-<probe>-<device>/`, reads the sitespeed.io HAR inside each cell, and
prints a markdown table section per scenario that can be pasted into
TEMPLATE.md.

Everything we need is inside the HAR: sitespeed.io embeds `pageTimings`
(FCP/LCP/TTI) and `_googleWebVitals` (CLS/TTFB/FID/TBT) on the first page
entry, so we don't need a separate `browsertime.json` — it's not written
to disk by default in v39+ anyway.

Usage:
    python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/2026-04-24-abc1234
    python scripts/analyze_baseline.py --baseline-dir ... --output-format json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import zipfile
from pathlib import Path
from typing import Any


CELL_RE = re.compile(r"^s(\d)-(.+)-(desktop|mobile)$")

SCENARIO_TITLES = {
    "s1": "S1 — Cold first load, Today page (via login)",
    "s2": "S2 — Cold first load, Training page (via login)",
    "s3": "S3 — Warm repeat visit, Today page",
    "s4": "S4 — Anonymous Landing page",
}

COLUMNS = [
    ("fcp_ms", "FCP (ms)"),
    ("lcp_ms", "LCP (ms)"),
    ("tti_ms", "TTI (ms)"),
    ("ttfb_ms", "HTML TTFB"),
    ("static_kb", "Static KB"),
    ("api_kb", "API KB"),
    ("num_requests", "# reqs"),
    ("num_api", "# API"),
    ("api_p50_ms", "API p50"),
    ("api_p95_ms", "API p95"),
    ("protocol", "Protocol"),
    ("font_css_ttfb", "Font CSS TTFB"),
]


def find_har(cell_dir: Path) -> Path | None:
    paths = list(cell_dir.rglob("browsertime.har")) + list(cell_dir.rglob("browsertime.har.zip"))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def load_har(har_path: Path) -> dict[str, Any]:
    if har_path.suffix == ".zip":
        with zipfile.ZipFile(har_path) as z:
            inner = next((n for n in z.namelist() if n.endswith(".har")), None)
            if inner is None:
                raise ValueError(f"No .har file inside {har_path}")
            with z.open(inner) as f:
                return json.load(f)
    with har_path.open(encoding="utf-8") as f:
        return json.load(f)


def extract_metrics(cell_dir: Path) -> dict[str, Any] | None:
    har_path = find_har(cell_dir)
    if har_path is None:
        return None
    har = load_har(har_path)
    log = har.get("log", {})
    pages = log.get("pages", [])
    entries = log.get("entries", [])

    page = pages[0] if pages else {}
    page_timings = page.get("pageTimings", {}) or {}
    gwv = page.get("_googleWebVitals", {}) or {}

    # Sitespeed.io underscores internal fields in the HAR; stable public
    # names live on _googleWebVitals. Fall back between them for safety.
    fcp = gwv.get("firstContentfulPaint") or page_timings.get("_firstContentfulPaint")
    lcp = gwv.get("largestContentfulPaint") or page_timings.get("_largestContentfulPaint")
    # TTI isn't a HAR field — use domInteractiveTime as the closest proxy.
    tti = page_timings.get("_domInteractiveTime")
    ttfb = gwv.get("ttfb")
    num_requests = len(entries)
    api_entries = [e for e in entries if "/api/" in (e.get("request") or {}).get("url", "")]
    num_api = len(api_entries)

    static_bytes = 0
    api_bytes = 0
    for e in entries:
        url = (e.get("request") or {}).get("url", "")
        size = ((e.get("response") or {}).get("content") or {}).get("size") or 0
        transferred = (e.get("response") or {}).get("bodySize")
        if transferred is None or transferred < 0:
            transferred = size
        if "/api/" in url:
            api_bytes += max(0, transferred)
        else:
            static_bytes += max(0, transferred)

    api_durations = []
    for e in api_entries:
        t = e.get("timings") or {}
        wait = t.get("wait") or 0
        receive = t.get("receive") or 0
        if wait >= 0 and receive >= 0:
            api_durations.append(wait + receive)
    api_p50 = statistics.median(api_durations) if api_durations else None
    api_p95: float | None = None
    if len(api_durations) >= 2:
        qs = statistics.quantiles(api_durations, n=20, method="inclusive")
        api_p95 = qs[-1]
    elif api_durations:
        api_p95 = api_durations[0]

    protocols = {((e.get("response") or {}).get("httpVersion") or "").lower() for e in entries}
    protocols.discard("")
    if any("3" in p for p in protocols):
        protocol: Any = "h3"
    elif any("2" in p for p in protocols):
        protocol = "h2"
    elif protocols:
        protocol = sorted(protocols)[0]
    else:
        protocol = "?"

    font_css_ttfb: Any = None
    for e in entries:
        url = (e.get("request") or {}).get("url", "")
        if "fonts.googleapis.com" in url:
            t = e.get("timings") or {}
            wait = t.get("wait")
            if wait is None or wait < 0:
                font_css_ttfb = "timeout"
            else:
                font_css_ttfb = round(wait)
            break

    # Zero is meaningful signal here, not missing data: S4 (anonymous
    # Landing) legitimately has 0 API requests / 0 API KB, and that's
    # what tells us the anonymous route isn't calling /api/*. So render
    # zeros as 0, not em-dash.
    return {
        "fcp_ms": round(fcp) if fcp is not None else None,
        "lcp_ms": round(lcp) if lcp is not None else None,
        "tti_ms": round(tti) if tti is not None else None,
        "ttfb_ms": round(ttfb) if ttfb is not None else None,
        "static_kb": round(static_bytes / 1024, 1),
        "api_kb": round(api_bytes / 1024, 1),
        "num_requests": num_requests,
        "num_api": num_api,
        "api_p50_ms": round(api_p50) if api_p50 is not None else None,
        "api_p95_ms": round(api_p95) if api_p95 is not None else None,
        "protocol": protocol,
        "font_css_ttfb": font_css_ttfb,
    }


def render_markdown(results: dict[str, dict[str, Any] | None]) -> str:
    by_scenario: dict[str, list[tuple[str, str, dict[str, Any] | None]]] = {}
    for cell_name, metrics in results.items():
        m = CELL_RE.match(cell_name)
        assert m is not None
        scenario = f"s{m.group(1)}"
        probe = m.group(2)
        device = m.group(3).capitalize()
        by_scenario.setdefault(scenario, []).append((probe, device, metrics))

    header = "| Probe | Device | " + " | ".join(label for _, label in COLUMNS) + " |"
    separator = "|" + "---|" * (len(COLUMNS) + 2)

    out: list[str] = []
    for scenario in sorted(by_scenario):
        title = SCENARIO_TITLES.get(scenario, scenario.upper())
        out.append(f"### {title}\n")
        out.append(header)
        out.append(separator)
        for probe, device, metrics in by_scenario[scenario]:
            cells: list[str] = []
            for key, _ in COLUMNS:
                v = metrics.get(key) if metrics else None
                cells.append("—" if v is None else str(v))
            out.append(f"| {probe} | {device} | " + " | ".join(cells) + " |")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", required=True, type=Path)
    parser.add_argument("--output-format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    baseline_dir: Path = args.baseline_dir
    if not baseline_dir.is_dir():
        print(f"Error: baseline dir not found: {baseline_dir}", file=sys.stderr)
        return 1

    cells = sorted(p for p in baseline_dir.iterdir() if p.is_dir() and CELL_RE.match(p.name))
    if not cells:
        print(
            f"Error: no cell directories matching s<N>-<probe>-<desktop|mobile> in {baseline_dir}",
            file=sys.stderr,
        )
        return 1

    results: dict[str, dict[str, Any] | None] = {}
    for cell in cells:
        results[cell.name] = extract_metrics(cell)

    if args.output_format == "json":
        print(json.dumps(results, indent=2))
    else:
        print(render_markdown(results))

    missing = [name for name, v in results.items() if v is None]
    if missing:
        print(
            f"\nWarning: no sitespeed.io output found in {len(missing)} cell(s): {', '.join(missing)}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
