"""Anthropic Claude code_execution tool → Podflare sandbox.

Claude's `code_execution` server-side tool is great, but you might want
your own sandbox: longer-lived state, your own region, your own egress
policy, your own audit trail. This pattern uses Claude's tool_use API
to forward code into a Podflare sandbox you control.

Setup:
    pip install podflare anthropic
    export PODFLARE_API_KEY=pf_live_...
    export ANTHROPIC_API_KEY=sk-ant-...

Run:
    python anthropic-tool-use.py
"""
import anthropic
from podflare import Sandbox

PODFLARE_TOOL = {
    "name": "run_code",
    "description": (
        "Execute code in an isolated Firecracker microVM. Supports python "
        "(default) and bash. Returns stdout, stderr, exit_code. "
        "Filesystem and Python REPL state persist across calls."
    ),
    "input_schema": {
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
}


def main() -> None:
    client = anthropic.Anthropic()

    with Sandbox() as sandbox:
        messages = [
            {"role": "user", "content": "Compute the 100th prime number. Use the tool."},
        ]
        for _step in range(8):
            resp = client.messages.create(
                model="claude-opus-4-7",
                max_tokens=2048,
                tools=[PODFLARE_TOOL],
                messages=messages,
            )
            messages.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                # Final answer text is in the text blocks of the last message.
                for block in resp.content:
                    if block.type == "text":
                        print(block.text)
                return

            # Forward each tool_use block into the sandbox.
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                code = block.input.get("code", "")
                language = block.input.get("language", "python")
                r = sandbox.run_code(code, language=language)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": (
                        f"stdout:\n{r.stdout}\n"
                        f"stderr:\n{r.stderr}\n"
                        f"exit_code: {r.exit_code}"
                    ),
                    "is_error": r.exit_code != 0,
                })
            messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    main()
