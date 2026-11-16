"""The studio lead: a Google ADK agent that runs the build, score, revise loop.

The lead owns the decisions (which audience each builder takes, what angle to
push, what to prioritise in a revision, when to stop). Its tools own the
mechanics: starting builder processes, waiting on the board, running the audit
and recording every score so the dashboard can chart progress round by round.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time

from pagesmith import config
from pagesmith.audit import audit_page
from pagesmith.board import Board
from pagesmith.console import console, live_board
from pagesmith.prompts import BUILD_TASK, ORCHESTRATOR_PROMPT, PAGE_RULES, REVISE_TASK
from pagesmith.store import Run
from pagesmith.workers import launch_argv

_APP = "pagesmith"


class Studio:
    """Working state shared by the lead's tools. The model never sees this object."""

    def __init__(self, run: Run, builders: list[dict]) -> None:
        self.run = run
        self.board = Board(run.board_path)
        self.builders = {b["key"]: b for b in builders}
        self.procs: dict[str, subprocess.Popen] = {}
        self.goals: dict[str, int] = {}
        state = run.read()
        self.target: int = state["target"]
        self.max_rounds: int = state["max_rounds"]
        self.brief = run.brief

    # helpers -------------------------------------------------------------------------
    def variant(self, key: str) -> dict:
        return self.run.read()["variants"].get(key, {})

    def set_variant(self, variant_key: str, /, **fields) -> None:
        self.run.update(lambda s: s["variants"].setdefault(variant_key, {}).update(fields))

    def _launch(self, key: str, goal_id: int) -> None:
        log_path = self.run.dir / "logs" / f"{key}-goal{goal_id}.log"
        log_path.parent.mkdir(exist_ok=True)
        group = {} if sys.platform == "win32" else {"start_new_session": True}
        with open(log_path, "w", encoding="utf-8") as log:
            self.procs[key] = subprocess.Popen(
                launch_argv(self.builders[key], str(self.run.dir), goal_id),
                stdout=log, stderr=subprocess.STDOUT, cwd=str(config.PROJECT_ROOT), env=os.environ.copy(), **group,
            )
        self.goals[key] = goal_id

    @staticmethod
    def _stop(proc: subprocess.Popen) -> None:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    def score(self, key: str) -> dict:
        report = audit_page(self.run.page_dir(key), self.brief)
        v = self.variant(key)
        rounds = list(v.get("rounds", []))
        round_no = v.get("round", 1)
        entry = {"round": round_no, "score": report.score, "grade": report.grade,
                 "categories": report.categories, "at": time.time()}
        rounds = [r for r in rounds if r["round"] != round_no] + [entry]
        passed = report.score >= self.target
        status = "passed" if passed else ("out_of_rounds" if round_no >= self.max_rounds else "below_target")
        self.set_variant(key, rounds=rounds, status=status, feedback=report.feedback(limit=8))
        return {"report": report, "status": status, "round": round_no}

    def ranking(self) -> str:
        """Every scored variant, best first, with history and the points it still loses."""
        variants = [v for v in self.run.read()["variants"].values() if v.get("rounds")]
        variants.sort(key=lambda v: v["rounds"][-1]["score"], reverse=True)
        lines = [f"Ranking (target {self.target}), best first:"]
        for i, v in enumerate(variants, 1):
            last = v["rounds"][-1]
            cats = ", ".join(f"{c['label']} {c['score']:g}/{c['max']:g}" for c in last["categories"].values())
            history = " -> ".join(f"{r['score']:g}" for r in v["rounds"])
            lines.append(f"{i}. {v['key']} ({v['audience']}): {last['score']:g}/100 [{v['status']}], "
                         f"round {v['round']}/{self.max_rounds}, history {history}. {cats}")
            if last["score"] < self.target:
                lines += ["   " + line for line in v.get("feedback", "").splitlines()[:5]]
        return "\n".join(lines)

    def summary_table(self) -> str:
        lines = []
        for key, v in self.run.read()["variants"].items():
            history = " -> ".join(f"{r['score']:g}" for r in v.get("rounds", [])) or "not scored"
            lines.append(f"{key} ({v.get('audience', '?')}): {history} [{v.get('status', '?')}], round {v.get('round', 1)}/{self.max_rounds}")
        return "\n".join(lines)


