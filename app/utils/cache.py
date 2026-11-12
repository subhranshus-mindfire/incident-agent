import logging
from functools import lru_cache

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.config import settings

logger = logging.getLogger("incident_agent.cache")


class RedisCache:
    """Short-lived JSON values in Redis. A Redis failure is a cache miss, never an error for the caller."""

    def __init__(self, redis_url: str) -> None:
        self._redis = Redis.from_url(redis_url)

    async def get(self, key: str) -> str | None:
        try:
            value = await self._redis.get(key)
        except RedisError as exc:
            logger.debug(f"Cache read skipped for {key}: {exc}")
            return None
        if value is None:
            return None
        return value if isinstance(value, str) else value.decode("utf-8")

    async def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            await self._redis.set(key, value, ex=ttl_seconds)
        except RedisError as exc:
            logger.debug(f"Cache write skipped for {key}: {exc}")


@lru_cache
def get_cache() -> RedisCache | None:
    """The shared cache, or None when caching is turned off in settings."""
    if not settings.CACHE_ENABLED:
        return None
    return RedisCache(settings.REDIS_URL)
