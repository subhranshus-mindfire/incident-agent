from contextvars import ContextVar

_actor: ContextVar[str] = ContextVar("actor", default="system")


def set_actor(username: str) -> None:
    """Records who the current request is acting for, so tools can attribute their actions."""
    _actor.set(username)


def current_actor() -> str:
    return _actor.get()
