import pytest
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq

from app.config.config import Settings
from app.llms.providers import (
    ProviderNotConfiguredError,
    build_chat_model,
    is_rate_limit_error,
)


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {"_env_file": None}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_gemini_provider_builds_gemini_model() -> None:
    model = build_chat_model(
        settings(LLM_PROVIDER="gemini", GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-2.5-flash"),
        max_output_tokens=512,
    )
    assert isinstance(model, ChatGoogleGenerativeAI)
    assert model.model == "gemini-2.5-flash"


def test_gemini_without_key_is_reported_not_guessed() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="GEMINI_API_KEY"):
        build_chat_model(
            settings(LLM_PROVIDER="gemini", GEMINI_API_KEY=None), max_output_tokens=512
        )


def test_groq_is_the_default_provider() -> None:
    model = build_chat_model(settings(GROQ_API_KEY="test-key"), max_output_tokens=512)
    assert isinstance(model, ChatGroq)


def test_groq_without_key_is_reported() -> None:
    with pytest.raises(ProviderNotConfiguredError, match="GROQ_API_KEY"):
        build_chat_model(settings(GROQ_API_KEY=None), max_output_tokens=512)


class _Limited(Exception):
    status_code = 429


class ResourceExhausted(Exception):
    """Named like Google's quota error."""


def test_rate_limits_are_recognised_for_both_providers() -> None:
    assert is_rate_limit_error(_Limited("slow down"))
    assert is_rate_limit_error(ResourceExhausted("quota"))


def test_other_errors_are_not_rate_limits() -> None:
    assert not is_rate_limit_error(ValueError("bad input"))
