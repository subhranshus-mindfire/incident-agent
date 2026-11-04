import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import AuthSession

SESSION_HOURS = 12


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_session(db: AsyncSession, username: str) -> str:
    """Creates a session and returns the bearer token. The token is shown once and never stored."""
    token = secrets.token_urlsafe(32)
    db.add(
        AuthSession(
            token_hash=_digest(token),
            username=username,
            expires_at=datetime.now(UTC) + timedelta(hours=SESSION_HOURS),
        )
    )
    await db.commit()
    return token


async def username_for_token(db: AsyncSession, token: str) -> str | None:
    """The user a valid, unexpired token belongs to, or None."""
    row = await db.scalar(select(AuthSession).where(AuthSession.token_hash == _digest(token)))
    if row is None or row.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
        return None
    return row.username


async def end_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(AuthSession).where(AuthSession.token_hash == _digest(token)))
    await db.commit()
