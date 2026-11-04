import httpx
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, verify_password
from app.config.database import get_db_session
from app.main import app
from app.utils.rate_limit import SlidingWindowLimiter


def anonymous_client(db_session: AsyncSession) -> httpx.AsyncClient:
    """A client with no sign-in. Token checks use the in-memory test database, not a live one."""

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def test_write_route_without_sign_in_is_refused(db_session: AsyncSession) -> None:
    async with anonymous_client(db_session) as client:
        res = await client.post("/api/v1/investigations/x/approve", json={"reason": "no sign-in"})
    assert res.status_code == 401


async def test_write_route_with_invalid_token_is_refused(db_session: AsyncSession) -> None:
    async with anonymous_client(db_session) as client:
        res = await client.post(
            "/api/v1/investigations/x/approve",
            json={"reason": "bad token"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert res.status_code == 401


async def test_chat_without_sign_in_is_refused(db_session: AsyncSession) -> None:
    async with anonymous_client(db_session) as client:
        res = await client.post("/api/v1/chat", json={"message": "hello", "history": []})
    assert res.status_code == 401


async def test_read_routes_stay_open(db_session: AsyncSession) -> None:
    async with anonymous_client(db_session) as client:
        res = await client.get("/health")
    assert res.status_code == 200


async def test_login_rejects_a_wrong_password(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/login", json={"username": "test-user", "password": "wrong-password"}
    )
    assert res.status_code == 401


async def test_login_returns_a_token_that_identifies_the_user(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/login", json={"username": "test-user", "password": "test-password-123"}
    )
    assert res.status_code == 200
    token = res.json()["token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json() == {"username": "test-user"}


def test_passwords_are_hashed_and_verified() -> None:
    stored = hash_password("correct horse battery")
    assert "correct horse battery" not in stored
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)


def test_rate_limiter_allows_up_to_the_limit_then_refuses() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.allow("client-a")
    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")
    assert limiter.allow("client-b")
