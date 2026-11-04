from typing import Any, Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.agents.chat_agent import run_chat

router = APIRouter(prefix="/chat", tags=["Chat"])


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=30)
    approval_pending: bool = False


@router.post(
    "",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Chat with the incident agent",
)
async def chat(payload: ChatRequest) -> dict[str, Any]:
    """Answers a free-form question using live telemetry tools; may open an investigation."""
    return await run_chat(
        payload.message,
        [turn.model_dump() for turn in payload.history],
        payload.approval_pending,
    )
