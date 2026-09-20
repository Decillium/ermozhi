import pytest
import datetime
import asyncio
from unittest.mock import AsyncMock, patch

from src.data.storage.blob_repo import BlobStorageRepository
from src.worker.lease_manager import WorkLeaseManager
from src.worker.pipeline import WorkerPipeline
from src.worker.jobs.reconciliation import ReconciliationJob


from src.data.snapshots.publisher import SnapshotPublisher
from src.contracts.v1 import MarketObservation


@pytest.fixture
def memory_repo():
    repo = BlobStorageRepository(use_memory_store=True)
    obs_list = [
        MarketObservation(date="2026-09-20", modal_price=14200.0, market="Erode"),
        MarketObservation(date="2026-09-19", modal_price=14100.0, market="Perundurai"),
        MarketObservation(date="2026-09-18", modal_price=13900.0, market="Gobichettipalayam"),
        MarketObservation(date="2026-09-17", modal_price=14000.0, market="Erode"),
    ]
    snapshot = SnapshotPublisher.build_snapshot(
        commodity="Turmeric",
        variety="Finger",
        district="Erode",
        observations=obs_list
    )
    SnapshotPublisher.publish(snapshot, repository=repo)
    return repo


class TestReconciliationJob:

    def test_recover_orphaned_inbox_item(self, memory_repo):
        lease_manager = WorkLeaseManager(repository=memory_repo)
        pipeline = WorkerPipeline(repository=memory_repo)
        job = ReconciliationJob(
            repository=memory_repo,
            lease_manager=lease_manager,
            pipeline=pipeline,
            orphan_threshold_seconds=600  # 10 mins
        )

        # Seed an orphaned item enqueued 20 minutes ago
        old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=20)).isoformat()
        message_id = "orphan_msg_001"
        work_item = {
            "message_id": message_id,
            "provider": "meta_whatsapp",
            "participant_ref": "+919876543210",
            "enqueued_at": old_time,
            "attempt": 1,
            "input": {
                "kind": "text",
                "text": "மஞ்சள் விரலி விலை 14500 ஈரோடு"
            },
            "locale_hint": "ta-IN"
        }
        memory_repo.save_json(f"inbox/{message_id}.json", work_item)

        # Run reconciliation
        stats = asyncio.run(job.run_reconciliation())

        assert stats["scanned"] == 1
        assert stats["orphans_found"] == 1
        assert stats["recovered"] == 1
        assert stats["dead_lettered"] == 0

        # Verify inbox and active are cleaned up
        assert memory_repo.load_json(f"inbox/{message_id}.json") is None
        assert memory_repo.load_json(f"work/active/{message_id}.json") is None

    def test_skip_fresh_inbox_items(self, memory_repo):
        lease_manager = WorkLeaseManager(repository=memory_repo)
        pipeline = WorkerPipeline(repository=memory_repo)
        job = ReconciliationJob(
            repository=memory_repo,
            lease_manager=lease_manager,
            pipeline=pipeline,
            orphan_threshold_seconds=600
        )

        # Fresh item enqueued 1 minute ago
        recent_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)).isoformat()
        message_id = "fresh_msg_002"
        work_item = {
            "message_id": message_id,
            "enqueued_at": recent_time,
            "attempt": 1,
            "input": {"kind": "text", "text": "மஞ்சள் விரலி 14500"}
        }
        memory_repo.save_json(f"inbox/{message_id}.json", work_item)

        stats = asyncio.run(job.run_reconciliation())

        assert stats["scanned"] == 1
        assert stats["orphans_found"] == 0
        assert stats["recovered"] == 0
        # Inbox item should remain untouched
        assert memory_repo.load_json(f"inbox/{message_id}.json") is not None

    def test_dead_letter_when_max_retries_exceeded(self, memory_repo):
        lease_manager = WorkLeaseManager(repository=memory_repo)
        pipeline = WorkerPipeline(repository=memory_repo)
        job = ReconciliationJob(
            repository=memory_repo,
            lease_manager=lease_manager,
            pipeline=pipeline,
            max_retries=3,
            orphan_threshold_seconds=600
        )

        old_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=30)).isoformat()
        message_id = "poison_msg_003"
        work_item = {
            "message_id": message_id,
            "enqueued_at": old_time,
            "attempt": 3,  # Reached max retries
            "input": {"kind": "text", "text": "corrupt message payload"}
        }
        memory_repo.save_json(f"inbox/{message_id}.json", work_item)

        stats = asyncio.run(job.run_reconciliation())

        assert stats["scanned"] == 1
        assert stats["orphans_found"] == 1
        assert stats["dead_lettered"] == 1
        assert stats["recovered"] == 0

        # Verify routed to dead-letter and purged from inbox
        assert memory_repo.load_json(f"inbox/{message_id}.json") is None
        dl_item = memory_repo.load_json(f"work/dead-letter/{message_id}.json")
        assert dl_item is not None
        assert dl_item["message_id"] == message_id
        assert "Exceeded max retries" in (dl_item.get("error_reason") or dl_item.get("error"))
