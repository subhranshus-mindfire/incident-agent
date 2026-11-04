import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph import close_checkpointer, open_checkpointer
from app.config.config import settings
from app.config.database import close_db
from app.exceptions import (
    AppException,
    app_exception_handler,
    generic_exception_handler,
    validation_exception_handler,
)
from app.middleware.request_logging import add_request_logging, configure_logging
from app.routes import api_router
from app.routes.health import router as health_router
from app.utils.http_client import close_shared_http_client, get_shared_http_client

logger = logging.getLogger("incident_agent")


async def run_db_migrations() -> None:
    """Applies pending Alembic database migrations programmatically on startup."""
    logger.info("Applying database migrations via Alembic...")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    # Alembic's async env.py starts its own event loop, so it runs in a worker thread.
    await asyncio.to_thread(command.upgrade, cfg, "head")
    logger.info("Database schema is fully up to date.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Handles startup events (DB migrations, connection pools)
    and graceful shutdown cleanup.
    """
    logger.info("Initializing %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment: %s", settings.ENVIRONMENT)

    # Initialize shared connection pool
    get_shared_http_client()

    try:
        await run_db_migrations()
        configure_logging()
    except Exception as ex:
        logger.warning("Automated migration check encountered an issue: %s", ex)

    # Paused approvals live in this store, so failing to open it must stop startup.
    await open_checkpointer()

    # Initialize Qdrant collection and seed runbooks in non-test environments
    if settings.ENVIRONMENT != "test":
        try:
            from app.seed.runbooks import DEFAULT_PRODUCTION_RUNBOOKS
            from app.services.qdrant_service import get_shared_qdrant_service

            qdrant = get_shared_qdrant_service()
            await qdrant.init_collection()
            for rb in DEFAULT_PRODUCTION_RUNBOOKS:
                await qdrant.upsert_runbook(rb)
            logger.info("Qdrant collection and default production runbooks initialized.")
        except Exception as ex:
            logger.warning("Qdrant initialization encountered an issue: %s", ex)

    # Yield control to the application
    yield

    logger.info("Shutting down %s...", settings.APP_NAME)
    from app.services.qdrant_service import close_shared_qdrant_service

    await close_shared_qdrant_service()
    await close_shared_http_client()
    try:
        await close_checkpointer()
    except Exception as ex:
        logger.warning("Error during checkpointer shutdown: %s", ex)
    try:
        await close_db()
    except Exception as ex:
        logger.warning("Error during database shutdown: %s", ex)


def create_application() -> FastAPI:
    """Builds the FastAPI app: lifespan, logging, CORS, exception handlers and routes."""
    configure_logging()
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="Autonomous Incident Investigation & Remediation Platform",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    add_request_logging(application)

    application.add_exception_handler(AppException, app_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, generic_exception_handler)

    application.include_router(health_router)
    application.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @application.get("/", tags=["Root"])
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/health",
            "api": settings.API_V1_PREFIX,
        }

    return application
