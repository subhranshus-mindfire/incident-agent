import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings

logger = logging.getLogger("incident_agent")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup events (DB connections, vector collection init, caches)
    and graceful shutdown cleanup.
    """
    logger.info("Initializing %s v%s...", settings.APP_NAME, settings.APP_VERSION)
    logger.info("Environment: %s", settings.ENVIRONMENT)

    # Yield control to the application
    yield

    logger.info("Shutting down %s...", settings.APP_NAME)
