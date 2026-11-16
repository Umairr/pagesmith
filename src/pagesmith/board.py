"""The shared task board: one SQLite file every agent in a run reads and writes.

The orchestrator posts one goal per builder. A builder breaks its goal into steps
on the board, ticks each off as it works, and closes the goal when done. WAL mode
plus a busy timeout let several processes write at once without locking each
other out, and the dashboard reads the same file to draw the board live.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   INTEGER,
    owner       TEXT NOT NULL DEFAULT '',
    round       INTEGER NOT NULL DEFAULT 1,
    task        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    result      TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
)
"""


class Board:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def add_goal(self, task: str, owner: str, round_no: int = 1) -> int:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO todos (owner, round, task, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (owner, round_no, task, now, now),
            )
            return int(cur.lastrowid)

    def add_step(self, goal_id: int, task: str) -> int:
        now = time.time()
        with self._connect() as conn:
            goal = conn.execute("SELECT owner, round FROM todos WHERE id = ?", (goal_id,)).fetchone()
            owner, round_no = (goal["owner"], goal["round"]) if goal else ("", 1)
            cur = conn.execute(
                "INSERT INTO todos (parent_id, owner, round, task, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (goal_id, owner, round_no, task, now, now),
            )
            return int(cur.lastrowid)

    def get(self, todo_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
            return dict(row) if row else None

    def list(self, goal_id: int | None = None) -> list[dict]:
        with self._connect() as conn:
            if goal_id is None:
                rows = conn.execute("SELECT * FROM todos ORDER BY id").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM todos WHERE id = ? OR parent_id = ? ORDER BY id", (goal_id, goal_id)
                ).fetchall()
            return [dict(r) for r in rows]

    def _set(self, todo_id: int, status: str, result: str | None = None) -> None:
        with self._connect() as conn:
            if result is None:
                conn.execute("UPDATE todos SET status = ?, updated_at = ? WHERE id = ?", (status, time.time(), todo_id))
            else:
                conn.execute(
                    "UPDATE todos SET status = ?, result = ?, updated_at = ? WHERE id = ?",
                    (status, result, time.time(), todo_id),
                )

    def claim(self, todo_id: int) -> None:
        self._set(todo_id, "in_progress")

    def complete(self, todo_id: int, result: str) -> None:
        self._set(todo_id, "done", result)

    def fail(self, todo_id: int, reason: str) -> None:
        self._set(todo_id, "failed", reason)

    def close_open_steps(self, goal_id: int) -> None:
        """Tick off any steps a builder left open once its goal is done."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE todos SET status = 'done', updated_at = ? WHERE parent_id = ? AND status != 'done'",
                (time.time(), goal_id),
            )
