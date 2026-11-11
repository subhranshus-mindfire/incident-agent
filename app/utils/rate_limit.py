import logging
import time
import uuid
from collections import deque
from typing import Final

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config.config import settings

logger = logging.getLogger("incident_agent.rate_limit")

# Keeps the window in a sorted set scored by time. Expired hits go, and a hit is recorded only when the
# caller is under the limit, so a refused request does not extend its own block. One script call is atomic,
# so two workers cannot both take the last slot.
_SLIDING_WINDOW_SCRIPT: Final = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, tonumber(ARGV[1]) - tonumber(ARGV[2]))
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
    return 0
end
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""


class SlidingWindowLimiter:
    """Allows at most `limit` hits per key in any `window_seconds` span. In-process, so per worker."""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True


class SharedRateLimiter:
    """A sliding-window limit shared by every worker through Redis.

    If Redis cannot be reached, the request is judged by this process's own counts and a warning is
    logged, so a Redis outage weakens the limit but does not fail the requests it protects.
    """

    def __init__(
        self,
        name: str,
        limit: int,
        window_seconds: int,
        redis_url: str | None,
    ) -> None:
        self.name = name
        self.limit = limit
        self.window_seconds = window_seconds
        self._fallback = SlidingWindowLimiter(limit, window_seconds)
        self._redis: Redis | None = Redis.from_url(redis_url) if redis_url else None
        self._script = self._redis.register_script(_SLIDING_WINDOW_SCRIPT) if self._redis else None

    async def allow(self, key: str) -> bool:
        if self._script is None:
            return self._fallback.allow(key)
        try:
            allowed = await self._script(
                keys=[f"ratelimit:{self.name}:{key}"],
                args=[time.time(), self.window_seconds, self.limit, uuid.uuid4().hex],
            )
        except RedisError as exc:
            logger.warning(
                f"Rate limit '{self.name}' is using this process only; Redis failed: {exc}"
            )
            return self._fallback.allow(key)
        return bool(allowed)

    def clear_local(self) -> None:
        """Forgets this process's own counts. Used by tests."""
        self._fallback._hits.clear()


def shared_limiter(name: str, limit: int, window_seconds: int) -> SharedRateLimiter:
    """A limiter configured from settings: Redis when RATE_LIMIT_STORE is "redis", this process otherwise."""
    redis_url = settings.REDIS_URL if settings.RATE_LIMIT_STORE == "redis" else None
    return SharedRateLimiter(name, limit=limit, window_seconds=window_seconds, redis_url=redis_url)
