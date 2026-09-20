import os
import hmac
import json
import time
import hashlib
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.gateway.routes.meta import get_event_store
from src.platform.storage.event_store import EventStore
from src.data.storage.blob_repo import BlobStorageRepository
from src.gateway.middleware.rate_limit import default_rate_limiter


@pytest.fixture(autouse=True)
def setup_environment(monkeypatch):
    monkeypatch.setenv("META_APP_SECRET", "test_meta_secret_key_12345")
    monkeypatch.setenv("META_VERIFY_TOKEN", "my_meta_verify_token")
    default_rate_limiter.clear()


@pytest.fixture
def memory_event_store():
    repo = BlobStorageRepository(use_memory_store=True)
    store = EventStore(repository=repo)
    return store


@pytest.fixture
def client(memory_event_store):
    app.dependency_overrides[get_event_store] = lambda: memory_event_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def generate_meta_signature(body_bytes: bytes, secret: str) -> str:
    digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=body_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


class TestMetaWhatsAppWebhook:
    """Test suite for Meta WhatsApp Cloud API ingress."""

    def test_verify_challenge_handshake_success(self, client):
        response = client.get(
            "/api/v1/channels/meta-whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "my_meta_verify_token",
                "hub.challenge": "1158201444"
            }
        )
        assert response.status_code == 200
        assert response.text == "1158201444"

    def test_verify_challenge_handshake_invalid_token(self, client):
        response = client.get(
            "/api/v1/channels/meta-whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong_token",
                "hub.challenge": "1158201444"
            }
        )
        assert response.status_code == 403

    def test_verify_challenge_handshake_invalid_mode(self, client):
        response = client.get(
            "/api/v1/channels/meta-whatsapp/webhook",
            params={
                "hub.mode": "publish",
                "hub.verify_token": "my_meta_verify_token",
                "hub.challenge": "1158201444"
            }
        )
        assert response.status_code == 403

    def test_receive_signed_text_message_success(self, client, memory_event_store):
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1002345678",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "919876543210",
                                    "phone_number_id": "phone_id_1"
                                },
                                "contacts": [{"wa_id": "919876543210", "profile": {"name": "Farmer Selvam"}}],
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.HBgLMjAyNi4wOS4yM...",
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
        sig = generate_meta_signature(body_bytes, "test_meta_secret_key_12345")

        start_time = time.perf_counter()
        response = client.post(
            "/api/v1/channels/meta-whatsapp/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig
            }
        )
        latency_ms = (time.perf_counter() - start_time) * 1000

        assert response.status_code == 200
        assert latency_ms < 500.0  # Fast acknowledgement requirement (< 500ms)
        data = response.json()
        assert data["status"] == "ACCEPTED"
        assert "message_id" in data
        assert "event_id" in data
        assert data["is_duplicate"] is False

        # Verify durable storage
        inbox_item = memory_event_store.get_inbox_item(data["message_id"])
        assert inbox_item is not None
        assert inbox_item["provider"] == "meta_whatsapp"
        assert inbox_item["input"]["kind"] == "text"
        assert inbox_item["input"]["text"] == "மஞ்சள் விரலி 14000"

    def test_receive_signed_audio_message_success(self, client, memory_event_store):
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
                                        "id": "wamid.audio.12345",
                                        "timestamp": "1726800000",
                                        "type": "audio",
                                        "audio": {
                                            "id": "media_blob_999",
                                            "mime_type": "audio/ogg; codecs=opus"
                                        }
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
        sig = generate_meta_signature(body_bytes, "test_meta_secret_key_12345")

        response = client.post(
            "/api/v1/channels/meta-whatsapp/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ACCEPTED"

        inbox_item = memory_event_store.get_inbox_item(data["message_id"])
        assert inbox_item is not None
        assert inbox_item["input"]["kind"] == "audio"
        assert inbox_item["input"]["media_ref"] == "meta://media/media_blob_999"

    def test_reject_invalid_signature(self, client):
        payload = {"object": "whatsapp_business_account", "entry": []}
        body_bytes = json.dumps(payload).encode("utf-8")

        response = client.post(
            "/api/v1/channels/meta-whatsapp/webhook",
            content=body_bytes,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=invalid_hex_digest"
            }
        )
        assert response.status_code == 403

    def test_reject_missing_signature(self, client):
        payload = {"object": "whatsapp_business_account", "entry": []}
        body_bytes = json.dumps(payload).encode("utf-8")

        response = client.post(
            "/api/v1/channels/meta-whatsapp/webhook",
            content=body_bytes,
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 403
