import logging
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, Query, status

from app.constants.default_runbooks import DEFAULT_PRODUCTION_RUNBOOKS
from app.exceptions.domain import EntityNotFoundException, ValidationException
from app.schemas.runbook import (
    Runbook,
    RunbookCreate,
    RunbookSearchRequest,
    RunbookSearchResult,
)
from app.services.qdrant_service import QdrantService

logger = logging.getLogger("incident_agent.routes.runbooks")

router = APIRouter(prefix="/runbooks", tags=["Runbooks & Knowledge Base"])


@lru_cache
def get_qdrant_service() -> QdrantService:
    """Provides cached singleton QdrantService instance."""
    return QdrantService()


@router.post(
    "",
    response_model=Runbook,
    status_code=status.HTTP_201_CREATED,
    summary="Create & Index Runbook",
)
async def create_runbook(
    payload: RunbookCreate,
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> Runbook:
    """Indexes a new operational runbook into Qdrant vector database with dense embedding."""
    runbook = Runbook(**payload.model_dump())
    await qdrant.upsert_runbook(runbook)
    return runbook


@router.get(
    "",
    response_model=list[Runbook],
    status_code=status.HTTP_200_OK,
    summary="List Runbooks",
)
async def list_runbooks(
    limit: int = Query(default=50, ge=1, le=100, description="Max runbooks to return"),
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> list[Runbook]:
    """Lists indexed operational runbooks."""
    return await qdrant.list_runbooks(limit=limit)


@router.get(
    "/health",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Qdrant Vector Store Health Check",
)
async def qdrant_health_probe(
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> dict[str, Any]:
    """Probes the live status of the Qdrant vector cluster."""
    is_healthy = await qdrant.health_check()
    return {
        "qdrant": "healthy" if is_healthy else "unreachable",
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/seed",
    response_model=dict[str, Any],
    status_code=status.HTTP_200_OK,
    summary="Seed Default Production Runbooks",
)
async def seed_production_runbooks(
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> dict[str, Any]:
    """Seeds default production SRE runbooks into Qdrant vector collection."""
    await qdrant.init_collection()
    count = 0
    for runbook in DEFAULT_PRODUCTION_RUNBOOKS:
        await qdrant.upsert_runbook(runbook)
        count += 1

    return {
        "status": "success",
        "message": f"Successfully seeded {count} production SRE runbooks into Qdrant",
        "seeded_count": count,
    }


@router.post(
    "/search",
    response_model=list[RunbookSearchResult],
    status_code=status.HTTP_200_OK,
    summary="Semantic Runbook Search",
)
async def search_runbooks(
    request: RunbookSearchRequest,
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> list[RunbookSearchResult]:
    """Executes semantic cosine search across runbooks based on incident symptoms and filters."""
    if not request.query.strip():
        raise ValidationException("Search query cannot be blank")

    return await qdrant.search_runbooks(
        query=request.query,
        service=request.service,
        incident_type=request.incident_type,
        limit=request.limit,
        score_threshold=request.score_threshold,
    )


@router.get(
    "/{runbook_id}",
    response_model=Runbook,
    status_code=status.HTTP_200_OK,
    summary="Get Runbook by ID",
)
async def get_runbook(
    runbook_id: str,
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> Runbook:
    """Retrieves an operational runbook by its UUID."""
    runbook = await qdrant.get_runbook(runbook_id)
    if not runbook:
        raise EntityNotFoundException(entity_name="Runbook", entity_id=runbook_id)
    return runbook


@router.delete(
    "/{runbook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Runbook",
)
async def delete_runbook(
    runbook_id: str,
    qdrant: QdrantService = Depends(get_qdrant_service),
) -> None:
    """Deletes an operational runbook from the vector store."""
    existing = await qdrant.get_runbook(runbook_id)
    if not existing:
        raise EntityNotFoundException(entity_name="Runbook", entity_id=runbook_id)
    await qdrant.delete_runbook(runbook_id)
