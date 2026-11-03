import numpy as np
import pytest

from app.services.embedding_service import EmbeddingService, FastEmbedProvider
from app.services.qdrant_service import incident_document_text


class FakeModel:
    """Stands in for a fastembed model: records which method was used and returns fixed vectors."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension
        self.calls: list[str] = []

    def passage_embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append("passage")
        return [np.ones(self.dimension, dtype=np.float32) for _ in texts]

    def query_embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append("query")
        return [np.ones(self.dimension, dtype=np.float32) for _ in texts]


async def test_documents_and_queries_use_their_own_embedding_modes() -> None:
    model = FakeModel(dimension=4)
    service = EmbeddingService(provider=FastEmbedProvider(model, dimension=4), dimension=4)
    assert len(await service.embed_document("runbook text")) == 4
    assert len(await service.embed_text("a search")) == 4
    assert model.calls == ["passage", "query"]


async def test_wrong_vector_size_is_rejected() -> None:
    service = EmbeddingService(
        provider=FastEmbedProvider(FakeModel(dimension=8), dimension=4), dimension=4
    )
    with pytest.raises(ValueError, match="expected 4"):
        await service.embed_document("text")


def test_incident_text_has_one_definition() -> None:
    text = incident_document_text("payment-api", "timeouts", "pool exhausted", "rollback")
    assert (
        text
        == "Service: payment-api | Symptoms: timeouts | Root Cause: pool exhausted | Remediation: rollback"
    )


async def test_configured_model_produces_normalised_384_dimensional_vectors() -> None:
    service = EmbeddingService(dimension=384)
    vector = await service.embed_document("payment-api database connection pool exhausted")
    assert len(vector) == 384
    assert abs(sum(x * x for x in vector) ** 0.5 - 1.0) < 1e-3
