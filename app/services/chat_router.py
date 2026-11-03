"""Decides how a chat message is answered before the language model is involved.

Order: short follow-ups are rewritten, greetings get a fixed reply, live status/log/metric questions
read telemetry directly, and everything else goes to the agent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.constants.services import PRIMARY_SERVICE
from app.services.live_status import answer_live, classify_live_request, resolve_service

GREETING_REPLIES: Final[dict[str, str]] = {
    "hi": "👋 Hey! I'm your incident investigation assistant. Tell me about a service issue or pick one of the suggested queries to get started.",
    "hello": "👋 Hello! I'm ready to investigate incidents. Describe a symptom or service name to begin.",
    "hey": '👋 Hey there! Describe an issue (e.g. *"payment-api is returning 500s"*) and I\'ll dig in.',
    "okay": "Got it! Ready when you are — just describe the incident you want me to investigate.",
    "ok": "Sure thing! What incident should I look into?",
    "thanks": "You're welcome! Let me know if you need another investigation.",
    "thank you": "Glad I could help! 🙌",
    "bye": "See you next time! Stay incident-free 🚀",
}

# Words that mean the message is about an incident, so it must not get a canned greeting.
_INVESTIGATION_KEYWORDS: Final = (
    "investigate",
    "check",
    "diagnose",
    "debug",
    "error",
    "fault",
    "issue",
    "incident",
    "500",
    "latency",
    "timeout",
    "crash",
    "payment",
    "api",
    "deployment",
    "deploy",
    "rollback",
    "metric",
    "log",
    "prometheus",
    "loki",
    "qdrant",
    "blast",
    "root cause",
    "rca",
    "remediat",
    "chaos",
    "deadlock",
    "connection pool",
    "cpu",
    "memory",
    "service",
    "health",
    "down",
    "slow",
    "failure",
    "alert",
    "outage",
)

# Short requests for action on whatever was discussed last, e.g. "fix it" after a status answer.
_FOLLOWUP_FIX_PATTERN: Final = re.compile(
    r"^(?:please\s+)?(?:fix|remediate|resolve)"
    r"(?:\s+(?:it|this|that|those|these|them|the (?:faults?|issues?|problems?)))?[.!?]*$"
    r"|^(?:do it|go ahead)[.!?]*$",
    re.IGNORECASE,
)
_KNOWN_SERVICES: Final = ("payment-api", "order-service", "auth-service")
_REPEATED_LETTERS: Final = re.compile(r"(.)\1+")
# A short yes after a reply that is waiting for approval. Approval is a human action in the console.
_AFFIRMATIVE_PATTERN: Final = re.compile(
    r"^(?:yes|yep|yeah|yup|ok|okay|sure|approve|approved|proceed|confirm)[.!]*$", re.IGNORECASE
)
_APPROVAL_WAITING_MARKERS: Final = (
    "awaiting human approval",
    "approval needed",
    "awaiting approval",
)
APPROVAL_REPLY: Final = (
    "This remediation needs an operator's approval. Use **Approve & execute** on the approval card "
    "below the chat. I can't approve or run remediation from chat."
)


@dataclass(frozen=True)
class RoutedMessage:
    """`text` is what the agent should see. `reply` is set when the message is answered without it."""

    text: str
    reply: str | None


def _squeeze(text: str) -> str:
    """Collapses repeated letters so 'hii' and 'helloo' match their canonical greetings."""
    return _REPEATED_LETTERS.sub(r"\1", text)


def resolve_follow_up(text: str, history: list[dict[str, str]]) -> str:
    """Expands a short follow-up such as 'fix it' into a request about the service discussed last."""
    if not _FOLLOWUP_FIX_PATTERN.match(text.strip()):
        return text
    last_reply = next(
        (turn["content"] for turn in reversed(history) if turn["role"] == "assistant"), ""
    )
    service = next((name for name in _KNOWN_SERVICES if name in last_reply), PRIMARY_SERVICE)
    return f"Investigate {service} degradation and propose a fix."


def greeting_reply(text: str) -> str | None:
    low = _squeeze(text.lower().strip().rstrip("!.,?"))
    if any(word in text.lower() for word in _INVESTIGATION_KEYWORDS):
        return None
    for key, reply in GREETING_REPLIES.items():
        canonical = _squeeze(key)
        if low == canonical or low.startswith(canonical + " "):
            return reply
    return None


def _awaiting_approval(history: list[dict[str, str]]) -> bool:
    last_reply = next(
        (turn["content"] for turn in reversed(history) if turn["role"] == "assistant"), ""
    )
    return any(marker in last_reply.lower() for marker in _APPROVAL_WAITING_MARKERS)


async def route_message(message: str, history: list[dict[str, str]]) -> RoutedMessage:
    if _AFFIRMATIVE_PATTERN.match(message.strip()) and _awaiting_approval(history):
        return RoutedMessage(text=message.strip(), reply=APPROVAL_REPLY)

    text = resolve_follow_up(message.strip(), history)

    greeting = greeting_reply(text)
    if greeting is not None:
        return RoutedMessage(text=text, reply=greeting)

    live = classify_live_request(text)
    if live is not None:
        return RoutedMessage(text=text, reply=await answer_live(live, resolve_service(text)))

    return RoutedMessage(text=text, reply=None)
