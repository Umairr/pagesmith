"""Shared process entry point for every builder.

    python -m pagesmith.workers.<framework>_builder <run_dir> <key> <goal_id>

Parses the arguments, binds the toolkit to the goal, claims it on the board, hands
the work to the framework-specific coroutine and, whatever happens, leaves the
goal in a final state so the orchestrator never waits on a ghost.
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from typing import Awaitable, Callable

from pagesmith import config
from pagesmith.board import Board
from pagesmith.prompts import BUILDER_INSTRUCTIONS
from pagesmith.store import Run
from pagesmith.toolkit import build_toolkit

BuilderFn = Callable[[list[Callable], str, str, str], Awaitable[None]]


def main(build: BuilderFn) -> None:
    if len(sys.argv) != 4:
        raise SystemExit("usage: python -m pagesmith.workers.<builder> <run_dir> <key> <goal_id>")
    run_dir, key, goal_id = sys.argv[1], sys.argv[2], int(sys.argv[3])
    run = Run(run_dir)
    board = Board(run.board_path)
    board.claim(goal_id)
    tools = build_toolkit(run, key, goal_id)
    message = (
        f"You have claimed goal #{goal_id} on the board. Call read_task to see your assignment, "
        "then plan, build, audit and iterate. Call finish when you are done."
    )
    try:
        asyncio.run(build(tools, BUILDER_INSTRUCTIONS, message, config.BUILDER_MODEL))
    except Exception as exc:  # the orchestrator reads the reason off the board
        traceback.print_exc()
        board.fail(goal_id, f"{type(exc).__name__}: {str(exc)[:240]}")
        raise SystemExit(1) from exc

    goal = board.get(goal_id)
    if goal and goal["status"] != "done":
        board.close_open_steps(goal_id)
        board.complete(goal_id, "Finished without a closing summary.")
