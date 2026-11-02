import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config.config import settings
from app.config.database import init_db, close_db

logger = logging.getLogger("incident_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup events (database tables initialization, connection pools)
    and graceful shutdown cleanup.
    """
    logger.info("Initializing %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment: %s", settings.ENVIRONMENT)

    try:
        await init_db()
    except Exception as ex:
        logger.warning("Database auto-init skipped or failed (will be retried on demand): %s", ex)

    # Yield control to the application
    yield

    logger.info("Shutting down %s...", settings.APP_NAME)
    try:
        await close_db()
    except Exception as ex:
        logger.warning("Error during database shutdown: %s", ex)
