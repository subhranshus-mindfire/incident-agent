"""Chat routing: greetings, follow-ups and approval replies."""

import re
from typing import Final

# Words that mean the message is about an incident, so it must not get a canned greeting.
INVESTIGATION_KEYWORDS: Final = (
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
FOLLOWUP_FIX_PATTERN: Final = re.compile(
    r"^(?:please\s+)?(?:fix|remediate|resolve)"
    r"(?:\s+(?:it|this|that|those|these|them|the (?:faults?|issues?|problems?)))?[.!?]*$"
    r"|^(?:do it|go ahead)[.!?]*$",
    re.IGNORECASE,
)

KNOWN_SERVICES: Final = ("payment-api", "order-service", "auth-service")

# A short yes after a reply that is waiting for approval. Approval is a human action in the console.
AFFIRMATIVE_PATTERN: Final = re.compile(
    r"^(?:yes|yep|yeah|yup|ok|okay|sure|approve|approved|proceed|confirm)[.!]*$", re.IGNORECASE
)

# Asking to act on the approval card on screen, e.g. "please have a fix". Questions are excluded.
APPROVAL_INTENT_PATTERN: Final = re.compile(
    r"\b(?:fix|approve|proceed|execute|apply|remediate|go ahead|do it)\b", re.IGNORECASE
)

APPROVAL_WAITING_MARKERS: Final = (
    "awaiting human approval",
    "approval needed",
    "awaiting approval",
)

APPROVAL_REPLY: Final = (
    "This remediation needs an operator's approval. Use **Approve & execute** on the approval card "
    "below the chat. I can't approve or run remediation from chat."
)

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
