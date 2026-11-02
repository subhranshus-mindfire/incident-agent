import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.health import router as health_router
from app.routes import api_router
from app.starter import lifespan

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("incident_agent")


def create_application() -> FastAPI:
    """FastAPI application factory."""
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Autonomous Incident Investigation & Remediation Platform",
        lifespan=lifespan,
    )

    # CORS configuration
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include Routers
    application.include_router(health_router)
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @application.get("/", tags=["Root"])
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/health",
            "api": settings.API_V1_PREFIX
        }

    return application


app = create_application()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
