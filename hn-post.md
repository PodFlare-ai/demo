# HN draft — "I benchmarked E2B vs Daytona vs Podflare"

Proposed title:

> **I benchmarked E2B vs Daytona vs Podflare — here's what I found**

Proposed first comment (disclosure) as a reply to our own submission:

> *Disclosure: I work on Podflare. The bench scripts are in the repo; I
> ran them against each platform's public SDK with a key I bought/got
> the same way any developer would. If your numbers differ please
> share them — we treat regressions as P0.*

---

## Body text

If you're building an agent that runs LLM-generated code, the three
major cloud sandbox platforms today are
[E2B](https://e2b.dev), [Daytona](https://daytona.io), and
[Podflare](https://podflare.ai). They all do the same basic thing: give
you a Linux VM you can throw untrusted code into. So which is
"fastest"?

I spent a day benching them against each other with an identical harness
— same machine, same minute, same workload — and the answer is more
interesting than I expected.

## Methodology

Thirty sequential `Sandbox.create() → exec("echo ready") → close()`
cycles per platform. Each cycle is a complete cold-start round-trip.
I measured the whole wall-clock of each cycle and report the full
distribution. No warmup discard, no cherry-picking, no "typical
customer workload" curation.

Bench scripts are in
[github.com/PodFlare-ai/demo](https://github.com/PodFlare-ai/demo) —
one file per platform, they all do the same thing via each SDK:

```bash
pip install podflare e2b-code-interpreter daytona

PODFLARE_API_KEY=pf_live_... python benchmarks/bench-reliability.py podflare
E2B_API_KEY=...               python benchmarks/bench-reliability.py e2b
DAYTONA_API_KEY=...           python benchmarks/bench-reliability.py daytona
```

Tested from a MacBook on residential wifi in California, April 2026.
If you run it from a fiber uplink or a cloud VM your absolute numbers
will be ~100–150 ms lower across the board — that's the last-mile
delta. The *ranking* is what's stable.

## The results

30 iterations, full distribution, milliseconds. One representative run
(I ran this three times across an hour — see "run-to-run variance"
below):

```
                 min   p50   p95   p99   max   mean   p95-p50
  Podflare       245   280   380  1741  2290    357      100
  E2B            412   470   809   879   906    527      339
  Daytona        457   777  1183  1350  1418    793      406
```

A few things jump out:

1. **No one platform wins every percentile.** Podflare takes p50 and p95
   (1.7× and 2.1× faster than the next best). E2B takes p99 and max —
   our worst-case ~2,300 ms vs their ~900 ms is not close.

2. **Zero errors across 90 total iterations.** "Reliability" in the
   traditional uptime sense is identical across all three. The
   differentiator is *latency distribution*, not availability.

3. **The spread tells you about tail behavior.** Podflare's 100 ms
   between p50 and p95 is the tightest in the fast zone — the typical
   request and the 1-in-20 request are basically the same. E2B trades
   a higher median for a tighter long-tail bound. If p99 is in your
   SLA, E2B is probably the right answer. If median latency drives
   the feel of your agent, Podflare.

4. **Daytona was the consistent-but-slowest** of the three. Nothing
   catastrophic — just no standout metric.

### Run-to-run variance

I ran this three times over an hour. The p50 rank order and the p95
rank order are stable across runs — Podflare wins both every time,
E2B second, Daytona third. But the **absolute p99 numbers bounce
around a lot** at this sample size:

```
  Podflare p99:   519 → 1741 → 2000 ms   (three runs)
  E2B      p99:   879 →  903 →  903 ms
  Daytona  p99:  1184 → 1240 → 1350 ms
```

E2B is noticeably more tail-stable than the other two. That tracks
with the architectural difference (below). If you want reliable p99
numbers you'd need several hundred iterations per platform; 30 is
enough to rank but not enough to publish a precise tail claim.

## What explains the distribution shapes

We dug into our own p99 outlier because it was annoying. The cause
turned out to be interesting: **public-internet TCP SYN drops**.

Every backbone drops ~0.05–0.35 % of SYN packets. Linux's default
reaction is exponential retry at 1 s → 3 s → 7 s. A single dropped SYN
turns into a 7-second request. With 30 iterations from residential
wifi you'd expect to hit one. We did.

Our SDK fix (shipped as `podflare-0.0.17`): cap the connect timeout
at 800 ms and let httpx retry on a fresh socket. Now a dropped SYN
becomes ~800 ms + a sub-second retry instead of 7 s. That's why our
p95 is 380 ms — we own the client library and can fix this.

But the p99 still occasionally hits 1.7–2 s, and I'm pretty sure I
know why now: each iteration of our bench creates a **fresh
`Sandbox()` instance**, which creates a **fresh httpx client pool**.
Between iterations the pool cools off, and on some fraction of
iterations the next call opens a new TCP connection that catches a
SYN drop. Two SYN drops in a row during the 0.8 s + retry window =
~2 s. This is a bench-harness artifact — in a real agent loop you
reuse one `Sandbox()` and the h1 keep-alive pool stays warm. Still,
it's on our todo list to pre-warm the connection during
`Sandbox()` construction.

**E2B's ConnectRPC over HTTP/2 handles this better** — a persistent
h2 connection doesn't open new TCPs per call, so SYN drops only
matter at session start. That's a legitimate architectural advantage
for tail-bound workloads, reflected in their much more stable p99
(~880–900 ms across three runs, vs our 519 → 1,741 → 2,000 ms).
Respect.

Daytona runs Docker + Sysbox rather than Firecracker, with an in-VM
HTTP server on port 2280. Their per-call overhead is higher but more
predictable — which shows up as the wider p95−p50 spread but the
lower absolute p99 vs ours.

## What I didn't measure (but could)

- **Fork(n)**. Only Podflare exposes this primitive. Server-side it's
  ~80 ms for `n=5`. Useful for tree-of-thought agents. Couldn't run
  an apples-to-apples comparison.

- **Persistent state across destroy**. Podflare's "Spaces" (full VM
  memory freeze-to-disk), E2B's snapshot API, Daytona's
  archive. Semantics differ enough that "ms to resume" isn't
  directly comparable.

- **HTTP outbound from inside the sandbox**. Geography dominates:
  E2B hits `api.github.com/zen` in 25 ms (their colo is near
  GitHub's Azure us-east); Podflare us-west is 89 ms (coast-to-
  coast). Podflare us-east is 29 ms. The comparison is about
  which datacenter your sandbox lives in, not platform speed.

- **Cost per run**. Pricing gets updated, so a static comparison
  ages poorly. TL;DR: all three are within the same order of
  magnitude per execution-minute.

## Takeaways

If you're picking a cloud sandbox for an AI agent today:

- **p50 matters most for interactive agents** (every tool call is
  felt by a human waiting). Podflare.
- **p99 matters most for SLA-bound batch work** (one bad call
  blocks a whole job). E2B.
- **Open source matters**. E2B is Apache-2.0 (self-hostable, no
  viral clause). Daytona is AGPL-3.0 (self-hostable, but
  modifications must be public if you run as a service). Podflare
  is proprietary platform + MIT SDKs.
- **Fork() and persistent memory-level state are unique to
  Podflare** (currently). If you need them you don't really have
  a choice.

## Links

- Reproduce: [github.com/PodFlare-ai/demo](https://github.com/PodFlare-ai/demo)
  — the three `bench-reliability.py` invocations above. Please send
  us your numbers if they disagree.
- Full provider matrix + LangChain / Gemini / Vercel AI SDK adapters:
  in that same repo under `examples/`.
- Podflare performance page with the 5-iter bench history:
  [docs.podflare.ai/architecture/performance](https://docs.podflare.ai/architecture/performance)
- Podflare 3-way comparison (this post's data, longer form):
  [docs.podflare.ai/architecture/comparison](https://docs.podflare.ai/architecture/comparison)

---

# Checklist before you submit

- [ ] **Post from your personal account**, not a brand account —
  HN auto-flags vendor-branded submissions.
- [ ] **Disclosure as the first top-level reply** to your own post
  (the text at the top of this file). HN moderators quietly
  penalize posts where vendor status shows up only in the comments
  after someone else finds it.
- [ ] **Post in a weekday morning US time window** (8–11 am Pacific).
  Best organic pickup.
- [ ] **Respond to every comment in the first two hours.** HN's
  ranking algo weights author engagement heavily. Answer
  disagreements with numbers, not adjectives.
- [ ] **Have a fallback ready**: if someone posts different numbers,
  don't argue — ask for their environment (OS, network, SDK
  version) and rerun on your side. The post's credibility comes
  from this behavior more than from the numbers themselves.
- [ ] **Don't mention pricing.** Distracts from the technical
  discussion and gets it re-flagged as marketing.

# Reasons HN might reject it

- **Title pattern is known marketing bait** — mitigated by leading
  with a real technical finding (SYN-drop tail behavior) and by
  admitting our p99 loss to E2B. If you want to hedge further,
  alternative title: "TCP SYN drops dominate the p99 of every AI
  sandbox platform I tested."
- **Too many CTAs** — I've kept the body to one (the GitHub repo).
  Don't add more in a top-level edit.

# If the post lands well

Expect traffic spike in waves: HN front page ~1h after submission,
Twitter/X secondary wave a few hours later, Discord/Slack developer
communities the next day. Have `api.podflare.ai` capacity ready —
your warm pool is 120 per region; an HN hit could push 300+ cold
creates in an hour. Worth pre-warming to 160 per region for the
~24 h window.
