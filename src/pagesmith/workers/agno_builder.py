"""Landing page builder on Agno."""

from __future__ import annotations

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from pagesmith.workers._entry import main


async def build(tools, instructions: str, message: str, model: str) -> None:
    agent = Agent(model=OpenAIChat(id=model), instructions=instructions, tools=tools, tool_call_limit=80)
    await agent.arun(input=message)


if __name__ == "__main__":
    main(build)
