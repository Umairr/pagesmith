"""Landing page builder on Pydantic AI."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from pagesmith.models import ModelSpec
from pagesmith.workers._entry import main


def make_model(spec: ModelSpec):
    key = spec.require_key()
    if spec.provider.name == "anthropic":
        from anthropic import AsyncAnthropic
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        # Hand over a ready client: newer anthropic SDKs refuse the httpx client
        # Pydantic AI would otherwise inject.
        provider = AnthropicProvider(anthropic_client=AsyncAnthropic(api_key=key))
        return AnthropicModel(spec.name, provider=provider)
    if spec.provider.name == "gemini":
        from pydantic_ai.models.google import GoogleModel
        from pydantic_ai.providers.google import GoogleProvider

        return GoogleModel(spec.name, provider=GoogleProvider(api_key=key))

    from pydantic_ai.models.openai import OpenAIChatModel

    if spec.provider.name == "openrouter":
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        return OpenAIChatModel(spec.name, provider=OpenRouterProvider(api_key=key))

    from pydantic_ai.providers.openai import OpenAIProvider

    return OpenAIChatModel(spec.name, provider=OpenAIProvider(base_url=spec.base_url, api_key=key))


async def build(tools, instructions: str, message: str, spec: ModelSpec) -> None:
    settings = {"max_tokens": spec.max_tokens} if spec.max_tokens else None
    agent = Agent(make_model(spec), instructions=instructions, tools=tools, model_settings=settings)
    await agent.run(message, usage_limits=UsageLimits(request_limit=80))


if __name__ == "__main__":
    main(build)
