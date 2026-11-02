import math
from datetime import UTC, datetime

import httpx
import pytest
from qdrant_client import AsyncQdrantClient

from app.constants.default_runbooks import DEFAULT_PRODUCTION_RUNBOOKS
from app.constants.enums import IncidentSeverity
from app.main import app
from app.routes.runbooks import get_qdrant_service
from app.schemas.runbook import Runbook, RunbookCreate
from app.services.embedding_service import EmbeddingService
from app.services.qdrant_service import QdrantService


@pytest.fixture
def embedding_service() -> EmbeddingService:
    return EmbeddingService(dimension=384)


@pytest.fixture
async def memory_qdrant(embedding_service: EmbeddingService) -> QdrantService:
    client = AsyncQdrantClient(":memory:")
    service = QdrantService(
        client=client,
        collection_name="test_runbooks",
        embedding_service=embedding_service,
    )
    await service.init_collection()
    yield service
    await client.close()


@pytest.mark.asyncio
async def test_embedding_dimensions_and_normalization(embedding_service: EmbeddingService):
    text = "High CPU spike detected in payment-service container"
    vector = await embedding_service.embed_text(text)

    assert len(vector) == 384
    # Check L2 unit length
    l2_norm = math.sqrt(sum(v * v for v in vector))
    assert math.isclose(l2_norm, 1.0, rel_tol=1e-4)


@pytest.mark.asyncio
async def test_embedding_semantic_cosine_similarity(embedding_service: EmbeddingService):
    text_cpu_1 = "Severe CPU saturation and container throttling in payment worker"
    text_cpu_2 = "High CPU spike causing thread starvation and high latency"
    text_db = "PostgreSQL deadlock and connection pool timeout error"

    vec_cpu_1 = await embedding_service.embed_text(text_cpu_1)
    vec_cpu_2 = await embedding_service.embed_text(text_cpu_2)
    vec_db = await embedding_service.embed_text(text_db)

    # Cosine similarity for unit vectors is simply dot product
    sim_cpu = sum(a * b for a, b in zip(vec_cpu_1, vec_cpu_2, strict=False))
    sim_cross = sum(a * b for a, b in zip(vec_cpu_1, vec_db, strict=False))

    assert sim_cpu > sim_cross
    assert sim_cpu > 0.25


