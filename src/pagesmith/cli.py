"""Command line interface.

    pagesmith run --brief briefs/ledgerly.json        build, score and iterate
    pagesmith serve                                   open the dashboard
    pagesmith audit runs/<id>/pages/agno --brief ...  score any page folder
    pagesmith runs                                    list past runs
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.table import Table


def _cmd_run(args: argparse.Namespace) -> None:
    from pagesmith import config, workers
    from pagesmith.brief import load_brief
    from pagesmith.console import console
    from pagesmith.orchestrator import run_studio
    from pagesmith.store import Run

    from pagesmith.models import ModelConfigError

    if args.model:
        config.use_model(args.model)
    try:
        config.check_models()
    except ModelConfigError as exc:
        sys.exit(f"{exc}\nCopy .env.example to .env and add a key for OpenAI, Anthropic, Gemini or OpenRouter.")

    if args.run_dir:
        run = Run(args.run_dir)
        state = run.read()
        builders = workers.select(state.get("builders") or None)
    else:
        brief = load_brief(args.brief)
        builders = workers.select(args.builders, args.skip)[: len(brief.audiences)]
        reference = None
        if args.reference:
            from pagesmith.style import describe_reference, guess_mime, merge

            reference = (Path(args.reference).read_bytes(), guess_mime(args.reference))
            found, source = describe_reference(*reference)
            brief = brief.model_copy(update={"style": merge(brief.style, found)})
            swatches = "  ".join(f"{role} {hex_}" for role, hex_ in brief.style.palette().items())
            console.print(f"Style from {args.reference} ({'read by the model' if source == 'model' else 'pixel palette'}): {swatches}")
        run = Run.create(brief, target=args.target, max_rounds=args.rounds, reference=reference)
        run.update(lambda s: s.update(builders=[b["key"] for b in builders]))

    state = run.read()
    console.print(f"[bold]Pagesmith[/bold] · {state['brief']['product']} · target {state['target']} · "
                  f"up to {state['max_rounds']} rounds · run [cyan]{run.id}[/cyan]")
    console.print(f"Lead: {config.ORCHESTRATOR_MODEL}   Builders: {config.BUILDER_MODEL}  "
                  f"({', '.join(b['name'] for b in builders)})\n")

    run_studio(run, builders)
    _print_results(run.read())
    console.print(f"\nPages: {run.pages_dir}\nDashboard: [cyan]pagesmith serve[/cyan] → http://localhost:8000/#/runs/{run.id}")


def _print_results(state: dict) -> None:
    from pagesmith.console import console

    table = Table(title="Final scores", show_lines=False)
    for col in ("Builder", "Audience", "Rounds", "Score", "Status"):
        table.add_column(col)
    for v in state["variants"].values():
        history = " → ".join(f"{r['score']:g}" for r in v.get("rounds", []))
        last = v["rounds"][-1]["score"] if v.get("rounds") else 0
        colour = "green" if last >= state["target"] else "yellow"
        table.add_row(v["framework"], v["audience"], history, f"[{colour}]{last:g}[/{colour}]", v.get("status", ""))
    console.print(table)
    if state.get("summary"):
        console.print("\n" + state["summary"], markup=False)


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("pagesmith.web.app:app", host=args.host, port=args.port, reload=False)


def _cmd_audit(args: argparse.Namespace) -> None:
    from pagesmith.audit import audit_page
    from pagesmith.brief import load_brief

    report = audit_page(Path(args.page_dir), load_brief(args.brief))
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return
    from pagesmith.console import console

    console.print(f"[bold]{report.score:g}/100[/bold] (grade {report.grade})")
    for cat in report.categories.values():
        console.print(f"  {cat['label']:<14} {cat['score']:>5g} / {cat['max']:g}")
    console.print("\nWhere points were lost:\n" + report.feedback(limit=20), markup=False, soft_wrap=True)


def _cmd_runs(_: argparse.Namespace) -> None:
    from pagesmith.console import console
    from pagesmith.store import list_runs

    table = Table(title="Runs")
    for col in ("Run", "Product", "Status", "Variants", "Best"):
        table.add_column(col)
    for r in list_runs():
        table.add_row(r["id"], r["product"], r["status"], str(r["variants"]), f"{r['best_score'] or 0:g}")
    console.print(table)


def main(argv: list[str] | None = None) -> None:
    from pagesmith import config

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="pagesmith", description="Multi-agent landing page studio.")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="build, score and iterate on landing page variants")
    src = run.add_mutually_exclusive_group(required=True)
    src.add_argument("--brief", help="path to a product brief (JSON)")
    src.add_argument("--run-dir", help="execute a run that was already created (used by the dashboard)")
    run.add_argument("--target", type=int, default=config.TARGET_SCORE, help="score every variant must reach")
    run.add_argument("--rounds", type=int, default=config.MAX_ROUNDS, help="max rounds per builder, first build included")
    run.add_argument("--builders", nargs="*", help="only these builders (strands pydantic agno maf)")
    run.add_argument("--skip", nargs="*", default=[], help="leave these builders out")
    run.add_argument("--reference", help="screenshot of a page whose colours and style the variants should follow")
    run.add_argument("--model", help="provider/model for the lead and every builder, e.g. anthropic/claude-sonnet-5-5")
    run.set_defaults(fn=_cmd_run)

    serve = sub.add_parser("serve", help="start the dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(fn=_cmd_serve)

    audit = sub.add_parser("audit", help="score one page folder against a brief")
    audit.add_argument("page_dir")
    audit.add_argument("--brief", required=True)
    audit.add_argument("--json", action="store_true")
    audit.set_defaults(fn=_cmd_audit)

    runs = sub.add_parser("runs", help="list past runs")
    runs.set_defaults(fn=_cmd_runs)

    args = parser.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
