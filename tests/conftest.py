import os
from collections.abc import AsyncGenerator

# Set before the app is imported: the settings are read at import time, and the test
# environment selects the in-memory checkpointer instead of the PostgreSQL one.
os.environ["ENVIRONMENT"] = "test"
# Rate limits stay in each test process, so test runs do not share counts through a live Redis.
os.environ["RATE_LIMIT_STORE"] = "memory"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth.passwords import hash_password
from app.auth.sessions import create_session
from app.config.database import Base, get_db_session
from app.main import app
from app.models.user import User
from app.services import clients
from app.utils.http_client import close_shared_http_client

# Isolated in-memory async SQLite engine for lightning-fast testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


@pytest_asyncio.fixture(scope="function")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provides a transactional database session rolled back after every test."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP async client with overridden database dependency."""

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    # A signed-in test user, so authenticated routes and actor attribution run as they do in production.
    db_session.add(User(username="test-user", password_hash=hash_password("test-password-123")))
    await db_session.commit()
    token = await create_session(db_session, "test-user")

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as async_client:
        yield async_client

    app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def fresh_shared_clients() -> AsyncGenerator[None, None]:
    """Shared HTTP clients are bound to the event loop that created them, so each test builds its own."""
    clients.get_prometheus_service.cache_clear()
    clients.get_loki_service.cache_clear()
    yield
    await close_shared_http_client()
    clients.get_prometheus_service.cache_clear()
    clients.get_loki_service.cache_clear()
