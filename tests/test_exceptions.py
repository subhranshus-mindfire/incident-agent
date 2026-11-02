import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rfc7807_not_found_exception(client: AsyncClient):
    response = await client.get("/api/v1/incidents/inc-nonexistent-404")
    assert response.status_code == 404
    data = response.json()
    assert data["status"] == 404
    assert data["title"] == "Resource Not Found"
    assert data["code"] == "RESOURCE_NOT_FOUND"
    assert "Incident with ID 'inc-nonexistent-404' not found." in data["detail"]
    assert data["instance"] == "/api/v1/incidents/inc-nonexistent-404"
    assert "timestamp" in data
    assert data["details"]["entity_name"] == "Incident"


@pytest.mark.asyncio
async def test_rfc7807_validation_error(client: AsyncClient):
    # Missing required 'title' and 'service'
    invalid_payload = {"severity": "critical"}
    response = await client.post("/api/v1/incidents", json=invalid_payload)
    assert response.status_code == 422
    data = response.json()
    assert data["status"] == 422
    assert data["code"] == "VALIDATION_ERROR"
    assert "invalid_params" in data
    param_names = [p["name"] for p in data["invalid_params"]]
    assert any("title" in p for p in param_names)
    assert any("service" in p for p in param_names)
