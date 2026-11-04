from fastapi import APIRouter

from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.incidents import router as incidents_router
from app.routes.investigations import router as investigations_router
from app.routes.runbooks import router as runbooks_router
from app.routes.telemetry import router as telemetry_router

api_router = APIRouter()
api_router.include_router(incidents_router)
api_router.include_router(telemetry_router)
api_router.include_router(runbooks_router)
api_router.include_router(investigations_router)
api_router.include_router(chat_router)
api_router.include_router(auth_router)

__all__ = ["api_router"]
