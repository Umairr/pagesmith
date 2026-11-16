"""Landing page builder on Microsoft Agent Framework."""

from __future__ import annotations

from agent_framework import Agent

from pagesmith.models import ModelSpec
from pagesmith.workers._entry import main


def make_client(spec: ModelSpec):
    key = spec.require_key()
    if spec.provider.name == "anthropic":
        from agent_framework.anthropic import AnthropicClient

        return AnthropicClient(model=spec.name, api_key=key)
    if spec.provider.name == "openai":
        from agent_framework.openai import OpenAIChatClient

        return OpenAIChatClient(model=spec.name, api_key=key)

    # Gemini, OpenRouter and custom endpoints all speak OpenAI chat completions.
    from agent_framework.openai import OpenAIChatCompletionClient

    return OpenAIChatCompletionClient(model=spec.name, api_key=key, base_url=spec.base_url)


async def build(tools, instructions: str, message: str, spec: ModelSpec) -> None:
    # Without this, Anthropic's client caps replies at 1,024 tokens: too short
    # to write a page in one tool call.
    options = {"max_tokens": spec.max_tokens} if spec.max_tokens else None
    agent = Agent(client=make_client(spec), instructions=instructions, tools=tools, default_options=options)
    await agent.run(message)


if __name__ == "__main__":
    main(build)
