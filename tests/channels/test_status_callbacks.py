import pytest
import datetime
from fastapi.testclient import TestClient

from src.app import app
from src.data.storage.blob_repo import BlobStorageRepository
from src.gateway.routes.status import get_repository


@pytest.fixture
def memory_repo():
    return BlobStorageRepository(use_memory_store=True)


@pytest.fixture
def client(memory_repo):
    app.dependency_overrides[get_repository] = lambda: memory_repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


class TestDeliveryStatusCallbacks:

    def test_meta_delivery_status_sent_and_delivered(self, client, memory_repo):
        wamid = "wamid.HBgLMTIzNDU2Nzg5MA=="
        
        # 1. First webhook: sent
        sent_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_1",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"display_phone_number": "919876543210", "phone_number_id": "1000123456"},
                                "statuses": [
                                    {
                                        "id": wamid,
                                        "status": "sent",
                                        "timestamp": "1726830000",
                                        "recipient_id": "919876543210"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        res1 = client.post("/api/v1/channels/meta-whatsapp/status", json=sent_payload)
        assert res1.status_code == 200
        assert res1.json()["status"] == "acknowledged"
        assert res1.json()["recorded_transitions"] == 1

        # 2. Second webhook: delivered
        delivered_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID_1",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "statuses": [
                                    {
                                        "id": wamid,
                                        "status": "delivered",
                                        "timestamp": "1726830005",
                                        "recipient_id": "919876543210"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }
        res2 = client.post("/api/v1/channels/meta-whatsapp/status", json=delivered_payload)
        assert res2.status_code == 200

        # Check storage
        now = datetime.datetime.now(datetime.timezone.utc)
        status_path = f"events/{now.year:04d}/{now.month:02d}/{now.day:02d}/{wamid}_status.json"
        data = memory_repo.load_json(status_path)
        assert data is not None
        assert data["identifier"] == wamid
        assert data["current_status"] == "delivered"
        assert len(data["transitions"]) == 2
        assert data["transitions"][0]["status"] == "sent"
        assert data["transitions"][1]["status"] == "delivered"
