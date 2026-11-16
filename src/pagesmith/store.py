"""Run storage: each run is a folder holding its brief, board, pages and score history.

    runs/<run_id>/
        run.json        brief, settings, status and the score history of every variant
        board.sqlite    the shared task board
        pages/<key>/    one landing page per builder (index.html, styles.css, script.js)

run.json is written only by the orchestrator process, always atomically, so the
dashboard can read it at any moment without seeing a half-written file.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from pagesmith import config
from pagesmith.brief import Brief


def new_run_id(product: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", product.lower()).strip("-")[:24] or "run"
    return f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{slug}"


class Run:
    def __init__(self, run_dir: str | Path) -> None:
        self.dir = Path(run_dir)

    # paths ---------------------------------------------------------------------------
    @property
    def id(self) -> str:
        return self.dir.name

    @property
    def state_path(self) -> Path:
        return self.dir / "run.json"

    @property
    def board_path(self) -> Path:
        return self.dir / "board.sqlite"

    @property
    def pages_dir(self) -> Path:
        return self.dir / "pages"

    def page_dir(self, key: str) -> Path:
        return self.pages_dir / key

    # state ---------------------------------------------------------------------------
    @classmethod
    def create(cls, brief: Brief, target: int, max_rounds: int, runs_dir: Path | None = None) -> "Run":
        run = cls((runs_dir or config.RUNS_DIR) / new_run_id(brief.product))
        run.pages_dir.mkdir(parents=True, exist_ok=True)
        run.write({
            "id": run.id,
            "status": "starting",
            "created_at": time.time(),
            "finished_at": None,
            "target": target,
            "max_rounds": max_rounds,
            "orchestrator_model": config.ORCHESTRATOR_MODEL,
            "builder_model": config.BUILDER_MODEL,
            "brief": brief.model_dump(),
            "variants": {},
            "log": [],
            "summary": "",
        })
        return run

    def read(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def write(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def update(self, fn) -> dict:
        state = self.read()
        fn(state)
        self.write(state)
        return state

    def log(self, message: str, kind: str = "info") -> None:
        self.update(lambda s: s["log"].append({"at": time.time(), "kind": kind, "message": message}))

    @property
    def brief(self) -> Brief:
        return Brief.model_validate(self.read()["brief"])


def list_runs(runs_dir: Path | None = None) -> list[dict]:
    root = runs_dir or config.RUNS_DIR
    if not root.exists():
        return []
    runs = []
    for path in sorted(root.iterdir(), reverse=True):
        state_file = path / "run.json"
        if not state_file.exists():
            continue
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        scores = [v["rounds"][-1]["score"] for v in state["variants"].values() if v.get("rounds")]
        runs.append({
            "id": state["id"],
            "product": state["brief"]["product"],
            "status": state["status"],
            "created_at": state["created_at"],
            "best_score": max(scores) if scores else None,
            "variants": len(state["variants"]),
        })
    return runs
