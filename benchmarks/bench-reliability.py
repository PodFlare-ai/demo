#!/usr/bin/env python3
"""Reliability benchmark: 30 cold-start iterations per platform.

Companion to bench-cold-start.py — same workload, longer N to expose
distribution tails. The 5-iteration version is enough to see the
*median*; this version is what you cite when you want to make claims
about p95/p99 and "is it ever stupidly slow."

Output per platform: full sorted distribution, p50/p90/p95/p99/max,
error count, and the longest single iteration.

Usage:

    PODFLARE_API_KEY=pf_live_... python3 scripts/bench-reliability.py podflare
    E2B_API_KEY=...               python3 scripts/bench-reliability.py e2b
    DAYTONA_API_KEY=...           python3 scripts/bench-reliability.py daytona
    BL_API_KEY=...  BL_WORKSPACE=...  BL_REGION=us-pdx-1 \\
                                  python3 scripts/bench-reliability.py blaxel

Each iteration is a complete `create() → exec("echo ready") → destroy()`
cycle. We catch and count exceptions per-iteration so a transient
failure on iteration 7 doesn't kill the whole run — that's actually the
data we're trying to capture.
"""
from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import time
from typing import Callable, List, Tuple

ITERATIONS = 30


def _percentile(sorted_xs: List[float], q: float) -> float:
    """Linear-interpolated percentile. Matches numpy.percentile default."""
    if not sorted_xs:
        return 0.0
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    pos = q / 100.0 * (len(sorted_xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_xs[int(pos)]
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


def _summarize(label: str, totals: List[float], errors: List[str]) -> None:
    """Print the distribution + error budget."""
    print()
    print(f"=== {label} — {len(totals)} successes, {len(errors)} errors ===")
    if not totals:
        print("  (no successful iterations — see errors below)")
    else:
        s = sorted(totals)
        n = len(s)
        print(f"  count   {n}")
        print(f"  min     {s[0]:7.0f} ms")
        print(f"  p50     {_percentile(s, 50):7.0f} ms   (median)")
        print(f"  p90     {_percentile(s, 90):7.0f} ms")
        print(f"  p95     {_percentile(s, 95):7.0f} ms")
        print(f"  p99     {_percentile(s, 99):7.0f} ms")
        print(f"  max     {s[-1]:7.0f} ms")
        print(f"  mean    {statistics.mean(s):7.0f} ms")
        # Spread = p95 - p50; tells you how wild the tail is
        print(f"  p95-p50 {_percentile(s, 95) - _percentile(s, 50):7.0f} ms   (variance)")
    if errors:
        print(f"  errors  {len(errors)}/{len(totals) + len(errors)}")
        for e in errors[:3]:
            print(f"          → {e[:120]}")
        if len(errors) > 3:
            print(f"          ... and {len(errors) - 3} more")


def _run_iterations(
    label: str,
    one_iter: Callable[[int], Tuple[float, str]],
) -> None:
    """Generic driver: call one_iter(i) → (total_ms, status). Catch any
    exception per-iteration so a transient failure doesn't kill the run."""
    print(f"Platform: {label}  (iterations: {ITERATIONS})")
    totals: List[float] = []
    errors: List[str] = []
    overall_t0 = time.perf_counter()
    for i in range(ITERATIONS):
        try:
            ms, status = one_iter(i)
            totals.append(ms)
            print(f"  {i+1:2d}: total={ms:7.0f} ms   {status}")
        except Exception as e:
            errors.append(f"iter {i+1}: {type(e).__name__}: {e}")
            print(f"  {i+1:2d}: ERROR  {type(e).__name__}: {str(e)[:100]}")
    wall = time.perf_counter() - overall_t0
    _summarize(label, totals, errors)
    print(f"  wall    {wall:7.1f} s   (whole run)")


def bench_podflare() -> None:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk-py"))
    from podflare import Sandbox  # noqa: E402

    api_key = os.environ["PODFLARE_API_KEY"]
    host = os.environ.get("PODFLARE_HOSTD_URL")  # None → SDK auto-detect
    label = f"Podflare  host={host or '(SDK auto-detect)'}"

    def one_iter(_: int) -> Tuple[float, str]:
        t0 = time.perf_counter()
        sb = Sandbox(host=host, api_key=api_key) if host else Sandbox(api_key=api_key)
        r = sb.run_code("echo ready", language="bash")
        sb.close()
        return (time.perf_counter() - t0) * 1000, f"out={r.stdout.strip()!r}"

    _run_iterations(label, one_iter)


def bench_e2b() -> None:
    try:
        from e2b_code_interpreter import Sandbox as E2BSandbox  # type: ignore
    except ImportError:
        print("install: pip install e2b-code-interpreter"); sys.exit(1)

    def one_iter(_: int) -> Tuple[float, str]:
        t0 = time.perf_counter()
        sb = E2BSandbox.create()
        r = sb.commands.run("echo ready", timeout=60)
        sb.kill()
        return (time.perf_counter() - t0) * 1000, f"out={r.stdout.strip()!r}"

    _run_iterations("E2B", one_iter)


def bench_daytona() -> None:
    try:
        from daytona import Daytona  # type: ignore
    except ImportError:
        print("install: pip install daytona"); sys.exit(1)
    d = Daytona()

    def one_iter(_: int) -> Tuple[float, str]:
        t0 = time.perf_counter()
        sb = d.create()
        r = sb.process.exec("echo ready", timeout=60)
        sb.delete()
        return (time.perf_counter() - t0) * 1000, f"out={r.result.strip()!r}"

    _run_iterations("Daytona", one_iter)


def bench_blaxel() -> None:
    try:
        import asyncio as _asyncio
        from blaxel.core import SandboxInstance  # type: ignore
    except ImportError:
        print("install: pip install blaxel"); sys.exit(1)
    region = os.environ.get("BL_REGION") or "us-pdx-1"

    # One event loop for the whole run. asyncio.run() per iteration would
    # close + reopen the loop, which Blaxel's shared httpx client doesn't
    # like (see bench-http-outbound.py:bench_blaxel for the same fix).
    loop = _asyncio.new_event_loop()

    def one_iter(i: int) -> Tuple[float, str]:
        # Per-iter unique name — Blaxel rejects duplicates within a workspace.
        name = f"pf-rel-{int(time.time()*1000)}-{i}"

        async def _do() -> Tuple[float, str]:
            t0 = time.perf_counter()
            sb = await SandboxInstance.create({
                "name":   name,
                "image":  "blaxel/base-image:latest",
                "memory": 1024,
                "region": region,
            })
            r = await sb.process.exec({"command": "echo ready", "waitForCompletion": True})
            await sb.delete()
            return (time.perf_counter() - t0) * 1000, f"out={(getattr(r, 'stdout', '') or '').strip()!r}"

        return loop.run_until_complete(_do())

    try:
        _run_iterations(f"Blaxel  region={region}", one_iter)
    finally:
        loop.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("platform", choices=["podflare", "e2b", "daytona", "blaxel"])
    args = ap.parse_args()
    {
        "podflare": bench_podflare,
        "e2b":       bench_e2b,
        "daytona":   bench_daytona,
        "blaxel":    bench_blaxel,
    }[args.platform]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
