"""Drive synthetic API load and report before/after server-side latency.

Why this exists: the Praxys app has very low organic traffic (~3
``/api/today`` calls per day), so percentile-based latency moves can take
days to surface in App Insights after a perf change. This script
generates a controlled burst of read-only requests against the live app
using the public demo account, waits for telemetry ingestion, then runs
the same KQL the pre-change profile used and prints a side-by-side
comparison.

Usage::

    .venv/Scripts/python.exe scripts/perf_synthetic_load_check.py

Optional env vars (all have safe defaults):

    PRAXYS_PERF_BASE_URL   default: https://trainsight-app.azurewebsites.net
                                    (the App Service origin — bypasses
                                    the SWA proxy on www.praxys.run,
                                    which doesn't forward POSTs)
    PRAXYS_PERF_USER       default: demo@trainsight.dev
    PRAXYS_PERF_PASSWORD   default: demo
    PRAXYS_PERF_N          default: 30  (calls per endpoint)
    PRAXYS_PERF_PAUSE_MS   default: 200  (between requests)
    PRAXYS_PERF_INGEST_S   default: 120  (App Insights ingestion lag)
    PRAXYS_PERF_BASELINE_DAYS   default: 7  (lookback window for "before")
    PRAXYS_PERF_MODE       default: both
                                    "cold" runs the historical 200-only burst.
                                    "warm" runs the L2 ETag-revalidation burst:
                                    issue one cold call per endpoint to capture
                                    the ``ETag``, then replay it as
                                    ``If-None-Match`` for the remaining N-1 calls.
                                    "both" runs cold first, then warm, in
                                    sequence. The App Insights summary slices
                                    by status code so 200 (cold) and 304
                                    (warm) get separate p50/p95.

Reads the workspace customer-id and tenant via the local az CLI cache,
so no secrets in env vars. The demo account is read-only and (per
api/auth.py:62) proxies to the admin's data, so the queries hit the
same SQLite tables and row counts a real user request would.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests


WORKSPACE_GUID = "cc14473b-35d9-44f0-b8a7-7d4e9a06917a"  # log-trainsight
ENDPOINTS = ["/api/today", "/api/training", "/api/science"]


@dataclass
class ClientSample:
    endpoint: str
    duration_ms: float
    status: int
    phase: str = "cold"  # "cold" | "warm" — kept on the sample so multi-phase
                         # runs can be summarized without re-correlating times.


def _login(base_url: str, email: str, password: str) -> str:
    r = requests.post(
        f"{base_url}/api/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _drive_cold(base_url: str, token: str, n: int, pause_ms: int) -> list[ClientSample]:
    """N requests per endpoint with no ``If-None-Match`` — full pack execution."""
    headers = {"Authorization": f"Bearer {token}"}
    samples: list[ClientSample] = []
    total = n * len(ENDPOINTS)
    done = 0
    for endpoint in ENDPOINTS:
        for _ in range(n):
            t0 = time.monotonic()
            try:
                r = requests.get(f"{base_url}{endpoint}", headers=headers, timeout=60)
                samples.append(ClientSample(
                    endpoint=endpoint,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    status=r.status_code,
                    phase="cold",
                ))
            except requests.RequestException as e:
                samples.append(ClientSample(endpoint=endpoint, duration_ms=-1, status=0, phase="cold"))
                print(f"  request failed: {e}", file=sys.stderr)
            done += 1
            print(f"  {done}/{total}  cold {endpoint}  {samples[-1].duration_ms:.0f}ms", flush=True)
            time.sleep(pause_ms / 1000)
    return samples


def _drive_warm(base_url: str, token: str, n: int, pause_ms: int) -> list[ClientSample]:
    """One cold call per endpoint to capture ``ETag``, then N-1 warm calls
    carrying ``If-None-Match: <etag>``.

    Mirrors what a returning browser does on every navigation after its
    initial cold paint: the browser caches the body and keys it on the
    ETag, then includes ``If-None-Match`` on the next visit. With L2 the
    server short-circuits to 304 + zero body, so the timing here measures
    "ETag dependency + SELECT cache_revisions + blake2b" — not pack
    execution. A 200 response in this phase is the L2 invariant violator
    we want to know about: it means a write between the cold capture and
    the warm replay flipped the ETag (or the dependency wasn't reached).
    """
    base_headers = {"Authorization": f"Bearer {token}"}
    samples: list[ClientSample] = []
    total = n * len(ENDPOINTS)
    done = 0
    for endpoint in ENDPOINTS:
        # Capture ETag with one cold call. Don't time this one — it's
        # paid by the cold burst already, so including it in warm samples
        # would double-count the pack-execution cost.
        try:
            cold = requests.get(
                f"{base_url}{endpoint}", headers=base_headers, timeout=60,
            )
        except requests.RequestException as e:
            print(f"  warm: ETag-capture call for {endpoint} failed: {e}", file=sys.stderr)
            done += n
            continue
        etag = cold.headers.get("ETag")
        if not etag:
            print(
                f"  warm: {endpoint} returned no ETag header (status {cold.status_code}) "
                f"— skipping warm phase for this endpoint",
                file=sys.stderr,
            )
            done += n
            continue

        warm_headers = {**base_headers, "If-None-Match": etag}
        # The warm burst issues N requests so its sample size matches the
        # cold burst exactly — keeps the p50/p95 percentiles directly
        # comparable.
        for _ in range(n):
            t0 = time.monotonic()
            try:
                r = requests.get(
                    f"{base_url}{endpoint}", headers=warm_headers, timeout=60,
                )
                samples.append(ClientSample(
                    endpoint=endpoint,
                    duration_ms=(time.monotonic() - t0) * 1000,
                    status=r.status_code,
                    phase="warm",
                ))
            except requests.RequestException as e:
                samples.append(ClientSample(endpoint=endpoint, duration_ms=-1, status=0, phase="warm"))
                print(f"  request failed: {e}", file=sys.stderr)
            done += 1
            print(
                f"  {done}/{total}  warm {endpoint}  "
                f"{samples[-1].duration_ms:.0f}ms  HTTP {samples[-1].status}",
                flush=True,
            )
            time.sleep(pause_ms / 1000)
    return samples


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * (pct / 100)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def _client_summary(
    samples: list[ClientSample], phase: str, status: int = 200,
) -> dict[str, dict[str, float]]:
    """Bucket samples by endpoint for one (phase, status) slice.

    Cold phase reports the 200 slice (the only outcome under L1). Warm phase
    reports the 304 slice — the L2 short-circuit. A 200 in the warm phase
    is reported separately as an invariant violator (a write between the
    cold capture and the warm replay flipped the ETag).
    """
    out: dict[str, dict[str, float]] = {}
    for ep in ENDPOINTS:
        ds = [
            s.duration_ms for s in samples
            if s.endpoint == ep and s.phase == phase and s.status == status
        ]
        if not ds:
            out[ep] = {"n": 0}
            continue
        out[ep] = {
            "n": len(ds),
            "p50": _percentile(ds, 50),
            "p95": _percentile(ds, 95),
            "p99": _percentile(ds, 99),
            "mean": statistics.mean(ds),
        }
    return out


def _run_kql(query: str) -> list[dict]:
    """Run a KQL query against log-trainsight and return rows.

    Uses ``shell=True`` because ``az`` is a ``.cmd`` shim on Windows that
    Python's subprocess won't resolve through PATHEXT without it. On Linux
    / mac this is also fine — the shell just locates the binary.
    """
    cmd_str = (
        f'az monitor log-analytics query '
        f'--workspace {WORKSPACE_GUID} '
        f'--analytics-query "{query.replace(chr(34), chr(92) + chr(34))}" '
        f'--timespan P14D -o json'
    )
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    result = subprocess.run(
        cmd_str, capture_output=True, text=True, env=env, timeout=60, shell=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"az query failed: {result.stderr}")
    return json.loads(result.stdout)


def _server_window_summary(start: datetime, end: datetime) -> list[dict]:
    """Server-side p50/p95/p99 from App Insights for the synthetic-load window.

    Slices by ResultCode so 200 (cold) and 304 (warm) get separate rows.
    Pre-L2 there were no 304s so the prior single-row-per-endpoint shape
    is preserved on those endpoints; post-L2 each endpoint produces two
    rows when both phases ran.
    """
    start_iso = start.isoformat()
    end_iso = end.isoformat()
    query = f"""
        AppRequests
        | where TimeGenerated between (datetime({start_iso}) .. datetime({end_iso}))
        | where Name in ("GET /api/today", "GET /api/training", "GET /api/science")
        | summarize n=count(),
                    p50=percentile(DurationMs, 50),
                    p95=percentile(DurationMs, 95),
                    p99=percentile(DurationMs, 99),
                    maxMs=max(DurationMs)
                  by Name, ResultCode
        | order by Name asc, ResultCode asc
    """
    return _run_kql(query)


def _server_baseline_summary(days: int, burst_start: datetime) -> list[dict]:
    """Server-side baseline over the last N days, ending strictly before
    this run's burst. Earlier versions used ``< ago(30m)`` for the upper
    bound, but a burst takes <1 min plus ingestion lag — re-running this
    script within 30 min of a previous run would let the prior burst
    contaminate the "before" baseline and silently understate the delta.
    Anchoring on ``burst_start`` instead is exact.
    """
    query = f"""
        AppRequests
        | where TimeGenerated > ago({days}d)
              and TimeGenerated < datetime({burst_start.isoformat()})
        | where Name in ("GET /api/today", "GET /api/training", "GET /api/science")
        | summarize n=count(),
                    p50=percentile(DurationMs, 50),
                    p95=percentile(DurationMs, 95),
                    p99=percentile(DurationMs, 99),
                    maxMs=max(DurationMs)
                  by Name, ResultCode
        | order by Name asc, ResultCode asc
    """
    return _run_kql(query)


def _print_table(title: str, rows: list[dict]) -> None:
    print(f"\n{title}")
    print(f"  {'endpoint':<22} {'code':>4} {'n':>4} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8}")
    print(f"  {'-'*22} {'-'*4} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for r in rows:
        code = r.get("ResultCode", "?")
        print(f"  {r['Name']:<22} {str(code):>4} {int(float(r['n'])):>4} "
              f"{float(r['p50']):>7.0f}ms {float(r['p95']):>7.0f}ms "
              f"{float(r['p99']):>7.0f}ms {float(r['maxMs']):>7.0f}ms")


def _print_client_summary(title: str, summary: dict[str, dict[str, float]]) -> None:
    print(f"\n  {title}")
    print(f"  {'endpoint':<22} {'n':>4} {'p50':>8} {'p95':>8} {'p99':>8} {'mean':>8}")
    print(f"  {'-'*22} {'-'*4} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for ep, s in summary.items():
        if s.get("n", 0) == 0:
            print(f"  {ep:<22} (none)")
            continue
        print(f"  {ep:<22} {s['n']:>4} {s['p50']:>7.0f}ms {s['p95']:>7.0f}ms "
              f"{s['p99']:>7.0f}ms {s['mean']:>7.0f}ms")


def main() -> int:
    base = os.environ.get("PRAXYS_PERF_BASE_URL", "https://trainsight-app.azurewebsites.net")
    user = os.environ.get("PRAXYS_PERF_USER", "demo@trainsight.dev")
    pwd = os.environ.get("PRAXYS_PERF_PASSWORD", "demo")
    n = int(os.environ.get("PRAXYS_PERF_N", "30"))
    pause_ms = int(os.environ.get("PRAXYS_PERF_PAUSE_MS", "200"))
    ingest_s = int(os.environ.get("PRAXYS_PERF_INGEST_S", "120"))
    baseline_days = int(os.environ.get("PRAXYS_PERF_BASELINE_DAYS", "7"))
    mode = os.environ.get("PRAXYS_PERF_MODE", "both").lower()
    if mode not in {"cold", "warm", "both"}:
        print(f"PRAXYS_PERF_MODE={mode!r} not in cold|warm|both", file=sys.stderr)
        return 2

    print(f"Target: {base}")
    print(f"Mode: {mode}")
    phases_planned = {"cold": ["cold"], "warm": ["warm"], "both": ["cold", "warm"]}[mode]
    total_calls = n * len(ENDPOINTS) * len(phases_planned)
    print(f"Plan: {n} requests x {len(ENDPOINTS)} endpoints x {len(phases_planned)} phase(s) = "
          f"{total_calls} calls, {pause_ms}ms apart")

    print("\n[1/4] Logging in...")
    token = _login(base, user, pwd)

    print(f"\n[2/4] Driving synthetic load ({', '.join(phases_planned)})...")
    start = datetime.now(timezone.utc)
    all_samples: list[ClientSample] = []
    if "cold" in phases_planned:
        all_samples.extend(_drive_cold(base, token, n, pause_ms))
    if "warm" in phases_planned:
        all_samples.extend(_drive_warm(base, token, n, pause_ms))
    end = datetime.now(timezone.utc)
    print(f"\nClient wall-clock window: {start.isoformat()} .. {end.isoformat()}")

    print("\n[3/4] Client-side timings (includes network from this PC):")
    if "cold" in phases_planned:
        _print_client_summary(
            "COLD (200 — full pack execution)",
            _client_summary(all_samples, phase="cold", status=200),
        )
    if "warm" in phases_planned:
        _print_client_summary(
            "WARM 304 (L2 short-circuit — dependency + SELECT + blake2b only)",
            _client_summary(all_samples, phase="warm", status=304),
        )
        # A 200 in the warm phase means the ETag was busted between the
        # capture call and the warm replay — surface it so noise vs.
        # invalidation-storms are visible.
        warm_200 = _client_summary(all_samples, phase="warm", status=200)
        if any(s.get("n", 0) > 0 for s in warm_200.values()):
            _print_client_summary(
                "WARM 200 (ETag busted between capture and replay — should be 0)",
                warm_200,
            )

    print(f"\n[4/4] Waiting {ingest_s}s for App Insights ingestion...")
    time.sleep(ingest_s)

    print(f"\nServer-side BEFORE (last {baseline_days} days, ending at {start.isoformat()}):")
    try:
        before = _server_baseline_summary(baseline_days, start)
        _print_table(f"baseline ({baseline_days}d)", before)
    except Exception as e:
        print(f"  baseline query failed: {e}")
        before = []

    print(f"\nServer-side AFTER (synthetic burst, server-side timings via AppRequests):")
    try:
        after = _server_window_summary(start, end)
        _print_table("burst", after)
    except Exception as e:
        print(f"  burst query failed: {e}")
        after = []

    if before and after:
        # Compare 200-vs-200 only (304s have no historical baseline since
        # L2 hadn't shipped). The 304 win is visible in the burst rows
        # alone — orders of magnitude under p50 of the 200 row.
        print("\nDelta — 200 only, negative = faster:")
        before_200 = {r["Name"]: r for r in before if str(r.get("ResultCode")) == "200"}
        after_200 = {r["Name"]: r for r in after if str(r.get("ResultCode")) == "200"}
        for name in sorted(set(before_200) | set(after_200)):
            b = before_200.get(name)
            a = after_200.get(name)
            if not (b and a):
                continue
            for stat in ("p50", "p95", "p99"):
                bv = float(b[stat])
                av = float(a[stat])
                pct = (av - bv) / bv * 100 if bv else float("nan")
                print(f"  {name:<22} {stat}: {bv:>7.0f}ms -> {av:>7.0f}ms "
                      f"({pct:+.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
