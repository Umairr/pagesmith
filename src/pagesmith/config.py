"""Runtime settings, read once from the environment (and a local .env, if present)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

from pagesmith import models  # noqa: E402  (reads the environment loaded above)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(os.environ.get("PAGESMITH_RUNS_DIR", PROJECT_ROOT / "runs")).resolve()
BRIEFS_DIR = PROJECT_ROOT / "briefs"

# Models are "provider/model" strings: openai/..., anthropic/..., gemini/...,
# openrouter/..., or custom/... for any OpenAI-compatible endpoint. Leave them
# unset and the first provider with an API key in the environment is used.
DEFAULT_MODEL = os.environ.get("PAGESMITH_MODEL", "")
ORCHESTRATOR_SPEC = models.parse(os.environ.get("PAGESMITH_ORCHESTRATOR_MODEL") or DEFAULT_MODEL)
BUILDER_SPEC = models.parse(os.environ.get("PAGESMITH_BUILDER_MODEL") or DEFAULT_MODEL)
ORCHESTRATOR_MODEL = ORCHESTRATOR_SPEC.id
BUILDER_MODEL = BUILDER_SPEC.id

TARGET_SCORE = int(os.environ.get("PAGESMITH_TARGET_SCORE", "95"))
MAX_ROUNDS = int(os.environ.get("PAGESMITH_MAX_ROUNDS", "3"))
BUILDER_TIMEOUT_S = int(os.environ.get("PAGESMITH_BUILDER_TIMEOUT_S", "420"))
ORCHESTRATOR_MAX_CALLS = int(os.environ.get("PAGESMITH_ORCHESTRATOR_MAX_CALLS", "60"))

# Optional shared secret for starting runs from the dashboard. When set, the
# "New run" form asks for it, so a public deployment cannot spend your credits.
ACCESS_TOKEN = os.environ.get("PAGESMITH_ACCESS_TOKEN", "")


def use_model(value: str) -> None:
    """Point the lead and the builders at one model (the CLI's --model flag).

    Written back to the environment so builder subprocesses inherit it.
    """
    global ORCHESTRATOR_SPEC, BUILDER_SPEC, ORCHESTRATOR_MODEL, BUILDER_MODEL
    ORCHESTRATOR_SPEC = BUILDER_SPEC = models.parse(value)
    ORCHESTRATOR_MODEL = BUILDER_MODEL = BUILDER_SPEC.id
    os.environ["PAGESMITH_ORCHESTRATOR_MODEL"] = os.environ["PAGESMITH_BUILDER_MODEL"] = BUILDER_SPEC.id


def check_models() -> None:
    """Fail early, with a readable message, when a configured provider has no key."""
    ORCHESTRATOR_SPEC.check()
    BUILDER_SPEC.check()


def orchestrator_llm():
    """The model object handed to the ADK orchestrator (routed through LiteLLM)."""
    from google.adk.models.lite_llm import LiteLlm

    spec = ORCHESTRATOR_SPEC
    extra = {"api_base": spec.base_url} if spec.provider.name == "custom" else {}
    if spec.max_tokens:
        extra["max_tokens"] = spec.max_tokens
    return LiteLlm(model=spec.litellm_id(), api_key=spec.require_key(), **extra)
