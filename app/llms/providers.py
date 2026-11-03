"""Chat model providers.

The agent asks for a chat model. The LLM_PROVIDER setting decides which API serves it, so the
agent code does not change when the provider does.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from pydantic import SecretStr

from app.config.config import Settings
from app.constants.llm import (
    MAX_PROVIDER_RETRIES,
)


class ProviderNotConfiguredError(RuntimeError):
    """The selected provider has no API key."""


def build_chat_model(settings: Settings, max_output_tokens: int) -> BaseChatModel:
    if settings.LLM_PROVIDER == "ollama":
        # Local model: no API key and no provider quota. Speed depends on the host's CPU and memory.
        return ChatOllama(
            model=settings.OLLAMA_MODEL,
            base_url=settings.OLLAMA_URL,
            temperature=0,
            num_predict=max_output_tokens,
        )
    if settings.LLM_PROVIDER == "gemini":
        if not settings.GEMINI_API_KEY:
            raise ProviderNotConfiguredError("GEMINI_API_KEY is not set")
        return ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=SecretStr(settings.GEMINI_API_KEY),
            temperature=0,
            max_output_tokens=max_output_tokens,
            max_retries=MAX_PROVIDER_RETRIES,
        )
    if not settings.GROQ_API_KEY:
        raise ProviderNotConfiguredError("GROQ_API_KEY is not set")
    # Only the OpenAI-hosted models accept reasoning_effort; others reject the request.
    reasoning = "low" if settings.GROQ_MODEL.startswith("openai/") else None
    return ChatGroq(
        model=settings.GROQ_MODEL,
        api_key=SecretStr(settings.GROQ_API_KEY),
        temperature=0,
        max_tokens=max_output_tokens,
        max_retries=MAX_PROVIDER_RETRIES,
        reasoning_effort=reasoning,
    )


def is_rate_limit_error(exc: BaseException) -> bool:
    """True for a provider's per-minute or per-day limit, from either Groq or Gemini."""
    status: Any = getattr(exc, "status_code", None)
    return status == 429 or type(exc).__name__ in ("RateLimitError", "ResourceExhausted")
