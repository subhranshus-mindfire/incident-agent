from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.current_user import current_user
from app.auth.passwords import verify_password
from app.auth.sessions import SESSION_HOURS, create_session, end_session
from app.config.database import get_db_session
from app.models.user import User
from app.utils.rate_limit import shared_limiter

router = APIRouter(prefix="/auth", tags=["Authentication"])

_login_limiter = shared_limiter("login", limit=10, window_seconds=60)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login", response_model=dict[str, Any], summary="Sign in and receive a bearer token")
async def login(
    payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db_session)
) -> dict[str, Any]:
    client = request.client.host if request.client else "unknown"
    if not await _login_limiter.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many sign-in attempts"
        )
    user = await db.get(User, payload.username)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        )
    token = await create_session(db, user.username)
    return {"token": token, "username": user.username, "expires_in_hours": SESSION_HOURS}


@router.get("/me", response_model=dict[str, Any], summary="The signed-in user")
async def me(username: str = Depends(current_user)) -> dict[str, Any]:
    return {"username": username}


@router.post("/logout", response_model=dict[str, Any], summary="End the current session")
async def logout(
    authorization: str | None = Header(default=None),
    username: str = Depends(current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    token = (authorization or "").partition(" ")[2]
    await end_session(db, token)
    return {"signed_out": username}
