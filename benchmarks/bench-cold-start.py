#!/usr/bin/env python3
"""Cold-start benchmark: the metric AI-agent users actually feel.

Measures three distinct phases per sandbox life-cycle:

  provision_ms = Sandbox.create() returns
  first_exec_ms = first `echo ready` completes (round-trip + exec)
  total_ms      = provision + first_exec

We care about `total_ms` because that's "how long until my agent can
run its first tool call." A warm-pool hit wins on provision_ms; a
pre-running in-sandbox daemon wins on first_exec_ms.

Usage:

    PODFLARE_API_KEY=pf_live_... python3 scripts/bench-cold-start.py podflare
    E2B_API_KEY=...              python3 scripts/bench-cold-start.py e2b
    DAYTONA_API_KEY=...          python3 scripts/bench-cold-start.py daytona

5 cold starts per platform, sequential. Each sandbox is destroyed
before the next one is created so every run is truly cold on the
client side (connection pools, region cache, TLS sessions all get to
persist in-process though — which is realistic agent behavior).
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from typing import List

RUNS = 5


def bench_podflare():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk-py"))
    from podflare import Sandbox  # noqa: E402

    api_key = os.environ["PODFLARE_API_KEY"]
    # Default: let the SDK pick the nearest region itself (timezone →
    # haversine → direct origin). Matches what real customers get
    # post-0.0.16 — first call goes direct to nearest box, no Worker
    # hop. To force a specific origin (e.g. measure Worker overhead),
    # set PODFLARE_HOSTD_URL=https://api.podflare.ai or =https://usw1.podflare.ai.
    host = os.environ.get("PODFLARE_HOSTD_URL")
    print(f"Platform: Podflare  host={host or '(SDK auto-detect)'}")

    provisions, first_execs, totals = [], [], []
    for i in range(RUNS):
        t0 = time.perf_counter()
        sb = Sandbox(host=host, api_key=api_key) if host else Sandbox(api_key=api_key)
        t1 = time.perf_counter()
        r = sb.run_code("echo ready", language="bash")
        t2 = time.perf_counter()
        sb.close()

        p, f = (t1 - t0) * 1000, (t2 - t1) * 1000
        provisions.append(p); first_execs.append(f); totals.append(p + f)
        print(f"  run {i+1}:  provision={p:6.0f} ms   first_exec={f:6.0f} ms   total={p+f:6.0f} ms   out={r.stdout.strip()!r}")

    _summary(provisions, first_execs, totals)


def bench_e2b():
    try:
        from e2b_code_interpreter import Sandbox as E2BSandbox  # type: ignore
    except ImportError:
        print("install: pip install e2b-code-interpreter"); sys.exit(1)
    print("Platform: E2B")

    provisions, first_execs, totals = [], [], []
    for i in range(RUNS):
        t0 = time.perf_counter()
        sb = E2BSandbox.create()
        t1 = time.perf_counter()
        exe = sb.commands.run("echo ready", timeout=60)
        t2 = time.perf_counter()
        sb.kill()

        p, f = (t1 - t0) * 1000, (t2 - t1) * 1000
        provisions.append(p); first_execs.append(f); totals.append(p + f)
        print(f"  run {i+1}:  provision={p:6.0f} ms   first_exec={f:6.0f} ms   total={p+f:6.0f} ms   out={exe.stdout.strip()!r}")

    _summary(provisions, first_execs, totals)


def bench_daytona():
    try:
        from daytona import Daytona  # type: ignore
    except ImportError:
        print("install: pip install daytona"); sys.exit(1)
    print("Platform: Daytona")
    d = Daytona()

    provisions, first_execs, totals = [], [], []
    for i in range(RUNS):
        t0 = time.perf_counter()
        sb = d.create()
        t1 = time.perf_counter()
        r = sb.process.exec("echo ready", timeout=60)
        t2 = time.perf_counter()
        sb.delete()

        p, f = (t1 - t0) * 1000, (t2 - t1) * 1000
        provisions.append(p); first_execs.append(f); totals.append(p + f)
        print(f"  run {i+1}:  provision={p:6.0f} ms   first_exec={f:6.0f} ms   total={p+f:6.0f} ms   out={r.result.strip()!r}")

    _summary(provisions, first_execs, totals)


def bench_blaxel():
    try:
        import asyncio as _asyncio
        from blaxel.core import SandboxInstance  # type: ignore
    except ImportError:
        print("install: pip install blaxel"); sys.exit(1)
    region = os.environ.get("BL_REGION") or "us-pdx-1"
    print(f"Platform: Blaxel  region={region}")

    async def one_run(i: int):
        # Per-run unique name — Blaxel rejects duplicate names within a workspace.
        name = f"pf-bench-{int(time.time()*1000)}-{i}"
        t0 = time.perf_counter()
        sb = await SandboxInstance.create({
            "name":   name,
            "image":  "blaxel/base-image:latest",
            "memory": 1024,
            "region": region,
        })
        t1 = time.perf_counter()
        r = await sb.process.exec({"command": "echo ready", "waitForCompletion": True})
        t2 = time.perf_counter()
        await sb.delete()
        out = (getattr(r, "stdout", "") or "").strip()
        return (t1 - t0) * 1000, (t2 - t1) * 1000, out

    provisions, first_execs, totals = [], [], []
    for i in range(RUNS):
        p, f, out = _asyncio.run(one_run(i))
        provisions.append(p); first_execs.append(f); totals.append(p + f)
        print(f"  run {i+1}:  provision={p:6.0f} ms   first_exec={f:6.0f} ms   total={p+f:6.0f} ms   out={out!r}")

    _summary(provisions, first_execs, totals)


def _summary(provisions: List[float], first_execs: List[float], totals: List[float]):
    def stat(label: str, xs: List[float]):
        xs_s = sorted(xs)
        print(
            f"  {label:12s} min={xs_s[0]:6.0f}  "
            f"median={xs_s[len(xs_s)//2]:6.0f}  "
            f"max={xs_s[-1]:6.0f}  "
            f"mean={statistics.mean(xs_s):6.0f} ms"
        )
    print("\nagg:")
    stat("provision",  provisions)
    stat("first_exec", first_execs)
    stat("total",      totals)


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
