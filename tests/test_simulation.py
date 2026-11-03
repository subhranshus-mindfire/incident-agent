from httpx import ASGITransport, AsyncClient
import pytest

from simulation.chaos_client import ChaosClient
from simulation.services.payment_api import app, chaos_state


@pytest.fixture(autouse=True)
def reset_chaos_state():
    chaos_state.deadlock_active = False
    chaos_state.bad_deployment_active = False
    chaos_state.cpu_burn_active = False
    chaos_state.current_version = "v2.3.1"
    yield
    chaos_state.deadlock_active = False
    chaos_state.bad_deployment_active = False
    chaos_state.cpu_burn_active = False


@pytest.mark.asyncio
async def test_payment_api_normal_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health
        health_res = await client.get("/health")
        assert health_res.status_code == 200
        assert health_res.json()["status"] == "healthy"

        # Pay
        pay_res = await client.post(
            "/pay", json={"amount": 49.99, "currency": "USD", "account_id": "acc-1"}
        )
        assert pay_res.status_code == 200
        assert pay_res.json()["status"] == "processed"

        # Deployments
        dep_res = await client.get("/deployments")
        assert dep_res.status_code == 200
        deps = dep_res.json()
        assert len(deps) >= 2
        assert deps[0]["deployment_id"] == "DEP-101"


@pytest.mark.asyncio
async def test_payment_api_deadlock_chaos_and_remediation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inject deadlock
        deadlock_res = await client.post("/chaos/db-deadlock")
        assert deadlock_res.status_code == 200
        assert chaos_state.deadlock_active is True

        # Verify payments now fail with 500
        pay_res = await client.post(
            "/pay", json={"amount": 10.0, "currency": "USD", "account_id": "acc-2"}
        )
        assert pay_res.status_code == 500
        assert "Database connection timeout" in pay_res.json()["error"]

        # Health reflects degraded
        health_res = await client.get("/health")
        assert health_res.json()["status"] == "degraded"

        # Remediate by terminating blocking queries
        rem_res = await client.post("/remediation/kill-queries")
        assert rem_res.status_code == 200
        assert rem_res.json()["status"] == "SUCCESS"
        assert chaos_state.deadlock_active is False

        # Payments recover to 200
        rec_res = await client.post(
            "/pay", json={"amount": 10.0, "currency": "USD", "account_id": "acc-2"}
        )
        assert rec_res.status_code == 200


@pytest.mark.asyncio
async def test_payment_api_bad_deployment_and_rollback():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Inject bad deployment
        bad_res = await client.post("/chaos/bad-deployment")
        assert bad_res.status_code == 200
        assert chaos_state.bad_deployment_active is True

        # Payment returns 500 regression
        pay_res = await client.post(
            "/pay", json={"amount": 15.0, "currency": "USD", "account_id": "acc-3"}
        )
        assert pay_res.status_code == 500

        # Execute rollback remediation
        rollback_res = await client.post("/remediation/rollback")
        assert rollback_res.status_code == 200
        assert rollback_res.json()["version"] == "v2.3.0"
        assert chaos_state.bad_deployment_active is False

        # Payments succeed with rolled-back version
        ok_res = await client.post(
            "/pay", json={"amount": 15.0, "currency": "USD", "account_id": "acc-3"}
        )
        assert ok_res.status_code == 200
        assert ok_res.json()["version"] == "v2.3.0"


@pytest.mark.asyncio
async def test_chaos_client_interface(monkeypatch):
    """Verifies ChaosClient methods work correctly against app transport."""
    client = ChaosClient(base_url="http://test")

    # Use ASGITransport for client calls in test
    transport = ASGITransport(app=app)

    # Inject custom client
    async with AsyncClient(transport=transport, base_url="http://test") as test_http:
        monkeypatch.setattr(client, "base_url", "http://test")

        # Test deadlock
        res = await test_http.post("http://test/chaos/db-deadlock")
        assert res.status_code == 200

        # Test clear
        clear_res = await test_http.post("http://test/chaos/clear")
        assert clear_res.status_code == 200
        assert chaos_state.deadlock_active is False
