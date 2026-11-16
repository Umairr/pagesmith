"""Landing page builder on Microsoft Agent Framework."""

from __future__ import annotations

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

from pagesmith.workers._entry import main


async def build(tools, instructions: str, message: str, model: str) -> None:
    agent = Agent(client=OpenAIChatClient(model=model), instructions=instructions, tools=tools)
    await agent.run(message)


if __name__ == "__main__":
    main(build)
