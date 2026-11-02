from fastapi import APIRouter
from app.routes.incidents import router as incidents_router

api_router = APIRouter()
api_router.include_router(incidents_router)

__all__ = ["api_router"]
