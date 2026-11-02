import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from app.config.config import settings

logger = logging.getLogger("incident_agent.database")


class Base(AsyncAttrs, DeclarativeBase):
    """Base declarative class for all SQLAlchemy 2.0 async models."""
    pass


# Global async engine and session factory
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency yielding a transactional AsyncSession.
    Automatically commits on success or rolls back on exception.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as ex:
            await session.rollback()
            logger.error("Transaction rolled back due to error: %s", ex, exc_info=True)
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Creates database schema tables if they do not exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema initialized.")


async def close_db() -> None:
    """Closes all database engine connections."""
    await engine.dispose()
    logger.info("Database connection pool closed.")
