import logging

import httpx

logger = logging.getLogger("incident_agent.http_client")

_shared_http_client: httpx.AsyncClient | None = None


def get_shared_http_client() -> httpx.AsyncClient:
    """Returns the shared application-scoped HTTP client for connection pooling."""
    global _shared_http_client
    if _shared_http_client is None or _shared_http_client.is_closed:
        _shared_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=4.0),
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
        )
    return _shared_http_client


async def close_shared_http_client() -> None:
    """Gracefully closes all connections in the shared HTTP pool on application shutdown."""
    global _shared_http_client
    if _shared_http_client is not None and not _shared_http_client.is_closed:
        await _shared_http_client.aclose()
        _shared_http_client = None
        logger.info("Shared HTTP connection pool closed.")
