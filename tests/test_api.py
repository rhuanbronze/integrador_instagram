from types import SimpleNamespace

import httpx
import pytest

from app.main import app
from app.services.instagram_service import JobBusyError


@pytest.fixture
async def client(settings, sessions, engine):
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.engine = engine
    app.state.service = SimpleNamespace(busy=False)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as instance:
        yield instance


async def test_health_and_empty_status(client):
    assert (await client.get("/health")).json() == {"status": "ok", "database": "ok"}
    response = await client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["accounts_count"] == 0
    assert response.json()["last_collection_at"] is None
    assert "fake-token" not in response.text


async def test_all_post_endpoints_require_header_not_query(client):
    for job_type in ("account", "media", "all"):
        assert (await client.post(f"/api/jobs/{job_type}")).status_code == 401
        response = await client.post(f"/api/jobs/{job_type}?api_key=fake-admin-key")
        assert response.status_code == 401
        assert "fake-admin" not in response.text


async def test_manual_accept_and_busy_response(client):
    async def accept(job_type):
        assert job_type == "all"
        return [1, 2]

    app.state.service.submit = accept
    response = await client.post("/api/jobs/all", headers={"X-API-Key": "fake-admin-key"})
    assert response.status_code == 202 and response.json()["run_ids"] == [1, 2]

    async def busy(_):
        raise JobBusyError()

    app.state.service.submit = busy
    response = await client.post("/api/jobs/account", headers={"X-API-Key": "fake-admin-key"})
    assert response.status_code == 409


async def test_internal_error_is_sanitized(client):
    async def failure(_):
        raise RuntimeError("fake-token-never-real fake-db-password fake-admin-key")

    app.state.service.submit = failure
    response = await client.post("/api/jobs/all", headers={"X-API-Key": "fake-admin-key"})
    assert response.status_code == 500
    assert "fake-" not in response.text


async def test_health_database_failure_is_503(client, monkeypatch):
    def fail(_):
        raise RuntimeError("fake-db-password")

    monkeypatch.setattr("app.api.routes_health.check_database", fail)
    response = await client.get("/health")
    assert response.status_code == 503
    assert "fake-db" not in response.text