def make_tools(studio: Studio) -> list:
    rules = PAGE_RULES

    def assign_variant(framework: str, audience: str, angle: str) -> str:
        """Start one builder on its landing page variant. Returns immediately; the builder works
        in the background. Start every builder, then call wait_for_team.

        Args:
            framework: the builder's framework key.
            audience: the audience segment this variant targets (one from the brief, each used once).
            angle: one or two sentences of positioning for that audience: what they care about,
                which features to lead with, which objection to answer.
        """
        if framework not in studio.builders:
            return f"Unknown framework '{framework}'. Your team: {', '.join(studio.builders)}."
        if studio.variant(framework):
            return f"{framework} already has a variant ({studio.variant(framework)['audience']})."
        b = studio.builders[framework]
        task = BUILD_TASK.format(audience=audience, product=studio.brief.product, angle=angle,
                                 brief=studio.brief.as_prompt(), rules=rules, target=studio.target, key=framework)
        goal_id = studio.board.add_goal(task, owner=framework, round_no=1)
        studio.set_variant(framework, key=framework, framework=b["name"], colour=b["colour"], audience=audience,
                           angle=angle, round=1, status="building", rounds=[], goals=[goal_id], notes=[])
        studio.run.log(f"{b['name']} assigned: {audience}", "assign")
        studio._launch(framework, goal_id)
        return f"{b['name']} is building the '{audience}' variant (goal #{goal_id})."

    async def wait_for_team() -> str:
        """Wait until every running builder has finished, showing the live board. Returns the board summary."""
        procs = {k: p for k, p in studio.procs.items() if p.poll() is None}
        if not procs:
            return "No builders are running.\n" + studio.summary_table()
        started = time.monotonic()
        with live_board(studio) as refresh:
            while any(p.poll() is None for p in procs.values()):
                refresh()
                if time.monotonic() - started > config.BUILDER_TIMEOUT_S:
                    for key, p in procs.items():
                        if p.poll() is None:
                            studio._stop(p)
                            studio.board.fail(studio.goals[key], "Stopped: exceeded the time budget.")
                            studio.run.log(f"{studio.builders[key]['name']} timed out", "warn")
                    break
                await asyncio.sleep(0.4)
            refresh()
        for key in procs:
            goal = studio.board.get(studio.goals[key])
            outcome = goal["status"] if goal else "unknown"
            studio.set_variant(key, status="built" if outcome == "done" else "build_failed")
            studio.run.log(f"{studio.builders[key]['name']} finished round {studio.variant(key).get('round', 1)} ({outcome})", "build")
        return "Team finished.\n" + studio.summary_table()

    def score_variants() -> str:
        """Run the automated audit on every variant that changed since it was last scored, and
        return the ranking: each score, its category breakdown, and where points were lost."""
        out = []
        for key, v in studio.run.read()["variants"].items():
            if key in studio.procs and studio.procs[key].poll() is None:
                out.append(f"{key}: still building, wait_for_team first.")
                continue
            if any(r["round"] == v.get("round", 1) for r in v.get("rounds", [])):
                continue  # this round is already scored and the page has not changed since
            res = studio.score(key)
            studio.run.log(f"{studio.builders[key]['name']} scored {res['report'].score:g} in round {res['round']}", "score")
        return studio.ranking() + ("\n" + "\n".join(out) if out else "")

    def request_revision(framework: str, notes: str) -> str:
        """Send a builder back to improve its variant. The builder automatically receives the
        audit's list of lost points; add your own priorities in notes. Returns immediately.

        Args:
            framework: the builder's framework key.
            notes: the lead's guidance for this round, in two or three sentences.
        """
        v = studio.variant(framework)
        if not v:
            return f"{framework} has no variant yet."
        if studio.procs.get(framework) and studio.procs[framework].poll() is None:
            return f"{framework} is still working; wait_for_team first."
        if not v.get("rounds"):
            return f"Score {framework} with score_variants before revising it."
        if v["rounds"][-1]["score"] >= studio.target:
            return f"{framework} already meets the target ({v['rounds'][-1]['score']:g})."
        if v["round"] >= studio.max_rounds:
            return f"{framework} has used all {studio.max_rounds} rounds."
        round_no = v["round"] + 1
        task = REVISE_TASK.format(audience=v["audience"], product=studio.brief.product, round_no=round_no,
                                  score=v["rounds"][-1]["score"], target=studio.target,
                                  feedback=v.get("feedback", ""), notes=notes, rules=rules)
        goal_id = studio.board.add_goal(task, owner=framework, round_no=round_no)
        studio.set_variant(framework, round=round_no, status="revising", goals=v.get("goals", []) + [goal_id],
                           notes=v.get("notes", []) + [{"round": round_no, "notes": notes}])
        studio.run.log(f"{studio.builders[framework]['name']} sent back for round {round_no}", "revise")
        studio._launch(framework, goal_id)
        return f"{framework} is revising (round {round_no}/{studio.max_rounds}, goal #{goal_id})."

    def publish_results(summary: str) -> str:
        """Finish the run: record the final summary shown on the dashboard. Call this once, last.

        Args:
            summary: three to five sentences: the top-ranked variant from the latest ranking,
                the final scores, and what moved them between rounds.
        """
        studio.run.update(lambda s: s.update(summary=summary))
        return "Published. You are done. Final ranking for reference:\n" + studio.ranking()

    return [assign_variant, wait_for_team, score_variants, request_revision, publish_results]


