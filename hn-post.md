# HN draft — "I benchmarked E2B vs Daytona vs Podflare"

Proposed title:

> **I benchmarked the three major cloud sandbox platforms for AI
> agents (E2B, Daytona, Podflare)**

Disclosure (first reply as OP):

> *Disclosure: I work on Podflare. The bench scripts are public. I
> ran them against each platform via their own SDK with a key I
> bought/got the same way any developer would. If you can't reproduce
> these numbers on your own machine, I want to hear about it.*

---

## Body text

If you're building an agent that runs LLM-generated code, three cloud
sandbox platforms dominate the space today:
[E2B](https://e2b.dev), [Daytona](https://daytona.io), and
[Podflare](https://podflare.ai). They all do the same basic thing —
give you a fresh Linux VM to throw untrusted code into. The question
I couldn't find a clean answer to was: *how do they actually compare
on latency?*

So I wrote an identical-harness bench and ran all three from the same
laptop in the same minute.

## The setup

Thirty sequential `Sandbox.create() → exec("echo ready") → close()`
cycles per platform. No warmup-and-discard, no cherry-picking. Bench
scripts are public at
[github.com/PodFlare-ai/demo](https://github.com/PodFlare-ai/demo):

```bash
pip install podflare e2b-code-interpreter daytona
PODFLARE_API_KEY=pf_live_... python benchmarks/bench-reliability.py podflare
E2B_API_KEY=...               python benchmarks/bench-reliability.py e2b
DAYTONA_API_KEY=...           python benchmarks/bench-reliability.py daytona
```

Tested from a MacBook on residential wifi in California, April 2026.
Each platform uses its own SDK's default region (E2B → us-east,
Daytona → nearest, Podflare → Cloudflare-edge routed to us-west).
Each iteration is a full `create + exec + close` round-trip including
TLS and the 3 HTTPS calls that implies.

## The results

30 iterations each, milliseconds:

```
               min   p50   p95   p99   max   mean
  Podflare     143   153   170   236   263   173
  E2B          418   467   750   852   888   509
  Daytona      439   713  1130  1136  1137   722
```

Podflare wins every percentile:
- **p50**: 3.0× faster than E2B, 4.7× faster than Daytona
- **p95**: 4.4× vs E2B, 6.6× vs Daytona
- **p99**: 3.6× vs E2B, 4.8× vs Daytona
- **max**: bounded under 270 ms — other two have outliers >850 ms

Zero errors across 90 total iterations. Reliability in the traditional
uptime sense is identical across all three; the differentiator is
**latency distribution**.

## Why the gap is what it is

Every exec call on all three platforms looks identical from the SDK
side, but the underlying transport is different:

| platform | first-exec stack |
|---|---|
| Podflare | hostd → vsock binary protocol → in-VM agent (no TCP, no TLS inside the guest) |
| E2B | client-proxy → orchestrator → ConnectRPC over TCP+TLS to `envd` in-VM |
| Daytona | proxy → runner → Docker/Sysbox + HTTP server inside the container |

vsock skips the TCP + TLS + HTTP framing that E2B and Daytona pay
inside the guest for every exec. Server-side round-trip on Podflare
is ~3 ms; the remaining ~150 ms is the network between the caller
and the region.

Podflare's `api.podflare.ai` is a Cloudflare Worker that haversine-
routes to the nearest region — from residential wifi that turned out
to be meaningfully faster than going direct to the region, because
the CF edge PoP is closer to the caller than any single origin and
CF's backbone to the origin is cleaner than the public-internet
route. Direct-to-origin p99 was 483 ms; edge-routed p99 was 236 ms.
Counter-intuitive, reproducible.

## What I didn't measure (but you might care about)

- **`fork(n)`.** Only Podflare exposes this. Snapshot a running VM
  mid-flight, spawn N children from the exact parent state. ~80 ms
  server-side for n=5. The primitive tree-of-thought and multi-attempt
  code synthesis patterns actually want.
- **Persistent state across destroy.** Podflare (full VM memory
  freeze into a "Space"), E2B (snapshot API), Daytona (container
  archive). Semantics differ enough that a single "ms to resume"
  number isn't apples-to-apples.
- **HTTP outbound from inside the sandbox.** Geography dominates.
  E2B hits `api.github.com/zen` in 25 ms because their colo is near
  GitHub's Azure us-east; Podflare us-west is 89 ms, us-east is 29 ms.
  That's about which datacenter your sandbox lives in, not platform
  speed.
- **Cost per run.** Ages poorly. All three land within an order of
  magnitude per execution-minute; pricing pages move.

## Reproduce these numbers

The whole point is that you don't have to trust me.

```bash
git clone https://github.com/PodFlare-ai/demo
cd demo
python benchmarks/bench-reliability.py podflare
python benchmarks/bench-reliability.py e2b
python benchmarks/bench-reliability.py daytona
```

If your numbers differ from mine, tell me — include the SDK versions,
your geography, and your network. I'd much rather rerun the bench
from your vantage point than argue about whose laptop is faster.

## Takeaways

- **Raw latency:** Podflare wins every percentile measured here.
- **Apache-2.0 + self-host on GCP/AWS:** E2B.
- **AGPL + self-host on Docker:** Daytona.

Most importantly: **run this bench yourself from wherever your agent
actually lives.** The p99 you care about is the one your own code
measures, not the one a vendor puts in a comparison table —
especially if that vendor is me.

## Links

- Reproduce: [github.com/PodFlare-ai/demo](https://github.com/PodFlare-ai/demo)
- Full architecture comparison: [docs.podflare.ai/architecture/comparison](https://docs.podflare.ai/architecture/comparison)
- Performance deep-dive with per-operation breakdowns: [docs.podflare.ai/architecture/performance](https://docs.podflare.ai/architecture/performance)

---

# Submission checklist

- [ ] **Post from your personal account**, not a brand account
- [ ] **Disclosure as first top-level reply**
- [ ] **Weekday 8–11 am PT** for best organic pickup
- [ ] **Respond to every comment in the first 2 h**
- [ ] Ask for repro env (OS, network, SDK) if someone posts different
      numbers — don't argue with their data, rerun on your side
- [ ] Don't mention pricing unless directly asked

The hook is the identical-harness 3-way numbers. Keep the body tight,
let the table speak, and be ready to rerun for anyone who pushes back
with their own machine.
