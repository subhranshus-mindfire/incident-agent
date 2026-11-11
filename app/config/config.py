from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "Incident Investigation Agent"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    API_V1_PREFIX: str = "/api/v1"

    # CORS: browsers may call the API only from these origins. The Streamlit console calls it
    # from the server, so no origin is needed by default.
    ALLOWED_ORIGINS: list[str] = []

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/incident_db"

    # Redis: shared rate limits across workers. "memory" keeps the counts in each process instead.
    REDIS_URL: str = "redis://localhost:6379/0"
    RATE_LIMIT_STORE: Literal["redis", "memory"] = "redis"

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

    @model_validator(mode="after")
    def refuse_unsafe_production_settings(self) -> "Settings":
        """Stops a production start with development defaults still in place."""
        if self.ENVIRONMENT != "production":
            return self
        problems = []
        if "postgres:postgres@" in self.DATABASE_URL:
            problems.append("DATABASE_URL uses the default database password")
        if "*" in self.ALLOWED_ORIGINS:
            problems.append("ALLOWED_ORIGINS allows every origin")
        if self.DEBUG:
            problems.append("DEBUG is enabled")
        if self.RATE_LIMIT_STORE == "redis" and "localhost" in self.REDIS_URL:
            problems.append(
                "REDIS_URL points at localhost, so workers on other hosts share no limits"
            )
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
