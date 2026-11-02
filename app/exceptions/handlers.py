import logging
from datetime import datetime, timezone
from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from app.exceptions.domain import AppException

logger = logging.getLogger("incident_agent.exceptions")


def create_problem_details(
    status_code: int,
    title: str,
    detail: str,
    instance: str,
    error_code: str,
    invalid_params: list | None = None,
    extra: dict | None = None,
) -> dict:
    """Constructs an RFC 7807 compliant problem details payload."""
    payload = {
        "type": f"https://httpstatuses.com/{status_code}",
        "title": title,
        "status": status_code,
        "detail": detail,
        "instance": instance,
        "code": error_code,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if invalid_params:
        payload["invalid_params"] = invalid_params
    if extra:
        payload["details"] = extra
    return payload


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handles domain-specific application exceptions."""
    logger.warning("Application exception [%s]: %s (path=%s)", exc.error_code, exc.message, request.url.path)
    problem = create_problem_details(
        status_code=exc.status_code,
        title=exc.error_code.replace("_", " ").title(),
        detail=exc.message,
        instance=str(request.url.path),
        error_code=exc.error_code,
        extra=exc.details,
    )
    return JSONResponse(status_code=exc.status_code, content=problem)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handles request body and query parameter validation errors."""
    invalid_params = []
    for err in exc.errors():
        loc = " -> ".join(str(item) for item in err.get("loc", []))
        invalid_params.append({
            "name": loc,
            "reason": err.get("msg", "Invalid value"),
            "type": err.get("type", "value_error"),
        })

    logger.info("Request validation failed on %s: %s", request.url.path, invalid_params)
    problem = create_problem_details(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Unprocessable Entity",
        detail="The request payload or parameters failed validation schema checks.",
        instance=str(request.url.path),
        error_code="VALIDATION_ERROR",
        invalid_params=invalid_params,
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=problem)


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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
