import asyncio
import os
import uuid

import pytest
from redis import Redis
from redis.exceptions import RedisError

from app.utils.rate_limit import SharedRateLimiter

# A real Redis is used when one is reachable; the database number keeps test keys away from app data.
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")


def _redis_reachable() -> bool:
    try:
        return bool(Redis.from_url(TEST_REDIS_URL, socket_connect_timeout=0.5).ping())
    except RedisError:
        return False


requires_redis = pytest.mark.skipif(
    not _redis_reachable(), reason="no Redis server reachable at TEST_REDIS_URL"
)


@requires_redis
async def test_workers_share_one_count_through_redis() -> None:
    name = f"test-{uuid.uuid4().hex}"
    # Two limiter objects stand in for two worker processes.
    worker_a = SharedRateLimiter(name, limit=2, window_seconds=60, redis_url=TEST_REDIS_URL)
    worker_b = SharedRateLimiter(name, limit=2, window_seconds=60, redis_url=TEST_REDIS_URL)

    assert await worker_a.allow("client") is True
    assert await worker_b.allow("client") is True
    assert await worker_a.allow("client") is False


@requires_redis
async def test_refused_requests_do_not_use_up_the_window() -> None:
    name = f"test-{uuid.uuid4().hex}"
    limiter = SharedRateLimiter(name, limit=1, window_seconds=1, redis_url=TEST_REDIS_URL)

    assert await limiter.allow("client") is True
    assert await limiter.allow("client") is False
    assert await limiter.allow("client") is False

    await asyncio.sleep(1.1)
    assert await limiter.allow("client") is True


async def test_unreachable_redis_falls_back_to_this_process() -> None:
    limiter = SharedRateLimiter(
        f"test-{uuid.uuid4().hex}",
        limit=2,
        window_seconds=60,
        redis_url="redis://127.0.0.1:1/0",
    )

    assert await limiter.allow("client") is True
    assert await limiter.allow("client") is True
    assert await limiter.allow("client") is False


async def test_no_redis_url_uses_this_process() -> None:
    limiter = SharedRateLimiter(
        f"test-{uuid.uuid4().hex}", limit=1, window_seconds=60, redis_url=None
    )

    assert await limiter.allow("client") is True
    assert await limiter.allow("client") is False
