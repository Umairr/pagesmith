"""Terminal output: the live board drawn with rich while the builders work."""

from __future__ import annotations

import logging
import warnings
from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable, Iterator

from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

if TYPE_CHECKING:
    from pagesmith.orchestrator import Studio

console = Console()

_MARK = {"done": "✓", "in_progress": "›", "failed": "✗", "pending": "·"}


def silence_libraries() -> None:
    """Keep the terminal readable: drop framework banners and experimental-feature notices."""
    warnings.filterwarnings("ignore", message=r".*\[EXPERIMENTAL\].*")
    warnings.filterwarnings("ignore", category=UserWarning)
    for name in ("google_genai._api_client", "google_adk", "LiteLLM", "litellm", "httpx"):
        logging.getLogger(name).setLevel(logging.ERROR)


def render(studio: "Studio") -> Group:
    todos = studio.board.list()
    variants = studio.run.read()["variants"]
    lines: list[Text] = []
    for goal in (t for t in todos if t["parent_id"] is None):
        v = variants.get(goal["owner"], {})
        colour = v.get("colour", "white")
        head = Text(f"{_MARK.get(goal['status'], '·')} ", style=colour)
        head.append(f"{v.get('framework', goal['owner'])}", style=f"bold {colour}")
        head.append(f"  round {goal['round']}  ", style="dim")
        head.append(v.get("audience", ""), style=colour)
        lines.append(head)
        for step in (t for t in todos if t["parent_id"] == goal["id"]):
            style = {"done": "dim strike", "in_progress": "bold", "failed": "red"}.get(step["status"], "")
            line = Text(f"    {_MARK.get(step['status'], '·')} ", style=colour)
            line.append(step["task"], style=style)
            lines.append(line)
    return Group(*lines) if lines else Group(Text("Waiting for builders to post their plans…", style="dim"))


@contextmanager
def live_board(studio: "Studio") -> Iterator[Callable[[], None]]:
    with Live(render(studio), console=console, refresh_per_second=4, transient=False) as live:
        yield lambda: live.update(render(studio))
