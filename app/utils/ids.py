import uuid


def new_id(prefix: str) -> str:
    """A short, prefixed random identifier, for example 'inc-1a2b3c4d5e6f'."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
