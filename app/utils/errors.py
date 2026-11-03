def error_payload(exc: BaseException) -> dict[str, str]:
    """A tool or service failure as a JSON-safe payload, so one failure does not end a whole request."""
    return {"error": f"{type(exc).__name__}: {exc}"}
