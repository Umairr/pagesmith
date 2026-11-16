"""The dashboard: a small FastAPI app over the runs folder.

It reads what the studio writes (run.json and the board) and never touches a
model itself, apart from starting a new run as a background process.
"""

from __future__ import annotations

import hmac
import json
import re
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from pagesmith import __version__, config, workers
from pagesmith.audit import PAGE_FILES, audit_page
from pagesmith.board import Board
from pagesmith.brief import Brief
from pagesmith.store import Run, list_runs

STATIC = Path(__file__).resolve().parent / "static"
_RUN_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[a-z0-9-]{1,24}$")
_MEDIA = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}

app = FastAPI(title="Pagesmith", version=__version__, docs_url="/api/docs", redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _run(run_id: str) -> Run:
    if not _RUN_ID.match(run_id):
        raise HTTPException(404, "Run not found")
    run = Run(config.RUNS_DIR / run_id)
    if not run.state_path.exists():
        raise HTTPException(404, "Run not found")
    return run


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/meta")
def meta() -> dict:
    briefs = sorted(p.stem for p in config.BRIEFS_DIR.glob("*.json"))
    return {
        "version": __version__,
        "token_required": bool(config.ACCESS_TOKEN),
        "target": config.TARGET_SCORE,
        "rounds": config.MAX_ROUNDS,
        "builders": [{k: b[k] for k in ("key", "name", "colour")} for b in workers.BUILDERS],
        "briefs": briefs,
        "orchestrator_model": config.ORCHESTRATOR_MODEL,
        "builder_model": config.BUILDER_MODEL,
    }


@app.get("/api/briefs/{name}")
def get_brief(name: str) -> dict:
    path = config.BRIEFS_DIR / f"{Path(name).name}.json"
    if not path.exists():
        raise HTTPException(404, "Brief not found")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/runs")
def runs() -> list[dict]:
    return list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    run = _run(run_id)
    state = run.read()
    state["board"] = Board(run.board_path).list() if run.board_path.exists() else []
    return state


@app.get("/api/runs/{run_id}/variants/{key}/audit")
def variant_audit(run_id: str, key: str) -> dict:
    run = _run(run_id)
    if key not in run.read()["variants"]:
        raise HTTPException(404, "Variant not found")
    return audit_page(run.page_dir(key), run.brief).to_dict()


@app.get("/runs/{run_id}/pages/{key}/", include_in_schema=False)
@app.get("/runs/{run_id}/pages/{key}/{filename}", include_in_schema=False)
def page_file(run_id: str, key: str, filename: str = "index.html") -> FileResponse:
    run = _run(run_id)
    if key not in workers.BY_KEY or filename not in PAGE_FILES:
        raise HTTPException(404, "Not found")
    path = run.page_dir(key) / filename
    if not path.exists():
        raise HTTPException(404, "Not built yet")
    return FileResponse(path, media_type=_MEDIA[path.suffix])


class NewRun(BaseModel):
    brief: dict
    target: int = Field(default=config.TARGET_SCORE, ge=50, le=100)
    rounds: int = Field(default=config.MAX_ROUNDS, ge=1, le=5)
    builders: list[str] = Field(default_factory=lambda: [b["key"] for b in workers.BUILDERS])


@app.post("/api/runs", status_code=201)
def start_run(body: NewRun, x_access_token: str = Header(default="")) -> dict:
    if config.ACCESS_TOKEN and not hmac.compare_digest(x_access_token, config.ACCESS_TOKEN):
        raise HTTPException(401, "A valid access token is required to start runs.")
    try:
        brief = Brief.model_validate(body.brief)
    except ValidationError as exc:
        raise HTTPException(422, f"Invalid brief: {exc.errors()[0]['msg']}") from exc
    chosen = [b["key"] for b in workers.select(body.builders)][: len(brief.audiences)]
    run = Run.create(brief, target=body.target, max_rounds=body.rounds)
    run.update(lambda s: s.update(builders=chosen))
    log = open(run.dir / "studio.log", "w", encoding="utf-8")  # noqa: SIM115 - handed to the child
    subprocess.Popen([sys.executable, "-m", "pagesmith", "run", "--run-dir", str(run.dir)],
                     stdout=log, stderr=subprocess.STDOUT, cwd=str(config.PROJECT_ROOT), start_new_session=True)
    return {"id": run.id}
