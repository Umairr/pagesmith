"""Model provider selection.

Every model setting is a ``provider/model`` string, for example::

    openai/gpt-5.4-mini
    anthropic/claude-opus-5-5
    gemini/gemini-3.7-flash
    openrouter/openai/gpt-5.4-mini      (everything after "openrouter/" is the OpenRouter id)
    custom/llama-3.3-70b                (any OpenAI-compatible endpoint, see PAGESMITH_BASE_URL)

A bare id with no known provider prefix ("gpt-5.4-mini") is treated as OpenAI.
When no model is configured at all, the first provider with a key in the
environment wins, so dropping a single API key into ``.env`` is enough.

Each framework gets its native client for the provider where one exists; the
helpers below only resolve names, keys and endpoints.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    key_vars: tuple[str, ...]
    default_model: str
    base_url: str | None = None


PROVIDERS: dict[str, Provider] = {
    "openai": Provider("openai", "OpenAI", ("OPENAI_API_KEY",), "gpt-5.4-mini"),
    "anthropic": Provider("anthropic", "Anthropic", ("ANTHROPIC_API_KEY",), "claude-opus-5-5"),
    "gemini": Provider(
        "gemini", "Google Gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "gemini-3.7-flash",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    ),
    "openrouter": Provider(
        "openrouter", "OpenRouter", ("OPENROUTER_API_KEY",), "openai/gpt-5.4-mini", "https://openrouter.ai/api/v1",
    ),
    "custom": Provider("custom", "OpenAI-compatible", ("PAGESMITH_API_KEY",), ""),
}
ALIASES = {"google": "gemini", "claude": "anthropic"}
# Order used to pick a provider when none is configured.
DETECT_ORDER = ("custom", "openai", "anthropic", "gemini", "openrouter")


# Reply cap sent to providers that bill or reserve credit against it (Anthropic
# requires one; OpenRouter reserves credit for it). Pages are written in a single
# tool call, so it has to fit a whole index.html. OpenAI models are left uncapped.
MAX_TOKENS = int(os.environ.get("PAGESMITH_MAX_TOKENS", "16000"))


class ModelConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    provider: Provider
    name: str

    @property
    def id(self) -> str:
        return f"{self.provider.name}/{self.name}"

    @property
    def base_url(self) -> str | None:
        if self.provider.name == "custom":
            return os.environ.get("PAGESMITH_BASE_URL") or None
        return self.provider.base_url

    @property
    def api_key(self) -> str | None:
        for var in self.provider.key_vars:
            if os.environ.get(var):
                return os.environ[var]
        return None

    @property
    def max_tokens(self) -> int | None:
        return None if self.provider.name == "openai" else MAX_TOKENS

    def require_key(self) -> str:
        key = self.api_key
        if key:
            return key
        if self.provider.name == "custom":
            return "not-needed"  # local servers such as Ollama ignore the key
        raise ModelConfigError(
            f"{self.id} needs {' or '.join(self.provider.key_vars)}. Add it to .env or pick another provider."
        )

    def check(self) -> None:
        self.require_key()
        if self.provider.name == "custom" and not self.base_url:
            raise ModelConfigError("custom/... models need PAGESMITH_BASE_URL (an OpenAI-compatible /v1 endpoint).")
        if not self.name:
            raise ModelConfigError(f"No model name given for provider '{self.provider.name}'.")

    def litellm_id(self) -> str:
        """The id LiteLLM routes on (used by the ADK lead)."""
        prefix = {"custom": "openai"}.get(self.provider.name, self.provider.name)
        return f"{prefix}/{self.name}"


def _has_key(provider: Provider) -> bool:
    if provider.name == "custom":
        return bool(os.environ.get("PAGESMITH_BASE_URL"))
    return any(os.environ.get(var) for var in provider.key_vars)


def detect_provider() -> Provider:
    for name in DETECT_ORDER:
        if _has_key(PROVIDERS[name]):
            return PROVIDERS[name]
    return PROVIDERS["openai"]


def parse(value: str | None) -> ModelSpec:
    """Turn a ``provider/model`` string (or nothing) into a ModelSpec."""
    value = (value or "").strip()
    if not value:
        provider = detect_provider()
        return ModelSpec(provider, provider.default_model)
    head, sep, rest = value.partition("/")
    head = ALIASES.get(head.lower(), head.lower())
    if sep and head in PROVIDERS:
        provider = PROVIDERS[head]
        return ModelSpec(provider, rest or provider.default_model)
    if value.lower() in PROVIDERS or value.lower() in ALIASES:
        provider = PROVIDERS[ALIASES.get(value.lower(), value.lower())]
        return ModelSpec(provider, provider.default_model)
    return ModelSpec(PROVIDERS["openai"], value)
