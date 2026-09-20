import time
import pytest
from src.worker.lease_manager import WorkLeaseManager
from src.data.storage.blob_repo import BlobStorageRepository, BlobPathBuilder


@pytest.fixture
def repo():
    return BlobStorageRepository(use_memory_store=True)


@pytest.fixture
def lease_manager(repo):
    return WorkLeaseManager(repository=repo, default_lease_duration_sec=60)


class TestWorkLeaseManager:
    """Test suite for lease acquisition, heartbeat renewal, purge, and dead-letter routing."""

    def test_lease_acquisition_success(self, repo, lease_manager):
        message_id = "msg_test_001"
        repo.save_json(f"inbox/{message_id}.json", {"message_id": message_id, "data": "farmer_query"})

        # Acquire lease
        lease_res = lease_manager.lease_work_item(message_id, duration_seconds=30)
        assert lease_res is not None
        lease_id, work_data = lease_res
        assert lease_id.startswith("lease_")
        assert work_data["message_id"] == message_id

        # Verify active lease recorded in work/active/
        active_path = BlobPathBuilder.work_active_path(message_id)
        assert repo.exists(active_path)
        active_record = repo.load_json(active_path)
        assert active_record["lease_id"] == lease_id
        assert active_record["duration_seconds"] == 30

        # Second attempt while lease is active should fail (concurrency lock)
        second_attempt = lease_manager.lease_work_item(message_id)
        assert second_attempt is None

    def test_lease_renewal_heartbeat(self, repo, lease_manager):
        message_id = "msg_test_002"
        repo.save_json(f"inbox/{message_id}.json", {"message_id": message_id})

        lease_id, _ = lease_manager.lease_work_item(message_id, duration_seconds=10)
        
        # Renew lease for +30s
        renewed = lease_manager.renew_lease(message_id, lease_id, extension_seconds=30)
        assert renewed is True

        active_path = BlobPathBuilder.work_active_path(message_id)
        active_record = repo.load_json(active_path)
        assert "last_renewed_at" in active_record

        # Renewal with wrong lease_id should fail
        wrong_renew = lease_manager.renew_lease(message_id, "wrong_lease_id")
        assert wrong_renew is False

    def test_complete_work_item_purges_inbox_and_active(self, repo, lease_manager):
        message_id = "msg_test_003"
        inbox_path = f"inbox/{message_id}.json"
        repo.save_json(inbox_path, {"message_id": message_id})

        lease_id, _ = lease_manager.lease_work_item(message_id)
        assert repo.exists(inbox_path)
        assert repo.exists(BlobPathBuilder.work_active_path(message_id))

        # Complete
        completed = lease_manager.complete_work_item(message_id, lease_id)
        assert completed is True

        assert not repo.exists(inbox_path)
        assert not repo.exists(BlobPathBuilder.work_active_path(message_id))

    def test_dead_letter_routing_on_fatal_failure(self, repo, lease_manager):
        message_id = "msg_test_004"
        inbox_path = f"inbox/{message_id}.json"
        repo.save_json(inbox_path, {"message_id": message_id, "payload": "corrupted"})

        lease_id, _ = lease_manager.lease_work_item(message_id)

        # Dead letter
        dlq_path = lease_manager.dead_letter_work_item(
            message_id=message_id,
            lease_id=lease_id,
            error_reason="UnrecoverableAIError: malformed token stream",
            error_details={"attempt": 3, "status": "FAILED"}
        )

        assert dlq_path == BlobPathBuilder.work_dead_letter_path(message_id)
        assert repo.exists(dlq_path)
        assert not repo.exists(inbox_path)
        assert not repo.exists(BlobPathBuilder.work_active_path(message_id))

        dlq_data = repo.load_json(dlq_path)
        assert dlq_data["error_reason"] == "UnrecoverableAIError: malformed token stream"
        assert dlq_data["error_details"]["attempt"] == 3

    def test_scan_inbox_filters_leased_items(self, repo, lease_manager):
        repo.save_json("inbox/msg_a.json", {"message_id": "msg_a"})
        repo.save_json("inbox/msg_b.json", {"message_id": "msg_b"})
        repo.save_json("inbox/msg_c.json", {"message_id": "msg_c"})

        # Lease msg_b
        lease_manager.lease_work_item("msg_b", duration_seconds=60)

        # Scan should return msg_a and msg_c, skipping msg_b
        available = lease_manager.scan_inbox()
        assert "msg_a" in available
        assert "msg_c" in available
        assert "msg_b" not in available
