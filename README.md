# Podflare demos

Public examples + reproducible benchmarks for [Podflare](https://podflare.ai),
the fastest hardware-isolated cloud sandbox for AI agents.

This repo is the **public-facing companion** to the [main monorepo](https://github.com/PodFlare-ai/podflare).
The SDKs and platform live there; this repo is what you'd read first if you
wanted to:

- Reproduce the headline benchmarks (vs E2B, Daytona, Blaxel)
- Copy-paste a working "hello world" agent integration in your language
- See drop-in adapters for the model providers you actually use

## What's in here

```
benchmarks/                  Reproducible head-to-head bench scripts
  bench-cold-start.py        5-iter quick: provision + first_exec + total
  bench-reliability.py       30-iter distribution: p50, p95, p99, max
  bench-http-outbound.py     Inside-sandbox curl latency

examples/python/             Python + pip install podflare
  hello.py                   30 lines: create → run_code → close
  anthropic-tool-use.py      Claude code_execution → Podflare exec
  openai-tool-call.py        OpenAI function calling → Podflare exec
  langchain-tool.py          LangChain tool wrapper (any model)
  gemini-tool.py             Google Gemini function calling
  groq-openai-compat.py      Groq via OpenAI-compatible endpoint
  perplexity-openai-compat.py
  kimi-openai-compat.py      Kimi (Moonshot AI) via OpenAI-compatible
  minimax-openai-compat.py
  mistral-tool.py            Mistral SDK (when supported)

examples/typescript/         Node.js + npm install podflare
  hello.ts
  anthropic-tool-use.ts
  ai-sdk-tool.ts             Vercel AI SDK
  openai-agents.ts           OpenAI Agents SDK
  langchain-tool.ts
  gemini-tool.ts
```

## Quick start

```bash
# Python
pip install podflare
export PODFLARE_API_KEY=pf_live_...   # mint at dashboard.podflare.ai/keys
python examples/python/hello.py
```

```bash
# TypeScript / Node.js
npm install podflare
export PODFLARE_API_KEY=pf_live_...
npx tsx examples/typescript/hello.ts
```

## Reproducing the benchmarks

The headline numbers on [our comparison page](https://docs.podflare.ai/architecture/comparison)
all came from the scripts in `benchmarks/`. They're identical to the ones
linked from the docs — same workload, same harness, no cherry-picking.

```bash
pip install podflare e2b-code-interpreter daytona blaxel

# 30-iter reliability bench — the headline numbers
PODFLARE_API_KEY=pf_live_... python benchmarks/bench-reliability.py podflare
E2B_API_KEY=...               python benchmarks/bench-reliability.py e2b
DAYTONA_API_KEY=...           python benchmarks/bench-reliability.py daytona
BL_API_KEY=... BL_WORKSPACE=... \
                              python benchmarks/bench-reliability.py blaxel

# HTTP outbound from inside the sandbox
PODFLARE_API_KEY=pf_live_... python benchmarks/bench-http-outbound.py podflare
```

Each prints the full distribution — min, p50, p90, p95, p99, max, mean —
plus error count. Run them yourself and **send us your numbers** if they
differ from what's on the comparison page.

## Supported AI providers

The Podflare SDK gives you `Sandbox.run_code(code, language)`. Anything that
can call a function can wrap it. Our pre-built adapters:

| provider | Python | TypeScript | how it works |
|---|---|---|---|
| **Anthropic Claude** | `from podflare.anthropic import ...` | `import { handleCodeExecutionToolUse } from "podflare/anthropic"` | Native `code_execution` tool_use blocks |
| **OpenAI Agents** | (in roadmap) | `import { podflareCodeInterpreter } from "podflare/openai-agents"` | Tool factory for `@openai/agents` |
| **Vercel AI SDK** | n/a | `import { podflareRunCode } from "podflare/ai-sdk"` | `tool()` helper for `ai` package |
| **LangChain** | `from podflare.langchain import PodflareTool` | `import { PodflareTool } from "podflare/langchain"` | Drop-in `BaseTool` — works with any LangChain-supported model |
| **Google Gemini** | `from podflare.gemini import podflare_function_declaration, run` | `import { podflareGeminiTool } from "podflare/gemini"` | `function_declarations` for Gemini's tool calling |

### OpenAI-compatible providers (no extra code needed)

These platforms all expose an OpenAI-compatible chat completions API. Use
the `openai` Python package (or `@openai/agents` in TS) with the right
`base_url` and `api_key`, then wire Podflare as a tool the same way you
would with native OpenAI:

| provider | base_url | env var convention |
|---|---|---|
| **Groq** | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` |
| **Perplexity** | `https://api.perplexity.ai` | `PERPLEXITY_API_KEY` |
| **Kimi (Moonshot AI)** | `https://api.moonshot.ai/v1` | `MOONSHOT_API_KEY` |
| **MiniMax** | `https://api.minimax.chat/v1` | `MINIMAX_API_KEY` |
| **Together AI** | `https://api.together.xyz/v1` | `TOGETHER_API_KEY` |
| **DeepInfra** | `https://api.deepinfra.com/v1/openai` | `DEEPINFRA_API_KEY` |

See `examples/python/groq-openai-compat.py` for the full pattern — it's
identical for all six. Swap one URL and one env var.

## License

MIT. Use however you want — copy snippets into your own code, fork the
repo, fold the bench scripts into your CI. Attribution appreciated but
not required.

## Issues

Bench reproductions that don't match our published numbers are P0 for us.
Open an issue with the platform, the SDK version, your machine type, and
the raw output. We'd rather find the regression than have it sit in
production.
