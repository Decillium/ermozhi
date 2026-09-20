import pytest
import datetime
from src.data.storage.blob_repo import BlobStorageRepository
from src.tools.replay import EventReplayManager
from src.worker.jobs.cleanup import CleanupJob


@pytest.fixture
def memory_repo():
    return BlobStorageRepository(use_memory_store=True)


class TestReplayToolAndCleanupJob:

    def test_list_and_replay_dead_letter(self, memory_repo):
        replay_mgr = EventReplayManager(repository=memory_repo)
        message_id = "failed_msg_101"

        # Seed a dead-letter item
        dlq_payload = {
            "message_id": message_id,
            "error_reason": "Gemini API rate limit exceeded",
            "dead_lettered_at": "2026-09-20T10:00:00Z",
            "original_payload": {
                "message_id": message_id,
                "input": {"kind": "text", "text": "மஞ்சள் விரலி விலை 14500"},
                "provider": "meta_whatsapp",
                "participant_ref": "+919876543210",
                "attempt": 3
            }
        }
        memory_repo.save_json(f"work/dead-letter/{message_id}.json", dlq_payload)

        # 1. Test listing
        items = replay_mgr.list_dead_letters()
        assert len(items) == 1
        assert items[0]["message_id"] == message_id
        assert items[0]["error_reason"] == "Gemini API rate limit exceeded"

        # 2. Test replay
        replayed = replay_mgr.replay_dead_letter(
            message_id=message_id,
            operator_id="operator_saravanan",
            reason="Quota replenished"
        )

        assert replayed["message_id"] == message_id
        assert replayed["attempt"] == 1
        assert replayed["replayed_by"] == "operator_saravanan"
        assert replayed["replay_reason"] == "Quota replenished"

        # Verify moved to inbox/ and deleted from dead-letter/
        assert memory_repo.load_json(f"work/dead-letter/{message_id}.json") is None
        assert memory_repo.load_json(f"inbox/{message_id}.json") is not None

    def test_replay_from_event_log(self, memory_repo):
        replay_mgr = EventReplayManager(repository=memory_repo)
        message_id = "evt_msg_202"
        event_path = f"events/2026/09/20/{message_id}.json"

        event_envelope = {
            "event_id": "evt_abc123",
            "message_id": message_id,
            "payload": {
                "message_id": message_id,
                "provider": "meta_whatsapp",
                "channel": "whatsapp",
                "participant_ref": "+919876543210",
                "input": {"kind": "text", "text": "மஞ்சள் விலை"}
            }
        }
        memory_repo.save_json(event_path, event_envelope)

        replayed = replay_mgr.replay_from_event(
            event_path=event_path,
            operator_id="admin_ops",
            reason="Farmer requested replay"
        )

        assert replayed["message_id"] == message_id
        assert replayed["attempt"] == 1
        assert memory_repo.load_json(f"inbox/{message_id}.json") is not None

    def test_cleanup_job_purges_expired_media_and_stale_leases(self, memory_repo):
        cleanup_job = CleanupJob(
            repository=memory_repo,
            retention_days=30,
            stale_lease_seconds=3600
        )

        now = datetime.datetime.now(datetime.timezone.utc)
        
        # 1. Old media blob (40 days old)
        old_date = now - datetime.timedelta(days=40)
        old_media_path = f"media/inbound/{old_date.year:04d}/{old_date.month:02d}/{old_date.day:02d}/old_audio.ogg"
        memory_repo.save_bytes(old_media_path, b"old_audio_data")

        # 2. Fresh media blob (5 days old)
        fresh_date = now - datetime.timedelta(days=5)
        fresh_media_path = f"media/inbound/{fresh_date.year:04d}/{fresh_date.month:02d}/{fresh_date.day:02d}/fresh_audio.ogg"
        memory_repo.save_bytes(fresh_media_path, b"fresh_audio_data")

        # 3. Stale active lease envelope (expired 2 hours ago)
        stale_lease_path = "work/active/stale_msg_303.json"
        stale_expires = (now - datetime.timedelta(hours=2)).isoformat()
        memory_repo.save_json(stale_lease_path, {
            "message_id": "stale_msg_303",
            "expires_at": stale_expires
        })

        # Run cleanup
        stats = cleanup_job.run_cleanup(current_time=now)

        assert stats["media_scanned"] == 2
        assert stats["media_deleted"] == 1
        assert stats["stale_leases_scanned"] == 1
        assert stats["stale_leases_deleted"] == 1

        # Assert old media deleted, fresh media retained
        assert memory_repo.load_bytes(old_media_path) is None
        assert memory_repo.load_bytes(fresh_media_path) is not None
        assert memory_repo.load_json(stale_lease_path) is None
