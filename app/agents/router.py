"""Decides how a chat message is answered before the language model is involved.

Order: greetings get a fixed reply, live status/log/metric questions read telemetry directly,
dependency questions read the service map, and everything else goes to the agent. Chat never
approves anything: the agent has no approve tool, and approval happens on the approval card.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.constants.chat import GREETING_REPLIES, INVESTIGATION_KEYWORDS
from app.services.dependency_view import dependency_reply
from app.services.live_status import answer_live, classify_live_request, resolve_service
from app.utils.text import squeeze_repeats


@dataclass(frozen=True)
class RoutedMessage:
    """`text` is what the agent should see. `reply` is set when the message is answered without it."""

    text: str
    reply: str | None


def greeting_reply(text: str) -> str | None:
    low = squeeze_repeats(text.lower().strip().rstrip("!.,?"))
    if any(word in text.lower() for word in INVESTIGATION_KEYWORDS):
        return None
    for key, reply in GREETING_REPLIES.items():
        canonical = squeeze_repeats(key)
        if low == canonical or low.startswith(canonical + " "):
            return reply
    return None


async def route_message(message: str) -> RoutedMessage:
    text = message.strip()

    greeting = greeting_reply(text)
    if greeting is not None:
        return RoutedMessage(text=text, reply=greeting)

    live = classify_live_request(text)
    if live is not None:
        return RoutedMessage(text=text, reply=await answer_live(live, resolve_service(text)))

    dependencies = dependency_reply(text)
    if dependencies is not None:
        return RoutedMessage(text=text, reply=dependencies)

    return RoutedMessage(text=text, reply=None)
