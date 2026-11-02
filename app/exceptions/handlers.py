import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions.domain import AppException

logger = logging.getLogger("incident_agent.exceptions")


def create_problem_details(
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    error_code: str,
    invalid_params: list[dict[str, Any]] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Constructs an RFC 7807 compliant problem details payload."""
    payload: dict[str, Any] = {
        "type": f"https://httpstatuses.com/{status_code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
        "code": error_code,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if invalid_params:
        payload["invalid_params"] = invalid_params
    if extra:
        payload["details"] = extra
    return payload


async def app_exception_handler(request: Request, exc: Exception) -> Response:
    """Handles domain-specific application exceptions."""
    app_exc = exc if isinstance(exc, AppException) else AppException(str(exc))
    logger.warning(
        "Application exception [%s]: %s (path=%s)",
        app_exc.error_code,
        app_exc.message,
        request.url.path,
    )
    problem = create_problem_details(
        status_code=app_exc.status_code,
        title=app_exc.error_code.replace("_", " ").title(),
        detail=app_exc.message,
        instance=str(request.url.path),
        error_code=app_exc.error_code,
        extra=app_exc.details,
    )
    return JSONResponse(status_code=app_exc.status_code, content=problem)


async def validation_exception_handler(request: Request, exc: Exception) -> Response:
    """Handles request body and query parameter validation errors."""
    validation_exc = exc if isinstance(exc, RequestValidationError) else None
    invalid_params: list[dict[str, Any]] = []
    if validation_exc:
        for err in validation_exc.errors():
            loc = " -> ".join(str(item) for item in err.get("loc", []))
            invalid_params.append(
                {
                    "name": loc,
                    "reason": err.get("msg", "Invalid value"),
                    "type": err.get("type", "value_error"),
                }
            )

    logger.info("Request validation failed on %s: %s", request.url.path, invalid_params)
    problem = create_problem_details(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        title="Unprocessable Entity",
        detail="The request payload or parameters failed validation schema checks.",
        instance=str(request.url.path),
        error_code="VALIDATION_ERROR",
        invalid_params=invalid_params,
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=problem)


async def generic_exception_handler(request: Request, exc: Exception) -> Response:
    """Catch-all handler for unhandled internal exceptions, masking internal details."""
    logger.error("Unhandled server exception on %s: %s", request.url.path, exc, exc_info=True)
    problem = create_problem_details(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail="An unexpected internal server error occurred. Please contact system administrators.",
        instance=str(request.url.path),
        error_code="INTERNAL_SERVER_ERROR",
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=problem)
