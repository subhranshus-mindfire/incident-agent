"""Dense text embeddings for Qdrant.

Uses a BAAI bge model through fastembed (ONNX, no PyTorch). Documents and queries are embedded
differently, as bge expects: documents are indexed with `passage_embed`, searches use `query_embed`.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final, Protocol

from fastembed import TextEmbedding

from app.config.config import settings

logger = logging.getLogger("incident_agent.embedding_service")

MAX_TEXT_CHARS: Final = 4000


class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class FastEmbedProvider:
    """A fastembed text model, run off the event loop because inference is synchronous."""

    def __init__(self, model: Any, dimension: int) -> None:
        self._model = model
        self.dimension = dimension

    @classmethod
    def load(cls, model_name: str, dimension: int, cache_dir: str) -> FastEmbedProvider:
        logger.info(f"Loading embedding model '{model_name}' (cache: {cache_dir})")
        return cls(TextEmbedding(model_name=model_name, cache_dir=cache_dir), dimension)

    def _checked(self, vectors: list[list[float]]) -> list[list[float]]:
        if any(len(v) != self.dimension for v in vectors):
            raise ValueError(
                f"Embedding model returned vectors of size {len(vectors[0])}, expected {self.dimension}"
            )
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        clipped = [t[:MAX_TEXT_CHARS] for t in texts]
        vectors = await asyncio.to_thread(
            lambda: [v.tolist() for v in self._model.passage_embed(clipped)]
        )
        return self._checked(vectors)

    async def embed_query(self, text: str) -> list[float]:
        clipped = text[:MAX_TEXT_CHARS]
        vectors = await asyncio.to_thread(
            lambda: [v.tolist() for v in self._model.query_embed([clipped])]
        )
        return self._checked(vectors)[0]


class EmbeddingService:
    """Turns text into vectors for indexing (documents) and for searching (queries)."""

    def __init__(
        self, provider: EmbeddingProvider | None = None, dimension: int | None = None
    ) -> None:
        self.dimension = dimension or settings.EMBEDDING_DIMENSION
        self._provider: EmbeddingProvider = provider or FastEmbedProvider.load(
            model_name=settings.EMBEDDING_MODEL,
            dimension=self.dimension,
            cache_dir=settings.FASTEMBED_CACHE_DIR,
        )

    async def embed_document(self, text: str) -> list[float]:
        """Vector for text that is stored in the index."""
        (vector,) = await self._provider.embed_documents([text])
        return vector

    async def embed_text(self, text: str) -> list[float]:
        """Vector for a search query."""
        return await self._provider.embed_query(text)


_default_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Returns the process-wide EmbeddingService, loading the model on first use."""
    global _default_embedding_service
    if _default_embedding_service is None:
        _default_embedding_service = EmbeddingService()
    return _default_embedding_service
