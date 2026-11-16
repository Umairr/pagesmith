from pathlib import Path

from pagesmith.board import Board


def test_goal_and_step_lifecycle(tmp_path: Path) -> None:
    board = Board(tmp_path / "board.sqlite")
    board.init()
    goal = board.add_goal("Build the page", owner="agno", round_no=2)
    steps = [board.add_step(goal, s) for s in ("Write HTML", "Write CSS")]

    assert {t["owner"] for t in board.list()} == {"agno"}
    assert {t["round"] for t in board.list()} == {2}

    board.claim(goal)
    board.complete(steps[0], "done")
    assert board.get(goal)["status"] == "in_progress"

    board.close_open_steps(goal)
    board.complete(goal, "shipped")
    assert all(t["status"] == "done" for t in board.list(goal))


def test_failed_goal_keeps_reason(tmp_path: Path) -> None:
    board = Board(tmp_path / "board.sqlite")
    board.init()
    goal = board.add_goal("Build", owner="maf")
    board.fail(goal, "timed out")
    assert board.get(goal)["status"] == "failed"
    assert board.get(goal)["result"] == "timed out"
