from fastapi import APIRouter

from app.routes.incidents import router as incidents_router
from app.routes.runbooks import router as runbooks_router
from app.routes.telemetry import router as telemetry_router

api_router = APIRouter()
api_router.include_router(incidents_router)
api_router.include_router(telemetry_router)
api_router.include_router(runbooks_router)

__all__ = ["api_router"]
