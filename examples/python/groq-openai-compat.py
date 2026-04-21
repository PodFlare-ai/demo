"""Groq + Podflare — OpenAI-compatible client, swap base_url.

Groq (and Perplexity, Kimi, MiniMax, Together AI, DeepInfra, ...) all
expose OpenAI-compatible chat completions. The integration with Podflare
is identical to the native OpenAI example — only `base_url` and the
env-var name change.

Setup:
    pip install podflare openai
    export PODFLARE_API_KEY=pf_live_...
    export GROQ_API_KEY=gsk_...

Run:
    python groq-openai-compat.py

To switch to a different OpenAI-compatible provider, just change BASE_URL
and the env var name — see provider_table at top.
"""
import json
import os
from openai import OpenAI
from podflare import Sandbox

# ────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible providers — pick one. Each has the exact same call
# pattern below; only base_url + env_var differ.
# ────────────────────────────────────────────────────────────────────────────
PROVIDER = "groq"   # try: groq | perplexity | kimi | minimax | together | deepinfra
PROVIDERS = {
    "groq":       ("https://api.groq.com/openai/v1",         "GROQ_API_KEY",       "llama-3.3-70b-versatile"),
    "perplexity": ("https://api.perplexity.ai",              "PERPLEXITY_API_KEY", "sonar"),
    "kimi":       ("https://api.moonshot.ai/v1",             "MOONSHOT_API_KEY",   "moonshot-v1-32k"),
    "minimax":    ("https://api.minimax.chat/v1",            "MINIMAX_API_KEY",    "abab6.5-chat"),
    "together":   ("https://api.together.xyz/v1",            "TOGETHER_API_KEY",   "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
    "deepinfra":  ("https://api.deepinfra.com/v1/openai",    "DEEPINFRA_API_KEY",  "meta-llama/Llama-3.3-70B-Instruct"),
}
BASE_URL, ENV_VAR, MODEL = PROVIDERS[PROVIDER]
# ────────────────────────────────────────────────────────────────────────────

PODFLARE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": "Execute code in a Firecracker microVM. Returns stdout/stderr/exit_code.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string", "enum": ["python", "bash"]},
            },
            "required": ["code"],
        },
    },
}


def main() -> None:
    client = OpenAI(base_url=BASE_URL, api_key=os.environ[ENV_VAR])
    print(f"using {PROVIDER} ({MODEL}) via {BASE_URL}")

    with Sandbox() as sandbox:
        messages = [
            {"role": "user", "content": "Compute the sha256 of the string 'podflare' using code."},
        ]
        while True:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=[PODFLARE_TOOL],
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                print(msg.content)
                return
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                r = sandbox.run_code(args["code"], language=args.get("language", "python"))
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}\nexit: {r.exit_code}",
                })


if __name__ == "__main__":
    main()
