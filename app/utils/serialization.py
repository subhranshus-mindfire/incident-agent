from typing import Any


def as_plain_dict(item: Any) -> Any:
    """Converts a Pydantic model to a plain dict; other values pass through unchanged."""
    return item.model_dump() if hasattr(item, "model_dump") else item
