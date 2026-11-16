"""Landing page builder on Pydantic AI."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from pagesmith.workers._entry import main


async def build(tools, instructions: str, message: str, model: str) -> None:
    agent = Agent(f"openai-chat:{model}", instructions=instructions, tools=tools)
    await agent.run(message, usage_limits=UsageLimits(request_limit=80))


if __name__ == "__main__":
    main(build)