async def _drive(studio: Studio) -> None:
    from google.adk.agents import LlmAgent
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    team = "\n".join(f"- {k}: {b['name']}" for k, b in studio.builders.items())
    instruction = ORCHESTRATOR_PROMPT.format(
        brief=studio.brief.as_prompt(), team=team, audiences="; ".join(studio.brief.audiences),
        target=studio.target, max_rounds=studio.max_rounds,
    )
    agent = LlmAgent(name="studio_lead", model=config.orchestrator_llm(), instruction=instruction, tools=make_tools(studio))
    runner = InMemoryRunner(agent=agent, app_name=_APP)
    try:
        session = await runner.session_service.create_session(app_name=_APP, user_id="lead")
        async for event in runner.run_async(
            user_id="lead", session_id=session.id,
            new_message=types.UserContent("Run the studio: build every variant and iterate until they meet the target."),
            run_config=RunConfig(max_llm_calls=config.ORCHESTRATOR_MAX_CALLS),
        ):
            for call in event.get_function_calls():
                console.print(f"[dim]lead → {call.name}[/dim]")
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text and part.text.strip():
                        console.print(part.text.strip(), style="italic", markup=False)
    finally:
        await runner.close()


def run_studio(run: Run, builders: list[dict]) -> Studio:
    """Run the lead agent to completion, then make sure the run ends in a consistent state."""
    from pagesmith.console import silence_libraries

    silence_libraries()
    studio = Studio(run, builders)
    studio.board.init()
    run.update(lambda s: s.update(status="running"))
    run.log(f"Run started with {len(builders)} builders, target {studio.target}", "start")
    status = "completed"
    try:
        asyncio.run(_drive(studio))
    except KeyboardInterrupt:
        status = "cancelled"
    except Exception as exc:
        console.print(f"[red]The lead stopped early: {type(exc).__name__}: {str(exc)[:200]}[/red]")
        run.log(f"Lead stopped early: {type(exc).__name__}", "warn")
        status = "completed_with_errors"
    finally:
        for p in studio.procs.values():
            if p.poll() is None:
                studio._stop(p)

    # Safety net: every variant ends with a recorded score, and the run has a summary.
    for key, v in run.read()["variants"].items():
        if not v.get("rounds") or v.get("status") in {"built", "building", "revising", "build_failed"}:
            studio.score(key)
    state = run.read()
    if not state.get("summary"):
        best = max(state["variants"].values(), key=lambda v: v["rounds"][-1]["score"], default=None)
        if best:
            run.update(lambda s: s.update(summary=f"Best variant: {best['framework']} for {best['audience']} "
                                                  f"at {best['rounds'][-1]['score']:g}/100."))
    run.update(lambda s: s.update(status=status, finished_at=time.time()))
    run.log("Run finished", "finish")
    return studio
