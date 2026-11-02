import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app


@pytest.mark.asyncio
async def test_list_incidents():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/incidents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert "id" in data[0]
        assert "service" in data[0]


@pytest.mark.asyncio
async def test_create_and_get_incident():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        new_incident = {
            "title": "Database Connection Pool Exhausted",
            "service": "auth-service",
            "severity": "high",
            "description": "Max connections reached on primary replica"
        }
        create_res = await client.post("/api/v1/incidents", json=new_incident)
        assert create_res.status_code == 201
        created_data = create_res.json()
        assert created_data["title"] == new_incident["title"]
        assert created_data["service"] == new_incident["service"]
        incident_id = created_data["id"]

        # Fetch created incident
        get_res = await client.get(f"/api/v1/incidents/{incident_id}")
        assert get_res.status_code == 200
        fetched_data = get_res.json()
        assert fetched_data["id"] == incident_id
        assert fetched_data["title"] == new_incident["title"]


@pytest.mark.asyncio
async def test_get_nonexistent_incident():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/incidents/inc-non-existent-999")
        assert response.status_code == 404
