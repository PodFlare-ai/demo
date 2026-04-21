"""LangChain → Podflare tool — works with any LangChain chat model.

This is the highest-leverage integration: LangChain abstracts over every
major model provider (OpenAI, Anthropic, Gemini, Mistral, Groq, Bedrock,
Ollama, ...). One PodflareTool wrapper, all those models can call it.

Setup:
    pip install podflare langchain-core langchain-openai langgraph
    export PODFLARE_API_KEY=pf_live_...
    export OPENAI_API_KEY=sk-...        # or any other LangChain-supported provider

Run:
    python langchain-tool.py
"""
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from podflare.langchain import PodflareTool


def main() -> None:
    # PodflareTool maintains a single sandbox across calls — REPL state,
    # variables, imports, files all persist. That's what an agent loop wants.
    tool = PodflareTool()

    try:
        agent = create_react_agent(
            model=ChatOpenAI(model="gpt-5.1"),  # swap for any LangChain chat model
            tools=[tool],
        )
        out = agent.invoke({
            "messages": [
                ("user", "What's the 100th prime number? Use code."),
            ],
        })
        print(out["messages"][-1].content)
    finally:
        tool.close()


if __name__ == "__main__":
    main()
