import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import FastAPI

from app.config.config import settings
from app.config.database import close_db
from app.core.http_client import close_shared_http_client, get_shared_http_client

logger = logging.getLogger("incident_agent")


def run_upgrade(connection: Any, cfg: Config) -> None:
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def run_db_migrations() -> None:
    """Applies pending Alembic database migrations programmatically on startup."""
    from app.config.database import engine

    logger.info("Applying database migrations via Alembic...")
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

    async with engine.begin() as conn:
        await conn.run_sync(run_upgrade, cfg)
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
    except Exception as ex:
        logger.warning("Automated migration check encountered an issue: %s", ex)

    # Initialize Qdrant collection and seed runbooks in non-test environments
    if settings.ENVIRONMENT != "test":
        try:
            from app.constants.default_runbooks import DEFAULT_PRODUCTION_RUNBOOKS
            from app.services.qdrant_service import QdrantService

            qdrant = QdrantService()
            await qdrant.init_collection()
            for rb in DEFAULT_PRODUCTION_RUNBOOKS:
                await qdrant.upsert_runbook(rb)
            await qdrant.close()
            logger.info("Qdrant collection and default production runbooks initialized.")
        except Exception as ex:
            logger.warning("Qdrant initialization encountered an issue: %s", ex)

    # Yield control to the application
    yield

    logger.info("Shutting down %s...", settings.APP_NAME)
    await close_shared_http_client()
    try:
        await close_db()
    except Exception as ex:
        logger.warning("Error during database shutdown: %s", ex)
