"""The builder roster: one landing page builder per agent framework.

Each builder runs as its own process, so the frameworks never share an event loop
or a dependency's global state, and a builder that hangs can be stopped on its own.
"""

from __future__ import annotations

import sys

BUILDERS = [
    {"key": "strands", "name": "AWS Strands", "module": "pagesmith.workers.strands_builder", "colour": "#f59e0b"},
    {"key": "pydantic", "name": "Pydantic AI", "module": "pagesmith.workers.pydantic_builder", "colour": "#ec4899"},
    {"key": "agno", "name": "Agno", "module": "pagesmith.workers.agno_builder", "colour": "#22c55e"},
    {"key": "maf", "name": "Microsoft Agent Framework", "module": "pagesmith.workers.maf_builder", "colour": "#3b82f6"},
]
BY_KEY = {b["key"]: b for b in BUILDERS}


def select(keys: list[str] | None = None, skip: list[str] | None = None) -> list[dict]:
    chosen = [b for b in BUILDERS if (not keys or b["key"] in keys) and b["key"] not in (skip or [])]
    if not chosen:
        raise SystemExit(f"No builders selected. Choose from: {', '.join(BY_KEY)}")
    return chosen


def launch_argv(builder: dict, run_dir: str, goal_id: int) -> list[str]:
    return [sys.executable, "-m", builder["module"], str(run_dir), builder["key"], str(goal_id)]
