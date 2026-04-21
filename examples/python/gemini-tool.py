"""Google Gemini function calling → Podflare sandbox.

Uses Gemini's native function-calling API. Pattern: declare run_code as
a function, let Gemini decide when to call it, forward the call into a
Podflare sandbox, hand the result back.

Setup:
    pip install podflare google-genai
    export PODFLARE_API_KEY=pf_live_...
    export GEMINI_API_KEY=...           # or set GOOGLE_API_KEY

Run:
    python gemini-tool.py
"""
from google import genai
from google.genai import types
from podflare import Sandbox
from podflare.gemini import (
    podflare_function_declaration,
    run_function_call,
)


def main() -> None:
    client = genai.Client()

    with Sandbox() as sandbox:
        contents: list[types.Content] = [
            types.Content(role="user", parts=[
                types.Part.from_text(text="Compute the 100th prime number using code."),
            ]),
        ]

        for _step in range(8):  # safety cap; agents shouldn't loop forever
            resp = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(function_declarations=[
                        podflare_function_declaration(),
                    ])],
                ),
            )
            content = resp.candidates[0].content
            contents.append(content)

            calls = [p.function_call for p in content.parts if p.function_call]
            if not calls:
                # No more tool calls — the model gave its final answer.
                print(resp.text)
                return

            # Execute every function call in this turn and append the responses.
            response_parts = [
                types.Part.from_function_response(
                    name=c.name,
                    response=run_function_call(c, sandbox),
                )
                for c in calls
            ]
            contents.append(types.Content(role="user", parts=response_parts))


if __name__ == "__main__":
    main()
