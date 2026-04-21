#!/usr/bin/env python3
"""HTTP-outbound benchmark for any sandbox platform.

Runs the same inside-the-sandbox HTTP-call test against two reliable
targets. Keeps the bench focused on what it's supposed to measure —
sandbox egress network speed — rather than how angry someone's free-
tier target endpoint is with our IP today.

Targets:
  1. cloudflare.com/cdn-cgi/trace  — Cloudflare's trace. 20–35 ms globally,
                                     no rate limit, never down. The apples-
                                     to-apples baseline.
  2. api.github.com/zen            — Real HTTPS API, real TLS. First call
                                     pays DNS, subsequent ~70 ms from a US
                                     sandbox close to GitHub's east-coast
                                     peering.

Deliberately NOT included: httpbin.org/ip. It's a single-tenant Heroku
side project that rate-limits by source IP and routinely serves 10 s+
outliers. When a sandbox platform's shared-NAT IP gets flagged, httpbin
starts connection-resetting — that's a story about httpbin, not about
the platform. Earlier versions of this bench included it and we kept
citing the wrong number.

Usage:

    # Podflare
    PODFLARE_API_KEY=pf_live_...  python3 scripts/bench-http-outbound.py podflare

    # E2B (requires e2b-code-interpreter)
    E2B_API_KEY=...               python3 scripts/bench-http-outbound.py e2b

    # Daytona (requires daytona)
    DAYTONA_API_KEY=...           python3 scripts/bench-http-outbound.py daytona

Prints: per-target, per-run curl time + aggregate stats.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import Callable, List, Tuple

TARGETS: List[Tuple[str, str]] = [
    ("cloudflare", "https://cloudflare.com/cdn-cgi/trace"),
    ("github",     "https://api.github.com/zen"),
]

# Each target gets 5 sequential calls from a SINGLE sandbox.
RUNS_PER_TARGET = 5
CURL_MAX_SECONDS = 15


def run_in_sandbox_podflare(exec_bash: Callable[[str], Tuple[int, str, float]]):
    """Inner loop for any platform — `exec_bash` takes a bash snippet and
    returns (exit_code, stdout, wall_clock_seconds)."""
    for name, url in TARGETS:
        print(f"\n── {name}  {url}")
        curl_times_s: List[float] = []
        wall_times_ms: List[float] = []
        for i in range(RUNS_PER_TARGET):
            code = f"curl -sS --max-time {CURL_MAX_SECONDS} -o /dev/null -w '%{{time_total}}' {url}"
            ec, out, wall = exec_bash(code)
            out = out.strip()
            wall_times_ms.append(wall * 1000)
            try:
                curl_s = float(out)
                curl_times_s.append(curl_s)
                print(f"  run {i+1}:  curl={curl_s*1000:7.0f} ms   exec_wall={wall*1000:7.0f} ms")
            except ValueError:
                print(f"  run {i+1}:  curl=ERR {out[:100]}  exec_wall={wall*1000:7.0f} ms")
        if curl_times_s:
            s = sorted(curl_times_s)
            n = len(s)
            print(
                f"  agg:     min={s[0]*1000:5.0f} "
                f"median={s[n//2]*1000:5.0f} "
                f"max={s[-1]*1000:5.0f} "
                f"mean={statistics.mean(s)*1000:5.0f} ms"
                f"  ({n} samples)"
            )


def bench_podflare():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk-py"))
    from podflare import Sandbox  # noqa: E402

    api_key = os.environ["PODFLARE_API_KEY"]
    # Default: SDK auto-detects nearest region (post-0.0.16). Override
    # with PODFLARE_HOSTD_URL to measure a specific origin.
    host = os.environ.get("PODFLARE_HOSTD_URL")
    print(f"Platform: Podflare  host={host or '(SDK auto-detect)'}")
    sb = Sandbox(host=host, api_key=api_key) if host else Sandbox(api_key=api_key)
    try:
        def exec_bash(cmd: str) -> Tuple[int, str, float]:
            t = time.perf_counter()
            r = sb.run_code(cmd, language="bash")
            return r.exit_code, r.stdout, time.perf_counter() - t
        run_in_sandbox_podflare(exec_bash)
    finally:
        sb.close()


def bench_e2b():
    """Requires: pip install e2b-code-interpreter"""
    try:
        from e2b_code_interpreter import Sandbox as E2BSandbox  # type: ignore
    except ImportError:
        print("install e2b-code-interpreter: pip install e2b-code-interpreter")
        sys.exit(1)
    print("Platform: E2B")
    # Current E2B SDK requires the factory — bare `E2BSandbox()` now expects
    # positional sandbox_id/envd_version/etc. `create()` provisions a new one.
    sb = E2BSandbox.create()
    try:
        def exec_bash(cmd: str) -> Tuple[int, str, float]:
            t = time.perf_counter()
            exe = sb.commands.run(cmd, timeout=60)
            return exe.exit_code, exe.stdout, time.perf_counter() - t
        run_in_sandbox_podflare(exec_bash)
    finally:
        sb.kill()


def bench_daytona():
    """Requires: pip install daytona"""
    try:
        from daytona import Daytona  # type: ignore
    except ImportError:
        print("install daytona: pip install daytona")
        sys.exit(1)
    print("Platform: Daytona")
    d = Daytona()
    sb = d.create()
    try:
        def exec_bash(cmd: str) -> Tuple[int, str, float]:
            t = time.perf_counter()
            r = sb.process.exec(cmd, timeout=60)
            return r.exit_code, r.result, time.perf_counter() - t
        run_in_sandbox_podflare(exec_bash)
    finally:
        sb.delete()


def bench_blaxel():
    """Requires: pip install blaxel + BL_API_KEY + BL_WORKSPACE."""
    try:
        import asyncio as _asyncio
        from blaxel.core import SandboxInstance  # type: ignore
    except ImportError:
        print("install blaxel: pip install blaxel"); sys.exit(1)
    region = os.environ.get("BL_REGION") or "us-pdx-1"
    print(f"Platform: Blaxel  region={region}")

    # Pin one event loop across all calls — Blaxel's SDK keeps a shared
    # httpx client whose connections are bound to the loop they were
    # opened on. asyncio.run() per call would close that loop after the
    # first exec and the second call would crash with
    # "Event loop is closed". loop.run_until_complete() reuses the loop.
    loop = _asyncio.new_event_loop()
    name = f"pf-http-bench-{int(time.time()*1000)}"
    sb = loop.run_until_complete(SandboxInstance.create({
        "name": name, "image": "blaxel/base-image:latest",
        "memory": 1024, "region": region,
    }))
    # Blaxel's base image is bare Alpine — no curl by default.
    # Install it before benching so the curl bench can run at all.
    # (Note this step counts against Blaxel's "out of the box" UX.)
    print("  [setup] apk add curl (Blaxel base-image lacks it) ...", end="", flush=True)
    t_setup = time.perf_counter()
    setup = loop.run_until_complete(sb.process.exec({
        "command": "apk add --no-cache curl",
        "waitForCompletion": True,
    }))
    setup_ms = (time.perf_counter() - t_setup) * 1000
    if getattr(setup, "exit_code", 0) != 0:
        print(f" FAILED in {setup_ms:.0f} ms — {getattr(setup, 'stderr', '')!r}")
        loop.run_until_complete(sb.delete())
        loop.close()
        sys.exit(1)
    print(f" ok in {setup_ms:.0f} ms")

    try:
        def exec_bash(cmd: str) -> Tuple[int, str, float]:
            t = time.perf_counter()
            r = loop.run_until_complete(
                sb.process.exec({"command": cmd, "waitForCompletion": True})
            )
            return (
                getattr(r, "exit_code", 0),
                (getattr(r, "stdout", "") or "").strip(),
                time.perf_counter() - t,
            )
        run_in_sandbox_podflare(exec_bash)
    finally:
        loop.run_until_complete(sb.delete())
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
