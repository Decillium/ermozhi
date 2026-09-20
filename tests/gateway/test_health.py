import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from src.app import app
from src.gateway.routes.health import get_event_store
from src.platform.storage.event_store import EventStore
from src.data.storage.blob_repo import BlobStorageRepository
from src.gateway.middleware.rate_limit import RateLimiter, check_rate_limit
from fastapi import HTTPException


@pytest.fixture
def memory_event_store():
    repo = BlobStorageRepository(use_memory_store=True)
    return EventStore(repository=repo)


@pytest.fixture
def client(memory_event_store):
    app.dependency_overrides[get_event_store] = lambda: memory_event_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestHealthAndReadiness:
    """Test suite for health and readiness probes and rate limiting."""

    def test_liveness_probe_returns_200(self, client):
        response = client.get("/api/v1/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ALIVE"
        assert "timestamp" in data

    def test_readiness_probe_healthy_storage_returns_200(self, client):
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "READY"
        assert data["storage"] == "CONNECTED"

    def test_readiness_probe_unhealthy_storage_returns_503(self):
        mock_store = MagicMock(spec=EventStore)
        mock_store.is_healthy.return_value = False

        app.dependency_overrides[get_event_store] = lambda: mock_store
        with TestClient(app) as test_client:
            response = test_client.get("/api/v1/health/ready")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "NOT_READY"
            assert data["storage"] == "UNAVAILABLE"
        app.dependency_overrides.clear()

    def test_rate_limiter_sliding_window_burst_protection(self):
        import asyncio
        limiter = RateLimiter(max_requests=3, window_seconds=10)
        key = "sender:+919876543210"

        # 3 requests allowed
        allowed1, remaining1, _ = limiter.is_allowed(key)
        assert allowed1 is True
        assert remaining1 == 2

        allowed2, remaining2, _ = limiter.is_allowed(key)
        assert allowed2 is True
        assert remaining2 == 1

        allowed3, remaining3, _ = limiter.is_allowed(key)
        assert allowed3 is True
        assert remaining3 == 0

        # 4th request rejected
        allowed4, remaining4, retry_after = limiter.is_allowed(key)
        assert allowed4 is False
        assert retry_after > 0

        # check_rate_limit raises 429
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(check_rate_limit(key, limiter=limiter))
        assert exc_info.value.status_code == 429
