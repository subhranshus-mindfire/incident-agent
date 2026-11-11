"""Checks that the figures in a chat reply appear in the tool results it was written from."""

import re
from typing import Final

# A number with a unit the metrics use: 14%, 2300ms, 0.5s, 3 rps, 12 req, 4 requests, 2/s.
_FIGURE: Final = re.compile(
    r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:%|ms\b|s\b|rps\b|req(?:uest)?s?\b|/s\b)", re.IGNORECASE
)
_NUMBER: Final = re.compile(r"-?\d+(?:\.\d+)?")


def _close(figure: float, value: float) -> bool:
    # Replies round, so a figure matches a value within 0.05 or 1% of it, whichever is larger.
    return abs(figure - value) <= max(0.05, 0.01 * abs(value))


def unsupported_figures(reply: str, tool_results: list[str]) -> list[str]:
    """Figures in the reply that no tool result contains. An empty list means the reply is grounded."""
    available = [float(n) for raw in tool_results for n in _NUMBER.findall(raw)]
    missing = []
    for match in _FIGURE.finditer(reply):
        figure = float(match.group(1))
        if not any(_close(figure, value) for value in available):
            missing.append(match.group(0).strip())
    return missing
