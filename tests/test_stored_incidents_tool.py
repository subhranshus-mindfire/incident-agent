import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.incident import IncidentCreate
from app.services.incident_service import IncidentService
from app.tools import chat_tools


@pytest.fixture
def db_factory(monkeypatch: pytest.MonkeyPatch):
    """Points the tool at the in-memory test database instead of PostgreSQL."""
    from tests.conftest import TestSessionLocal

    monkeypatch.setattr(chat_tools, "async_session_factory", TestSessionLocal)
    monkeypatch.setattr(
        chat_tools,
        "get_shared_qdrant_service",
        lambda: _NoMemory(),
    )
    return TestSessionLocal


class _NoMemory:
    async def list_historical_incident_ids(self):
        return None


async def test_stored_incidents_are_read_without_a_sign_in_token(
    db_session: AsyncSession, db_factory
) -> None:
    service = IncidentService(db_session)
    await service.create_incident(
        IncidentCreate(title="Payment latency spike", service="payment-api")
    )
    await service.create_incident(IncidentCreate(title="Order errors", service="order-service"))

    result = await chat_tools.list_stored_incidents.ainvoke({"service": "payment-api"})

    assert "error" not in result
    assert result["total_found"] == 1
    assert result["incidents"][0]["title"] == "Payment latency spike"
    assert result["incidents"][0]["service"] == "payment-api"


async def test_stored_incidents_reports_database_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Broken:
        def __call__(self):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(chat_tools, "async_session_factory", _Broken())

    result = await chat_tools.list_stored_incidents.ainvoke({})

    assert "database unavailable" in str(result)