@pytest.mark.asyncio
async def test_qdrant_upsert_and_retrieve(memory_qdrant: QdrantService):
    test_id = "00000000-0000-0000-0000-000000000001"
    runbook = Runbook(
        id=test_id,
        title="Custom Memory Leak Runbook",
        description="Runbook for debugging Node.js heap leaks",
        service="node-api",
        incident_types=["MEMORY_LEAK", "OOM_KILL"],
        severity_levels=[IncidentSeverity.HIGH],
        diagnostic_steps=["Check memory trend", "Inspect heap"],
        remediation_steps=["Restart pod", "Scale up"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    upserted_id = await memory_qdrant.upsert_runbook(runbook)
    assert upserted_id == test_id

    retrieved = await memory_qdrant.get_runbook(test_id)
    assert retrieved is not None
    assert retrieved.title == "Custom Memory Leak Runbook"
    assert retrieved.service == "node-api"
    assert "MEMORY_LEAK" in retrieved.incident_types


@pytest.mark.asyncio
async def test_qdrant_semantic_search_with_filtering(memory_qdrant: QdrantService):
    for rb in DEFAULT_PRODUCTION_RUNBOOKS:
        await memory_qdrant.upsert_runbook(rb)

    # Search for CPU issues
    results = await memory_qdrant.search_runbooks(
        query="CPU usage is at 98% and requests are timing out",
        limit=3,
        score_threshold=0.2,
    )
    assert len(results) > 0
    top_result = results[0]
    assert "CPU" in top_result.runbook.title or "CPU" in top_result.runbook.description
    assert top_result.score > 0.2

    # Search with service filter
    db_results = await memory_qdrant.search_runbooks(
        query="database connection pool exhausted and deadlock",
        service="postgres",
        limit=2,
        score_threshold=0.2,
    )
    assert len(db_results) > 0
    assert db_results[0].runbook.service in ("postgres", "generic")


@pytest.mark.asyncio
async def test_qdrant_delete_and_list(memory_qdrant: QdrantService):
    delete_id = "00000000-0000-0000-0000-000000000002"
    rb = Runbook(
        id=delete_id,
        title="Temporary Runbook",
        description="To be deleted soon",
        service="test-svc",
        incident_types=["TEST"],
        diagnostic_steps=["Step 1"],
        remediation_steps=["Step 2"],
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await memory_qdrant.upsert_runbook(rb)

    all_runbooks = await memory_qdrant.list_runbooks(limit=10)
    assert any(r.id == delete_id for r in all_runbooks)

    deleted = await memory_qdrant.delete_runbook(delete_id)
    assert deleted is True

    remaining = await memory_qdrant.list_runbooks(limit=10)
    assert not any(r.id == delete_id for r in remaining)


@pytest.mark.asyncio
async def test_runbooks_api_endpoints(client: httpx.AsyncClient, memory_qdrant: QdrantService):
    # Override get_qdrant_service dependency with our in-memory fixture
    app.dependency_overrides[get_qdrant_service] = lambda: memory_qdrant

    try:
        # 1. Health check
        health_res = await client.get("/api/v1/runbooks/health")
        assert health_res.status_code == 200
        assert health_res.json()["qdrant"] == "healthy"

        # 2. Seed production runbooks
        seed_res = await client.post("/api/v1/runbooks/seed")
        assert seed_res.status_code == 200
        seed_data = seed_res.json()
        assert seed_data["status"] == "success"
        assert seed_data["seeded_count"] == len(DEFAULT_PRODUCTION_RUNBOOKS)

        # 3. List runbooks
        list_res = await client.get("/api/v1/runbooks?limit=10")
        assert list_res.status_code == 200
        runbooks = list_res.json()
        assert len(runbooks) >= len(DEFAULT_PRODUCTION_RUNBOOKS)

        # 4. Search runbooks
        search_res = await client.post(
            "/api/v1/runbooks/search",
            json={
                "query": "OutOfMemoryError in payment container exit 137",
                "service": "payment-service",
                "incident_type": "OOM_KILL",
                "limit": 3,
                "score_threshold": 0.2,
            },
        )
        assert search_res.status_code == 200
        search_data = search_res.json()
        assert len(search_data) > 0
        assert (
            "OOM" in search_data[0]["runbook"]["title"]
            or "Memory" in search_data[0]["runbook"]["title"]
        )

        # 5. Create new runbook via API
        new_rb_payload = RunbookCreate(
            title="Kubernetes Ingress Crash",
            description="Ingress controller pod restart and 503 bad gateway",
            service="ingress-nginx",
            incident_types=["INGRESS_503", "CRASH_LOOP"],
            severity_levels=[IncidentSeverity.CRITICAL],
            diagnostic_steps=["Check ingress logs", "Inspect controller status"],
            remediation_steps=["Restart ingress controller"],
        ).model_dump(mode="json")

        create_res = await client.post("/api/v1/runbooks", json=new_rb_payload)
        assert create_res.status_code == 201
        created_rb = create_res.json()
        created_id = created_rb["id"]

        # 6. Retrieve by ID
        get_res = await client.get(f"/api/v1/runbooks/{created_id}")
        assert get_res.status_code == 200
        assert get_res.json()["title"] == "Kubernetes Ingress Crash"

        # 7. Delete by ID
        del_res = await client.delete(f"/api/v1/runbooks/{created_id}")
        assert del_res.status_code == 204

        # 8. Retrieve non-existent returns 404 RFC 7807
        not_found_res = await client.get(f"/api/v1/runbooks/{created_id}")
        assert not_found_res.status_code == 404
        assert "not found" in not_found_res.json()["title"].lower()

    finally:
        app.dependency_overrides.pop(get_qdrant_service, None)
