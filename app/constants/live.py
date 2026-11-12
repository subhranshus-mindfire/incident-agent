"""Live status and log-query settings: window bounds, keywords and patterns."""

import re
from typing import Final

DEFAULT_WINDOW_SECONDS: Final = 60

# payment-api is scraped every 5 s, so a 10 s rate still sees two samples.
MIN_WINDOW_SECONDS: Final = 10

MAX_WINDOW_SECONDS: Final = 3600

MAX_LOG_LINES: Final = 40

# Below this many requests in the window, an error percentage is one or two requests, not a rate.
MIN_REQUESTS_FOR_RATE: Final = 10

WINDOW_PATTERN: Final = re.compile(r"\blast\s+(\d+)\s*(seconds?|secs?|s|minutes?|mins?|m)\b")

INVESTIGATE_WORDS: Final = ("investigat", "diagnos", "debug", "analy")

# Wording of a search for past incidents. An investigation must never be opened from it.
SEARCH_REQUEST_WORDS: Final = (
    "search",
    "matching",
    "how many",
    "list ",
    "past incident",
    "previous incident",
)

# Questions about past or matching incidents. They are answered from the incident records, never from
# live metrics, even when they name a signal such as CPU.
HISTORY_WORDS: Final = (
    "incident",
    "past",
    "previous",
    "history",
    "matching",
    "involved",
    "similar",
    "search",
    "how many",
)

STATUS_PATTERN: Final = re.compile(r"\b(down|up|status|healthy|alive|working|available|outage)\b")

LOGS_PATTERN: Final = re.compile(r"\blogs?\b")

GOLDEN_WORDS: Final = (
    "golden",
    "signal",
    "latency",
    "cpu",
    "memory",
    "metric",
    "5xx",
    "error rate",
)

# Topics that need the full investigation or the agent, so a live answer would be incomplete.
OTHER_TOPIC_WORDS: Final = (
    "blast",
    "depend",
    "upstream",
    "downstream",
    "deploy",
    "regression",
    "past incident",
    "history",
    "root cause",
    "cause",
    "why",
)
