from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Incident Investigation Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"

    # CORS
    ALLOWED_ORIGINS: list[str] = ["*"]

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/incident_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant & Embeddings
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "runbooks"
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"
    FASTEMBED_CACHE_DIR: str = "~/.cache/fastembed"

    # Observability
    PROMETHEUS_URL: str = "http://localhost:9090"
    LOKI_URL: str = "http://localhost:3100"

    # LLM provider for the chat agent: "groq" or "gemini"
    LLM_PROVIDER: Literal["groq", "gemini", "ollama"] = "groq"
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "openai/gpt-oss-120b"
    GEMINI_API_KEY: str | None = None

    CHAT_REQUESTS_PER_MINUTE: int = 30
    GEMINI_MODEL: str = "gemini-2.5-flash"
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen2.5:3b"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
