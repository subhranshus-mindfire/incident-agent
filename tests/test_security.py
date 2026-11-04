import httpx
import pytest
from httpx import ASGITransport

from app.config.config import settings
from app.main import app
from app.utils.rate_limit import SlidingWindowLimiter


def anonymous_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def test_write_route_without_key_is_refused() -> None:
    async with anonymous_client() as client:
        res = await client.post("/api/v1/investigations/x/approve", json={"reason": "no key"})
    assert res.status_code == 401


async def test_write_route_with_wrong_key_is_refused() -> None:
    async with anonymous_client() as client:
        res = await client.post(
            "/api/v1/investigations/x/approve",
            json={"reason": "bad key"},
            headers={"X-API-Key": "wrong"},
        )
    assert res.status_code == 401


async def test_chat_without_key_is_refused() -> None:
    async with anonymous_client() as client:
        res = await client.post("/api/v1/chat", json={"message": "hello", "history": []})
    assert res.status_code == 401


async def test_key_check_fails_closed_when_no_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "API_KEY", None)
    async with anonymous_client() as client:
        res = await client.post(
            "/api/v1/chat", json={"message": "hello", "history": []}, headers={"X-API-Key": "x"}
        )
    assert res.status_code == 503


async def test_read_routes_stay_open() -> None:
    async with anonymous_client() as client:
        res = await client.get("/health")
    assert res.status_code == 200


def test_rate_limiter_allows_up_to_the_limit_then_refuses() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.allow("client-a")
    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")
    assert limiter.allow("client-b")
