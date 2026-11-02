from typing import Optional, Dict, Any


class AppException(Exception):
    """Base application exception with HTTP and RFC 7807 semantics."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: str = "INTERNAL_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or {}


class EntityNotFoundException(AppException):
    """Raised when a requested resource does not exist."""

    def __init__(self, entity_name: str, entity_id: str) -> None:
        super().__init__(
            message=f"{entity_name} with ID '{entity_id}' not found.",
            status_code=404,
            error_code="RESOURCE_NOT_FOUND",
            details={"entity_name": entity_name, "entity_id": entity_id},
        )


class IncidentNotFoundException(EntityNotFoundException):
    def __init__(self, incident_id: str) -> None:
        super().__init__(entity_name="Incident", entity_id=incident_id)


class InvalidStateTransitionException(AppException):
    """Raised when an illegal lifecycle state change is requested."""

    def __init__(self, current_status: str, requested_status: str, reason: str = "") -> None:
        super().__init__(
            message=f"Cannot transition from '{current_status}' to '{requested_status}'. {reason}".strip(),
            status_code=400,
            error_code="INVALID_STATE_TRANSITION",
            details={"current_status": current_status, "requested_status": requested_status},
        )


class UnauthorizedActionException(AppException):
    """Raised when an operation requires elevated approval or permission."""

    def __init__(self, action: str, reason: str = "Approval required") -> None:
        super().__init__(
            message=f"Action '{action}' is unauthorized: {reason}",
            status_code=403,
            error_code="UNAUTHORIZED_ACTION",
            details={"action": action, "reason": reason},
        )


class ExternalServiceException(AppException):
    """Raised when an external telemetry or LLM dependency fails or times out."""

    def __init__(self, service_name: str, message: str) -> None:
        super().__init__(
            message=f"External service '{service_name}' failure: {message}",
            status_code=502,
            error_code="BAD_GATEWAY",
            details={"service_name": service_name},
        )
