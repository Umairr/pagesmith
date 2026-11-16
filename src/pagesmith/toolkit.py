"""The tools a builder works with, as plain typed Python functions.

Every framework accepts typed functions with docstrings as tools (Strands needs its
@tool decorator on top), so one toolkit serves the whole team. Each toolkit is bound
to a single goal on the board and a single page folder, which is the builder's
whole world: it cannot read or write anything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from pagesmith.audit import PAGE_FILES, audit_page
from pagesmith.board import Board
from pagesmith.store import Run

MAX_FILE_BYTES = 120_000


def build_toolkit(run: Run, key: str, goal_id: int) -> list[Callable]:
    board = Board(run.board_path)
    page_dir = run.page_dir(key)
    page_dir.mkdir(parents=True, exist_ok=True)
    brief = run.brief
    target = run.read()["target"]

    def _path(filename: str) -> Path:
        name = Path(filename).name
        if name not in PAGE_FILES:
            raise ValueError(f"You can only use {', '.join(PAGE_FILES)}.")
        return page_dir / name

    def read_task() -> dict:
        """Return your assignment (the goal) and the steps you have planned so far, with their status."""
        todos = board.list(goal_id)
        goal = next(t for t in todos if t["id"] == goal_id)
        steps = [{"id": t["id"], "task": t["task"], "status": t["status"]} for t in todos if t["id"] != goal_id]
        return {"goal_id": goal_id, "assignment": goal["task"], "steps": steps}

    def plan_steps(steps: list[str]) -> dict:
        """Post your plan to the shared board as an ordered list of short, concrete steps (4 to 6)."""
        ids = [board.add_step(goal_id, s.strip()) for s in steps if s.strip()]
        return {"step_ids": ids}

    def complete_step(step_id: int, result: str) -> dict:
        """Tick one of your steps off the board with a one-line summary of what you did."""
        todo = board.get(step_id)
        if not todo or todo["parent_id"] != goal_id:
            return {"error": f"Step {step_id} is not one of your steps."}
        board.complete(step_id, result)
        return {"step_id": step_id, "status": "done"}

    def write_file(filename: str, content: str) -> str:
        """Create or overwrite one of your page files: index.html, styles.css or script.js."""
        try:
            path = _path(filename)
        except ValueError as exc:
            return str(exc)
        data = content.encode("utf-8")
        if len(data) > MAX_FILE_BYTES:
            return f"Refused: {path.name} would be {len(data) // 1024} KB; keep each file well under 100 KB."
        path.write_bytes(data)
        return f"Wrote {path.name} ({len(data):,} bytes)."

    def read_file(filename: str) -> str:
        """Read back one of your page files: index.html, styles.css or script.js."""
        try:
            path = _path(filename)
        except ValueError as exc:
            return str(exc)
        return path.read_text(encoding="utf-8") if path.exists() else f"{path.name} does not exist yet."

    def run_audit() -> dict:
        """Score your page with the automated audit (0 to 100) and list where points were lost, biggest first."""
        report = audit_page(page_dir, brief)
        return {
            "score": report.score,
            "target": target,
            "grade": report.grade,
            "categories": {k: f"{v['score']}/{v['max']}" for k, v in report.categories.items()},
            "lost_points": report.feedback(limit=10),
        }

    def finish(summary: str) -> str:
        """Close your assignment on the board with a short summary. Call this last."""
        board.close_open_steps(goal_id)
        board.complete(goal_id, summary)
        return "Assignment closed. You can stop now."

    return [read_task, plan_steps, complete_step, write_file, read_file, run_audit, finish]
