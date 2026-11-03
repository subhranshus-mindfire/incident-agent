"""Decides how a chat message is answered before the language model is involved.

Order: short follow-ups are rewritten, greetings get a fixed reply, live status/log/metric questions
read telemetry directly, and everything else goes to the agent.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.constants.chat import (
    AFFIRMATIVE_PATTERN,
    APPROVAL_REPLY,
    APPROVAL_WAITING_MARKERS,
    FOLLOWUP_FIX_PATTERN,
    GREETING_REPLIES,
    INVESTIGATION_KEYWORDS,
    KNOWN_SERVICES,
)
from app.constants.services import PRIMARY_SERVICE
from app.services.live_status import answer_live, classify_live_request, resolve_service
from app.utils.text import squeeze_repeats


@dataclass(frozen=True)
class RoutedMessage:
    """`text` is what the agent should see. `reply` is set when the message is answered without it."""

    text: str
    reply: str | None


def resolve_follow_up(text: str, history: list[dict[str, str]]) -> str:
    """Expands a short follow-up such as 'fix it' into a request about the service discussed last."""
    if not FOLLOWUP_FIX_PATTERN.match(text.strip()):
        return text
    last_reply = next(
        (turn["content"] for turn in reversed(history) if turn["role"] == "assistant"), ""
    )
    service = next((name for name in KNOWN_SERVICES if name in last_reply), PRIMARY_SERVICE)
    return f"Investigate {service} degradation and propose a fix."


def greeting_reply(text: str) -> str | None:
    low = squeeze_repeats(text.lower().strip().rstrip("!.,?"))
    if any(word in text.lower() for word in INVESTIGATION_KEYWORDS):
        return None
    for key, reply in GREETING_REPLIES.items():
        canonical = squeeze_repeats(key)
        if low == canonical or low.startswith(canonical + " "):
            return reply
    return None


def _awaiting_approval(history: list[dict[str, str]]) -> bool:
    last_reply = next(
        (turn["content"] for turn in reversed(history) if turn["role"] == "assistant"), ""
    )
    return any(marker in last_reply.lower() for marker in APPROVAL_WAITING_MARKERS)


async def route_message(message: str, history: list[dict[str, str]]) -> RoutedMessage:
    if AFFIRMATIVE_PATTERN.match(message.strip()) and _awaiting_approval(history):
        return RoutedMessage(text=message.strip(), reply=APPROVAL_REPLY)

    text = resolve_follow_up(message.strip(), history)

    greeting = greeting_reply(text)
    if greeting is not None:
        return RoutedMessage(text=text, reply=greeting)

    live = classify_live_request(text)
    if live is not None:
        return RoutedMessage(text=text, reply=await answer_live(live, resolve_service(text)))

    return RoutedMessage(text=text, reply=None)
