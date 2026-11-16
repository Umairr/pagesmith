"""Landing page builder on AWS Strands Agents."""

from __future__ import annotations

import os

from strands import Agent, tool
from strands.models.openai import OpenAIModel

from pagesmith.workers._entry import main


async def build(tools, instructions: str, message: str, model: str) -> None:
    agent = Agent(
        model=OpenAIModel(client_args={"api_key": os.environ["OPENAI_API_KEY"]}, model_id=model),
        system_prompt=instructions,
        tools=[tool(fn) for fn in tools],
        callback_handler=None,
    )
    await agent.invoke_async(message)


if __name__ == "__main__":
    main(build)
