from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.agents.chat_agent import run_chat
from app.auth.context import set_actor
from app.auth.current_user import current_user
from app.config.config import settings
from app.utils.rate_limit import shared_limiter

router = APIRouter(prefix="/chat", tags=["Chat"], dependencies=[Depends(current_user)])

_chat_limiter = shared_limiter("chat", limit=settings.CHAT_REQUESTS_PER_MINUTE, window_seconds=60)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)


@router.post(
    "",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Chat with the incident agent",
)
async def chat(
    payload: ChatRequest, request: Request, actor: str = Depends(current_user)
) -> dict[str, Any]:
    """Answers a free-form question using live telemetry tools; may open an investigation."""
    client = request.client.host if request.client else "unknown"
    if not await _chat_limiter.allow(client):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many chat requests; wait a minute",
        )
    set_actor(actor)
    return await run_chat(payload.message, [turn.model_dump() for turn in payload.history])
