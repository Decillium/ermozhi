import os
import hmac
import json
import hashlib
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.gateway.routes.meta import get_event_store as get_meta_store
from src.platform.storage.event_store import EventStore
from src.data.storage.blob_repo import BlobStorageRepository
from src.gateway.middleware.rate_limit import default_rate_limiter


@pytest.fixture(autouse=True)
def setup_environment(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "secret_key_dedup")
    default_rate_limiter.clear()


@pytest.fixture
def memory_event_store():
    repo = BlobStorageRepository(use_memory_store=True)
    return EventStore(repository=repo)


@pytest.fixture
def client(memory_event_store):
    app.dependency_overrides[get_meta_store] = lambda: memory_event_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_meta_sig(body_bytes: bytes, secret: str) -> str:
    digest = hmac.new(key=secret.encode("utf-8"), msg=body_bytes, digestmod=hashlib.sha256).hexdigest()
    return f"sha256={digest}"


class TestProviderDeduplication:
    """Test suite for idempotency and duplicate provider message suppression."""

    def test_meta_duplicate_message_id_suppression(self, client, memory_event_store):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1002345678",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.DEDUP.TEST.001",
                                        "timestamp": "1726800000",
                                        "type": "text",
                                        "text": {"body": "மஞ்சள் விரலி 14000"}
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        body_bytes = json.dumps(payload).encode("utf-8")
        sig = make_meta_sig(body_bytes, "secret_key_dedup")

        # 1. First Ingestion
        res1 = client.post(
            "/api/v1/channels/meta-whatsapp/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig}
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["is_duplicate"] is False
        first_msg_id = data1["message_id"]

        inbox_blobs_before = [b for b in memory_event_store.repository.list_blobs("inbox/")]
        assert len(inbox_blobs_before) == 1

        # 2. Duplicate Ingestion with same provider message ID
        res2 = client.post(
            "/api/v1/channels/meta-whatsapp/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig}
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["is_duplicate"] is True
        assert data2["message_id"] == first_msg_id

        # Inbox must still contain exactly 1 work item
        inbox_blobs_after = [b for b in memory_event_store.repository.list_blobs("inbox/")]
        assert len(inbox_blobs_after) == 1
