"""Landing page builder on Agno."""

from __future__ import annotations

from agno.agent import Agent

from pagesmith.models import ModelSpec
from pagesmith.workers._entry import main


def make_model(spec: ModelSpec):
    key = spec.require_key()
    match spec.provider.name:
        case "anthropic":
            from agno.models.anthropic import Claude

            return Claude(id=spec.name, api_key=key, max_tokens=spec.max_tokens)
        case "gemini":
            from agno.models.google import Gemini

            return Gemini(id=spec.name, api_key=key, max_output_tokens=spec.max_tokens)
        case "openrouter":
            from agno.models.openrouter import OpenRouter

            return OpenRouter(id=spec.name, api_key=key, max_tokens=spec.max_tokens)
        case "custom":
            from agno.models.openai.like import OpenAILike

            return OpenAILike(id=spec.name, api_key=key, base_url=spec.base_url, max_tokens=spec.max_tokens)
        case _:
            from agno.models.openai import OpenAIChat

            return OpenAIChat(id=spec.name, api_key=key)


async def build(tools, instructions: str, message: str, spec: ModelSpec) -> None:
    agent = Agent(model=make_model(spec), instructions=instructions, tools=tools, tool_call_limit=80)
    await agent.arun(input=message)


if __name__ == "__main__":
    main(build)
