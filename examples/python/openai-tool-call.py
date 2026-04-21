"""OpenAI native function calling → Podflare sandbox.

Pattern: define a `run_code` tool, let the model decide when to call it,
forward the call into a Podflare sandbox, hand the result back.

Setup:
    pip install podflare openai
    export PODFLARE_API_KEY=pf_live_...
    export OPENAI_API_KEY=sk-...

Run:
    python openai-tool-call.py
"""
import json
from openai import OpenAI
from podflare import Sandbox

PODFLARE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": (
            "Execute code in an isolated Firecracker microVM. Use for any "
            "calculation, data lookup, or task that benefits from real "
            "execution. Returns stdout, stderr, exit_code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Code to run."},
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
    with Sandbox() as sandbox:
        messages = [
            {"role": "user", "content": "What's the 100th prime number? Use code."},
        ]
        while True:
            resp = client.chat.completions.create(
                model="gpt-5.1",
                messages=messages,
                tools=[PODFLARE_TOOL],
            )
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                print(msg.content)
                return
            # Execute every tool call and append results.
            for call in msg.tool_calls:
                args = json.loads(call.function.arguments)
                r = sandbox.run_code(
                    args["code"],
                    language=args.get("language", "python"),
                )
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
