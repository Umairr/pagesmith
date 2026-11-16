"""Landing page builder on AWS Strands Agents."""

from __future__ import annotations

from strands import Agent, tool

from pagesmith.models import ModelSpec
from pagesmith.workers._entry import main


def make_model(spec: ModelSpec):
    key = spec.require_key()
    if spec.provider.name == "anthropic":
        from strands.models.anthropic import AnthropicModel

        return AnthropicModel(client_args={"api_key": key}, model_id=spec.name, max_tokens=spec.max_tokens)
    if spec.provider.name == "gemini":
        from strands.models.gemini import GeminiModel

        return GeminiModel(
            client_args={"api_key": key}, model_id=spec.name, params={"max_output_tokens": spec.max_tokens}
        )

    from strands.models.openai import OpenAIModel

    client_args = {"api_key": key}
    if spec.base_url:
        client_args["base_url"] = spec.base_url
    params = {"max_tokens": spec.max_tokens} if spec.max_tokens else None
    return OpenAIModel(client_args=client_args, model_id=spec.name, params=params)


async def build(tools, instructions: str, message: str, spec: ModelSpec) -> None:
    agent = Agent(
        model=make_model(spec),
        system_prompt=instructions,
        tools=[tool(fn) for fn in tools],
        callback_handler=None,
    )
    await agent.invoke_async(message)


if __name__ == "__main__":
    main(build)
