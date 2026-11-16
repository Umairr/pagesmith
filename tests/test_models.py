import pytest

from pagesmith import models

KEY_VARS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY", "PAGESMITH_API_KEY", "PAGESMITH_BASE_URL"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.mark.parametrize("value, provider, name", [
    ("openai/gpt-5.4-mini", "openai", "gpt-5.4-mini"),
    ("gpt-5.4-mini", "openai", "gpt-5.4-mini"),
    ("anthropic/claude-sonnet-5-5", "anthropic", "claude-sonnet-5-5"),
    ("claude", "anthropic", "claude-opus-5-5"),
    ("google/gemini-3.7-flash", "gemini", "gemini-3.7-flash"),
    ("openrouter/anthropic/claude-haiku-5-5", "openrouter", "anthropic/claude-haiku-5-5"),
    ("custom/llama3.3", "custom", "llama3.3"),
])
def test_parse(value, provider, name):
    spec = models.parse(value)
    assert (spec.provider.name, spec.name) == (provider, name)


def test_detects_provider_from_available_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert models.parse("").id == "anthropic/claude-opus-5-5"
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    assert models.parse("").provider.name == "openai"


def test_gemini_accepts_either_key_name(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert models.parse("gemini/gemini-3.7-flash").api_key == "g"


def test_missing_key_is_reported():
    with pytest.raises(models.ModelConfigError, match="ANTHROPIC_API_KEY"):
        models.parse("anthropic/claude-sonnet-5-5").check()


def test_custom_endpoint(monkeypatch):
    monkeypatch.setenv("PAGESMITH_BASE_URL", "http://localhost:11434/v1")
    spec = models.parse("custom/llama3.3")
    spec.check()
    assert spec.base_url == "http://localhost:11434/v1"
    assert spec.litellm_id() == "openai/llama3.3"


def test_openai_is_left_uncapped():
    assert models.parse("openai/gpt-5.4-mini").max_tokens is None
    assert models.parse("anthropic/claude-sonnet-5-5").max_tokens == models.MAX_TOKENS
