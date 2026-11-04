import hmac

from fastapi import Header, HTTPException, status

from app.config.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Rejects the request unless it carries the configured key. Fails closed when no key is configured."""
    expected = settings.API_KEY
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API_KEY is not configured on the server",
        )
    if x_api_key is None or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key"
        )
