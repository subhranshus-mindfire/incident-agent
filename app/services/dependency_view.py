"""Answers dependency questions from the service dependency map, without a language model.

The map is a fixed lookup, so answering from it is exact. Small local models sometimes skip the
tool and invent a refusal, so these questions never go to the model.
"""

from __future__ import annotations

import re

from app.constants.service_dependencies import SERVICE_DEPENDENCIES
from app.schemas.service import ServiceDependencyMap

DEPENDENCY_PATTERN = re.compile(
    r"\b(depend|dependenc|upstream|downstream|affected)\w*\b", re.IGNORECASE
)


def find_service(text: str) -> str | None:
    """The first service in the map that the text names, longest names first."""
    low = text.lower()
    for name in sorted(SERVICE_DEPENDENCIES, key=len, reverse=True):
        if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", low):
            return name
    return None


def is_dependency_question(text: str) -> bool:
    return bool(DEPENDENCY_PATTERN.search(text))


def render_dependencies(mapping: ServiceDependencyMap) -> str:
    upstream = ", ".join(f"`{s}`" for s in mapping.upstream_services) or "_none listed_"
    downstream = ", ".join(f"`{s}`" for s in mapping.downstream_services) or "_none listed_"
    return (
        f"#### Dependencies of `{mapping.service}`\n\n"
        "| Direction | Services |\n"
        "|-----------|----------|\n"
        f"| **Upstream** (depend on it) | {upstream} |\n"
        f"| **Downstream** (it depends on) | {downstream} |\n\n"
        f"Tier {mapping.tier} · criticality {mapping.criticality}. "
        f"A fault in `{mapping.service}` directly affects its upstream services."
    )


def dependency_reply(text: str) -> str | None:
    """Answer for a dependency question that names a known service, or None to leave it to the agent."""
    if not is_dependency_question(text):
        return None
    service = find_service(text)
    if service is None:
        return None
    return render_dependencies(SERVICE_DEPENDENCIES[service])
