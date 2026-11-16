"""Runtime settings, read once from the environment (and a local .env, if present)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(os.environ.get("PAGESMITH_RUNS_DIR", PROJECT_ROOT / "runs")).resolve()
BRIEFS_DIR = PROJECT_ROOT / "briefs"

# The orchestrator runs on Google ADK. Any LiteLLM model id works ("openai/...",
# "anthropic/...", ...); a bare "gemini-..." id is sent to Gemini natively.
ORCHESTRATOR_MODEL = os.environ.get("PAGESMITH_ORCHESTRATOR_MODEL", "openai/gpt-5.4-mini")
# Builders talk to OpenAI-compatible chat completions.
BUILDER_MODEL = os.environ.get("PAGESMITH_BUILDER_MODEL", "gpt-5.4-mini")

TARGET_SCORE = int(os.environ.get("PAGESMITH_TARGET_SCORE", "95"))
MAX_ROUNDS = int(os.environ.get("PAGESMITH_MAX_ROUNDS", "3"))
BUILDER_TIMEOUT_S = int(os.environ.get("PAGESMITH_BUILDER_TIMEOUT_S", "420"))
ORCHESTRATOR_MAX_CALLS = int(os.environ.get("PAGESMITH_ORCHESTRATOR_MAX_CALLS", "60"))

# Optional shared secret for starting runs from the dashboard. When set, the
# "New run" form asks for it, so a public deployment cannot spend your credits.
ACCESS_TOKEN = os.environ.get("PAGESMITH_ACCESS_TOKEN", "")


def orchestrator_llm():
    """The model object handed to the ADK orchestrator."""
    if ORCHESTRATOR_MODEL.startswith("gemini"):
        return ORCHESTRATOR_MODEL
    from google.adk.models.lite_llm import LiteLlm

    return LiteLlm(model=ORCHESTRATOR_MODEL)
