import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_incidents_empty(client: AsyncClient):
    response = await client.get("/api/v1/incidents")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_and_fetch_incident_lifecycle(client: AsyncClient):
    payload = {
        "title": "Payment Gateway Timeout Surge",
        "service": "payment-service",
        "severity": "critical",
        "description": "504 Gateway Timeout spike following deployment v2.1.0",
        "extra_metadata": {"cluster": "prod-us-east-1"},
    }
    # Create
    create_res = await client.post("/api/v1/incidents", json=payload)
    assert create_res.status_code == 201
    created_data = create_res.json()
    assert created_data["title"] == payload["title"]
    assert created_data["service"] == payload["service"]
    assert created_data["severity"] == "critical"
    assert created_data["status"] == "open"
    incident_id = created_data["id"]

    # Fetch by ID
    get_res = await client.get(f"/api/v1/incidents/{incident_id}")
    assert get_res.status_code == 200
    fetched_data = get_res.json()
    assert fetched_data["id"] == incident_id
    assert fetched_data["title"] == payload["title"]

    # Update Status
    patch_res = await client.patch(
        f"/api/v1/incidents/{incident_id}/status",
        json={"status": "investigating", "reason": "Automated triage started"},
    )
    assert patch_res.status_code == 200
    updated_data = patch_res.json()
    assert updated_data["status"] == "investigating"

    # List with filter
    filter_res = await client.get("/api/v1/incidents?service=payment-service&severity=critical")
    assert filter_res.status_code == 200
    list_data = filter_res.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == incident_id


@pytest.mark.asyncio
async def test_get_nonexistent_incident(client: AsyncClient):
    response = await client.get("/api/v1/incidents/inc-nonexistent-404")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()
