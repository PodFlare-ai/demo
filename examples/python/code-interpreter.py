"""Code Interpreter REPL — ask anything, the AI writes Python and runs it.

This is the ChatGPT "Advanced Data Analysis" pattern in 130 lines. Spin
up a Podflare sandbox, hand the model a `run_code` tool, and let it
solve whatever you throw at it. The sandbox persists across turns —
variables, imports, downloaded files, plots — so you can build up state
across a conversation just like the web UIs do.

Try asking:
    > Plot a sine wave from 0 to 2π and save it as sine.png
    > Now save it base64-encoded to clipboard.txt
    > Download the latest BTC price from coingecko and tell me trend
    > How many primes are there below 10,000?

Setup:
    pip install podflare openai
    export PODFLARE_API_KEY=pf_live_...   # mint at dashboard.podflare.ai/keys
    export OPENAI_API_KEY=sk-...

Run:
    python code-interpreter.py
"""
import json
import sys
from openai import OpenAI
from podflare import Sandbox

SYSTEM_PROMPT = """You are a code-interpreter assistant.

You have a `run_code` tool that executes Python (or bash) in a private
Linux sandbox with full internet access. Use it for anything that
benefits from real execution: math, data downloads, plotting, parsing,
testing hypotheses, calling APIs, etc.

The sandbox state PERSISTS across calls in this conversation — variables
you define, imports you make, and files you write all survive. Use that:
download data once, analyze it across many turns.

When you write code, prefer concise programs that print their result. The
user sees stdout. For plots, save to a PNG and tell the user the path."""

PODFLARE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": (
            "Execute code in an isolated Firecracker sandbox. The same "
            "sandbox is reused across every call in this conversation, so "
            "variables, imports, and files persist. Returns stdout, "
            "stderr, exit_code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to execute."},
                "language": {
                    "type": "string",
                    "enum": ["python", "bash"],
                    "description": "Runtime; defaults to python.",
                },
            },
            "required": ["code"],
        },
    },
}


def main() -> None:
    client = OpenAI()

    # SDK ≥ 0.0.16 picks the nearest region from your timezone — no Worker
    # hop on the first call. SDK ≥ 0.0.17 caps tail latency at p99 < 1 s.
    print("creating sandbox...", end=" ", flush=True)
    with Sandbox() as sandbox:
        print("ready.")
        print("─" * 60)
        print("Type a question (or 'exit'):")

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

        while True:
            try:
                user = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if user.lower() in {"exit", "quit", ":q"}:
                return
            if not user:
                continue

            messages.append({"role": "user", "content": user})
            _agent_loop(client, sandbox, messages)


def _agent_loop(client: OpenAI, sandbox: Sandbox, messages: list[dict]) -> None:
    """One user turn = one or more tool-call rounds until the model answers."""
    for _step in range(10):  # safety cap
        resp = client.chat.completions.create(
            model="gpt-5.1",
            messages=messages,
            tools=[PODFLARE_TOOL],
        )
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            # Model has its final answer.
            print(f"\n{msg.content}")
            return

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)
            code = args["code"]
            language = args.get("language", "python")
            # Show the user what the model is about to run — transparency
            # is half the point of running it ourselves vs a black-box
            # vendor's "advanced data analysis."
            print(f"\n  ┌─ run_code ({language}) ─" + "─" * 40)
            for line in code.splitlines():
                print(f"  │ {line}")
            r = sandbox.run_code(code, language=language)
            print(f"  └─ exit={r.exit_code}" + "─" * 40)
            if r.stdout.strip():
                for line in r.stdout.rstrip().splitlines():
                    print(f"    {line}")
            if r.stderr.strip():
                for line in r.stderr.rstrip().splitlines():
                    print(f"    [stderr] {line}", file=sys.stderr)

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": (
                    f"stdout:\n{r.stdout}\n"
                    f"stderr:\n{r.stderr}\n"
                    f"exit_code: {r.exit_code}"
                ),
            })


if __name__ == "__main__":
    main()
