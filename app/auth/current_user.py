from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import username_for_token
from app.config.database import get_db_session


async def current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> str:
    """The signed-in username for `Authorization: Bearer <token>`. Raises 401 otherwise."""
    scheme, _, token = (authorization or "").partition(" ")
    username = await username_for_token(db, token) if scheme.lower() == "bearer" and token else None
    if username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
