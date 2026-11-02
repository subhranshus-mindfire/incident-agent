from typing import Any, Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):  # noqa: UP046
    """
    Generic asynchronous base repository providing standard CRUD operations
    with strict typing and transaction-safe session handling.
    """

    def __init__(self, model: type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get_by_id(self, id: Any) -> ModelType | None:
        """Fetch a single record by its primary key ID."""
        return await self.session.get(self.model, id)

    async def list_all(self, skip: int = 0, limit: int = 100) -> list[ModelType]:
        """Fetch a paginated list of records."""
        query = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count total records for this entity."""
        query = select(func.count()).select_from(self.model)
        result = await self.session.execute(query)
        return result.scalar() or 0

    async def create(self, instance: ModelType) -> ModelType:
        """Persist a new model instance."""
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def delete(self, instance: ModelType) -> None:
        """Delete an existing model instance."""
        await self.session.delete(instance)
        await self.session.flush()
