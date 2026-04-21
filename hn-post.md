# HN draft — "I benchmarked E2B vs Daytona vs Podflare"

Proposed title:

> **I benchmarked E2B vs Daytona vs Podflare — and caught my own
> SDK lying about p99**

Disclosure (first reply as OP):

> *Disclosure: I work on Podflare. The bench scripts are public. I
> ran them against each platform via their own SDK with a key I
> bought/got the same way any developer would.*

---

## Body text

If you're building an agent that runs LLM-generated code, the three
major cloud sandbox platforms today are
[E2B](https://e2b.dev), [Daytona](https://daytona.io), and
[Podflare](https://podflare.ai). They all do the same basic thing:
give you a Linux VM to throw untrusted code into. So which is
"fastest"?

I spent a day benchmarking them against each other with an identical
harness — same machine, same minute, same workload. The most useful
thing I found wasn't the rank order. It was that my **own SDK had a
bug that inflated its p99 by 8×** and I only caught it because
someone on our team pointed out the tail numbers "don't look real."

## The setup

Thirty sequential `Sandbox.create() → exec("echo ready") → close()`
cycles per platform. No warmup discard, no cherry-picking. Bench
scripts are in
[github.com/PodFlare-ai/demo](https://github.com/PodFlare-ai/demo):

```bash
pip install podflare e2b-code-interpreter daytona
PODFLARE_API_KEY=pf_live_... python benchmarks/bench-reliability.py podflare
E2B_API_KEY=...               python benchmarks/bench-reliability.py e2b
DAYTONA_API_KEY=...           python benchmarks/bench-reliability.py daytona
```

Tested from a MacBook on residential wifi in California, April 2026.

## The results (SDK podflare 0.0.20, post-fix)

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
- **max**: bounded under 270 ms; the other two have outliers >850 ms

Zero errors across 90 total iterations. Reliability in the traditional
uptime sense is identical across all three — the differentiator is
latency *distribution*.

## The story of the bug

Before fixing this, our p99 was 1,741 ms and our max was 2,290 ms. That
"looked" like a real tail — the kind of number you'd attribute to
public-internet TCP SYN drops (~0.05–0.35 % rate across any backbone,
which Linux turns into 1 s → 3 s → 7 s retransmits).

I had "fixed" that earlier by shipping, in 0.0.17:

```python
timeouts = httpx.Timeout(connect=0.8, read=30.0, write=10.0, pool=5.0)
client = httpx.Client(..., transport=httpx.HTTPTransport(retries=2))
```

Idea: cap the connect timeout tight so we don't wait for the OS retry,
and let httpx try again on a fresh socket. Nice and defensive.

Except `retries=2` + a tight connect timeout turns into a foot-gun
when the handshake is **slow but not dead** — e.g., residential wifi
taking 900 ms for a TLS handshake because of a noisy local DNS
response. Our 800 ms ceiling kills it, retry kills it again, retry
kills it a third time, and three ConnectTimeouts in a row gets you to
~2.9 s before raising.

Empirical proof (reproduce this against any unreachable IP):

```
0.8s connect + retries=2, against blackhole:  raised after 2,910 ms
0.8s connect + retries=0:                     raised after   803 ms
2.0s connect + retries=0:                     raised after 2,002 ms
```

Self-inflicted. Our bench's p99 was our own retry loop multiplying a
single slow handshake into a triple-timeout chain.

## The fix (0.0.19 → 0.0.20, shipped during the writeup)

```python
timeouts = httpx.Timeout(connect=2.5, read=30.0, write=10.0, pool=5.0)
client = httpx.Client(..., transport=httpx.HTTPTransport(retries=1))
```

- Widen connect to 2.5 s so normal-slow handshakes complete on first
  attempt.
- Drop retries to 1 so a real failure isn't compounded.

After-fix 100-iter distribution:

```
  min       164 ms
  p50       187 ms
  p95       208 ms
  p99       221 ms
  max       475 ms
  >500ms    0/100
  >1000ms   0/100
```

p99 went from 1,741 → 221 ms. Max from 2,290 → 475. That's the fix
credit. The bench harness didn't lie — my SDK did.

## Architecture note: going direct isn't always faster

Podflare has an edge router at `api.podflare.ai` and direct region
URLs like `usw1.podflare.ai`. I always assumed direct was faster —
fewer hops. It turns out from a residential wifi laptop, **going
through the Cloudflare edge is faster**:

```
  via api.podflare.ai  →  p99 = 236 ms, max = 263 ms
  direct to usw1       →  p99 = 483 ms, max = 594 ms
```

Because Cloudflare's edge PoP is closer to my Mac than us-west is,
and the CF backbone to the origin is better than my ISP's route. So
the "extra hop" was actually shorter wall clock. Counter-intuitive but
reproducible.

So we shipped 0.0.20 to default to `api.podflare.ai` instead of
client-side timezone → direct-region. Every number above uses that
default.

## What I didn't measure (but could)

- **`fork(n)`**. Only Podflare exposes this primitive. ~80 ms
  server-side for n=5. Useful for tree-of-thought agents.
- **Persistent state across destroy.** Podflare's Spaces (full VM
  memory freeze), E2B's snapshot API, Daytona's archive. Semantics
  differ enough that "ms to resume" isn't directly comparable.
- **HTTP outbound from inside the sandbox.** Geography dominates.
  E2B hits `api.github.com/zen` in 25 ms (their colo is near GitHub's
  Azure us-east); Podflare us-west is 89 ms; Podflare us-east is
  29 ms. The difference is about which datacenter your sandbox lives
  in, not platform speed.
- **Cost per run.** Ages poorly. All three are within an order of
  magnitude per execution-minute.

## Takeaways

If you're picking a cloud sandbox for an AI agent today and you care
about raw latency, **Podflare wins every percentile** measured here.
If you care about Apache-2.0 + self-hostable on GCP/AWS, **E2B**.
If you want AGPL + self-hostable on Docker, **Daytona**.

But mostly: **verify the bench against your own environment**. Ship
it from whichever vantage your agent actually runs from. The p99
number you care about is the one your own code measures, not the one
the vendor puts in a comparison table. Especially if that vendor is
me.

## Links

- Reproduce: [github.com/PodFlare-ai/demo](https://github.com/PodFlare-ai/demo) — the three `bench-reliability.py` invocations
- The SDK fix that dropped our p99 8×: [podflare 0.0.19](https://pypi.org/project/podflare/0.0.19/) (connect=2.5, retries=1)
- The switch to edge-routing as default: [podflare 0.0.20](https://pypi.org/project/podflare/0.0.20/)
- Full 3-way comparison: [docs.podflare.ai/architecture/comparison](https://docs.podflare.ai/architecture/comparison)

---

# Submission checklist

- [ ] **Post from your personal account**, not a brand account
- [ ] **Disclosure as first top-level reply**
- [ ] **Weekday 8–11 am PT** for best organic pickup
- [ ] **Respond to every comment in the first 2 h**
- [ ] Ask for repro env (OS, network, SDK) if someone posts different
      numbers — don't argue with their data, rerun on your side
- [ ] Don't mention pricing

The "caught my own SDK lying" framing is the real hook for HN. Leading
with a genuine engineering mistake + fix usually outperforms
leading with "we win everything." And it's true — this actually
happened today.
