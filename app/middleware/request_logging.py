"""Logging setup and a request-access log.

Access log lines are written by the `incident_agent.access` logger, one per request:
method, path, status and duration. Health probes are skipped to keep the log readable.
"""

import logging
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

access_logger = logging.getLogger("incident_agent.access")
SKIPPED_PATHS = frozenset({"/health", "/api/v1/telemetry/health"})


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    # Alembic's logging config sets the root level to WARN; application INFO logs need it back at INFO.
    logging.getLogger().setLevel(logging.INFO)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        if request.url.path not in SKIPPED_PATHS:
            elapsed_ms = (time.perf_counter() - started) * 1000
            access_logger.info(
                "%s %s -> %s in %.0f ms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
        return response


def add_request_logging(application: FastAPI) -> None:
    application.add_middleware(RequestLoggingMiddleware)
