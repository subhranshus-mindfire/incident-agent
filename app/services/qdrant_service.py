import logging
import re
from typing import Any

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.config.config import settings
from app.exceptions.domain import ExternalServiceException
from app.schemas.runbook import Runbook, RunbookSearchResult
from app.services.embedding_service import EmbeddingService, get_embedding_service

logger = logging.getLogger("incident_agent.qdrant_service")

UUID_REGEX = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class QdrantService:
    """Enterprise vector store adapter for Qdrant.

    Manages semantic runbook indexing, payload filtering, and cosine similarity search.
    """

    def __init__(
        self,
        client: AsyncQdrantClient | None = None,
        collection_name: str = settings.QDRANT_COLLECTION,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.collection_name = collection_name
        self._embedding_service = embedding_service or get_embedding_service()
        self._external_client = client is not None
        self._client: AsyncQdrantClient = client or AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            api_key=settings.QDRANT_API_KEY,
            check_compatibility=False,
            timeout=10,
        )

    async def close(self) -> None:
        """Closes the async Qdrant client connection if created internally."""
        if not self._external_client:
            await self._client.close()

    async def health_check(self) -> bool:
        """Verifies connectivity to Qdrant cluster."""
        try:
            await self._client.get_collections()
            return True
        except Exception as exc:
            logger.warning(f"Qdrant health check failed: {exc}")
            return False

    @staticmethod
    def is_valid_uuid(val: str) -> bool:
        """Validates whether a string is a standard RFC 4122 UUID."""
        return bool(UUID_REGEX.match(val))

    async def init_collection(self) -> None:
        """Ensures the runbook vector collection and payload indexes exist (idempotent)."""
        try:
            exists = await self._client.collection_exists(self.collection_name)

            if not exists:
                logger.info(f"Creating Qdrant collection '{self.collection_name}'...")
                try:
                    await self._client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=models.VectorParams(
                            size=self._embedding_service.dimension,
                            distance=models.Distance.COSINE,
                        ),
                    )
                    logger.info(f"Collection '{self.collection_name}' created successfully.")
                except UnexpectedResponse as exc:
                    if "already exists" in str(exc).lower():
                        logger.info(
                            f"Collection '{self.collection_name}' already exists (race handled)."
                        )
                    else:
                        raise

            # Create payload keyword indexes idempotently
            for field in ("service", "incident_types"):
                try:
                    await self._client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )
                except UnexpectedResponse:
                    pass  # Index already exists
            logger.info("Payload indexes verified for 'service' and 'incident_types'.")
        except Exception as exc:
            logger.error(f"Failed to initialize Qdrant collection '{self.collection_name}': {exc}")
            raise ExternalServiceException(
                service_name="Qdrant",
                message=f"Collection initialization failed: {exc}",
            ) from exc

    def _prepare_search_text(self, runbook: Runbook) -> str:
        """Constructs an information-dense text representation for embedding."""
        parts = [
            f"Title: {runbook.title}",
            f"Description: {runbook.description}",
            f"Target Service: {runbook.service}",
            f"Incident Types: {', '.join(runbook.incident_types)}",
            f"Diagnostic Steps: {' '.join(runbook.diagnostic_steps)}",
            f"Remediation Steps: {' '.join(runbook.remediation_steps)}",
        ]
        if runbook.verification_steps:
            parts.append(f"Verification: {' '.join(runbook.verification_steps)}")
        return "\n".join(parts)

    async def upsert_runbook(self, runbook: Runbook) -> str:
        """Indexes or updates a runbook in Qdrant with its dense vector and payload."""
        try:
            searchable_text = self._prepare_search_text(runbook)
            vector = await self._embedding_service.embed_text(searchable_text)

            payload: dict[str, Any] = runbook.model_dump(mode="json")
            payload["_searchable_snippet"] = searchable_text[:500]

            await self._client.upsert(
                collection_name=self.collection_name,
                points=[
                    models.PointStruct(
                        id=runbook.id,
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            logger.info(f"Successfully upserted runbook '{runbook.title}' (ID: {runbook.id})")
            return runbook.id
        except Exception as exc:
            logger.error(f"Failed to upsert runbook '{runbook.id}': {exc}")
            raise ExternalServiceException(
                service_name="Qdrant",
                message=f"Failed to upsert runbook: {exc}",
            ) from exc

    async def search_runbooks(
        self,
        query: str,
        service: str | None = None,
        incident_type: str | None = None,
        limit: int = 5,
        score_threshold: float = 0.20,
    ) -> list[RunbookSearchResult]:
        """Performs semantic cosine search across indexed runbooks with optional metadata filtering."""
        if not query or not query.strip():
            return []

        try:
            query_vector = await self._embedding_service.embed_text(query)

            must_conditions: list[models.Condition] = []

            # Service filtering: match specific service or generic runbooks
            if service and service.lower() != "generic":
                must_conditions.append(
                    models.Filter(
                        should=[
                            models.FieldCondition(
                                key="service",
                                match=models.MatchValue(value=service),
                            ),
                            models.FieldCondition(
                                key="service",
                                match=models.MatchValue(value="generic"),
                            ),
                        ]
                    )
                )

            # Incident type matching
            if incident_type:
                must_conditions.append(
                    models.FieldCondition(
                        key="incident_types",
                        match=models.MatchValue(value=incident_type),
                    )
                )

            query_filter = models.Filter(must=must_conditions) if must_conditions else None

            query_response = await self._client.query_points(
                collection_name=self.collection_name,
                query=query_vector,
                query_filter=query_filter,
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )

            results: list[RunbookSearchResult] = []
            for hit in query_response.points:
                if hit.payload:
                    hit_payload = dict(hit.payload)
                    snippet = hit_payload.pop("_searchable_snippet", None)
                    runbook = Runbook.model_validate(hit_payload)
                    results.append(
                        RunbookSearchResult(
                            runbook=runbook,
                            score=round(float(hit.score), 4),
                            matched_chunk=snippet,
                        )
                    )

            logger.info(f"Search for '{query[:40]}' returned {len(results)} runbooks")
            return results
        except Exception as exc:
            logger.error(f"Search error in collection '{self.collection_name}': {exc}")
            raise ExternalServiceException(
                service_name="Qdrant",
                message=f"Semantic runbook search failed: {exc}",
            ) from exc

    async def get_runbook(self, runbook_id: str) -> Runbook | None:
        """Retrieves a single runbook by ID. Returns None if ID is not a valid UUID."""
        if not self.is_valid_uuid(runbook_id):
            return None

        try:
            records = await self._client.retrieve(
                collection_name=self.collection_name,
                ids=[runbook_id],
                with_payload=True,
            )
            if not records or not records[0].payload:
                return None

            payload = dict(records[0].payload)
            payload.pop("_searchable_snippet", None)
            return Runbook.model_validate(payload)
        except UnexpectedResponse as exc:
            logger.warning(f"Runbook retrieval unexpected response for ID {runbook_id}: {exc}")
            return None
        except Exception as exc:
            logger.error(f"Failed to retrieve runbook {runbook_id}: {exc}")
            raise ExternalServiceException(
                service_name="Qdrant",
                message=f"Failed to retrieve runbook: {exc}",
            ) from exc

    async def delete_runbook(self, runbook_id: str) -> bool:
        """Deletes a runbook by ID from the vector store. Returns False if ID is invalid."""
        if not self.is_valid_uuid(runbook_id):
            return False

        try:
            await self._client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[runbook_id]),
            )
            logger.info(f"Deleted runbook ID {runbook_id}")
            return True
        except Exception as exc:
            logger.error(f"Failed to delete runbook {runbook_id}: {exc}")
            raise ExternalServiceException(
                service_name="Qdrant",
                message=f"Failed to delete runbook: {exc}",
            ) from exc

    async def list_runbooks(self, limit: int = 50) -> list[Runbook]:
        """Lists indexed runbooks up to limit."""
        try:
            points, _ = await self._client.scroll(
                collection_name=self.collection_name,
                limit=limit,
                with_payload=True,
            )
            runbooks: list[Runbook] = []
            for pt in points:
                if pt.payload:
                    payload = dict(pt.payload)
                    payload.pop("_searchable_snippet", None)
                    runbooks.append(Runbook.model_validate(payload))
            return runbooks
        except Exception as exc:
            logger.error(f"Failed to list runbooks: {exc}")
            raise ExternalServiceException(
                service_name="Qdrant",
                message=f"Failed to list runbooks: {exc}",
            ) from exc


_shared_qdrant_service: QdrantService | None = None


def get_shared_qdrant_service() -> QdrantService:
    """Provides application-wide singleton QdrantService instance."""
    global _shared_qdrant_service
    if _shared_qdrant_service is None:
        _shared_qdrant_service = QdrantService()
    return _shared_qdrant_service


async def close_shared_qdrant_service() -> None:
    """Gracefully closes the shared Qdrant connection pool on shutdown."""
    global _shared_qdrant_service
    if _shared_qdrant_service is not None:
        await _shared_qdrant_service.close()
        _shared_qdrant_service = None
        logger.info("Shared Qdrant connection pool closed.")
