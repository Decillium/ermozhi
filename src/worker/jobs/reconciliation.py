import time
import logging
import datetime
from typing import Optional, Dict, Any, List

from src.data.storage.blob_repo import BlobStorageRepository
from src.worker.lease_manager import WorkLeaseManager
from src.worker.pipeline import WorkerPipeline

logger = logging.getLogger("ReconciliationJob")


class ReconciliationJob:
    """
    Scheduled reconciliation loop for recovering orphaned inbox work items:
    - Scans inbox/ for messages older than orphan_threshold_seconds (e.g. 10 minutes) without active leases.
    - Re-acquires leases and attempts re-processing through WorkerPipeline.
    - Tracks attempt counts; if retry limit (e.g. 3 attempts) is exceeded, routes item to work/dead-letter/{message_id}.json.
    """

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        lease_manager: Optional[WorkLeaseManager] = None,
        pipeline: Optional[WorkerPipeline] = None,
        max_retries: int = 3,
        orphan_threshold_seconds: int = 600
    ):
        self.repository = repository or BlobStorageRepository()
        self.lease_manager = lease_manager or WorkLeaseManager(repository=self.repository)
        self.pipeline = pipeline or WorkerPipeline(repository=self.repository)
        self.max_retries = max_retries
        self.orphan_threshold_seconds = orphan_threshold_seconds

    def is_orphan(self, work_item: Dict[str, Any], current_time: Optional[datetime.datetime] = None) -> bool:
        """
        Determines whether a work item is an orphan based on enqueue timestamp.
        """
        enqueued_at_str = work_item.get("enqueued_at") or work_item.get("received_at")
        if not enqueued_at_str:
            return True

        try:
            dt = datetime.datetime.fromisoformat(enqueued_at_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            
            now = current_time or datetime.datetime.now(datetime.timezone.utc)
            age_seconds = (now - dt).total_seconds()
            return age_seconds >= self.orphan_threshold_seconds
        except Exception as e:
            logger.warning(f"Error parsing timestamp '{enqueued_at_str}': {e}. Treating as candidate orphan.")
            return True

    async def run_reconciliation(self, current_time: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        """
        Executes a single reconciliation cycle across all inbox blobs.
        """
        stats = {
            "scanned": 0,
            "orphans_found": 0,
            "recovered": 0,
            "dead_lettered": 0,
            "retried": 0,
            "skipped_active": 0
        }

        # scan_inbox returns list of available message_ids
        available_message_ids = self.lease_manager.scan_inbox(limit=100)
        stats["scanned"] = len(available_message_ids)

        for message_id in available_message_ids:
            inbox_path = f"inbox/{message_id}.json"
            work_item = self.repository.load_json(inbox_path)
            if not work_item or not isinstance(work_item, dict):
                continue

            # Check if orphan
            if not self.is_orphan(work_item, current_time=current_time):
                continue

            stats["orphans_found"] += 1
            logger.info(f"Reconciliation candidate discovered: message_id={message_id}")

            # Acquire exclusive lease
            lease_res = self.lease_manager.lease_work_item(message_id, duration_seconds=60)
            if not lease_res:
                logger.info(f"Message '{message_id}' is actively leased by another worker. Skipping.")
                stats["skipped_active"] += 1
                continue

            lease_id, leased_work_item = lease_res
            attempt = int(leased_work_item.get("attempt", 1))

            if attempt >= self.max_retries:
                logger.warning(f"Message '{message_id}' reached max retries ({attempt}/{self.max_retries}). Routing to Dead-Letter Queue.")
                self.lease_manager.dead_letter_work_item(
                    message_id=message_id,
                    lease_id=lease_id,
                    error_reason=f"Exceeded max retries threshold ({self.max_retries})",
                    error_details=leased_work_item
                )
                stats["dead_lettered"] += 1
                continue

            # Increment attempt count and save back to inbox
            leased_work_item["attempt"] = attempt + 1
            leased_work_item["last_reconciled_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.repository.save_json(f"inbox/{message_id}.json", leased_work_item)

            try:
                logger.info(f"Re-executing pipeline for orphaned message '{message_id}' (attempt={attempt + 1})...")
                res = await self.pipeline.process_work_item(leased_work_item)
                self.lease_manager.complete_work_item(message_id, lease_id)
                stats["recovered"] += 1
                logger.info(f"Successfully recovered message '{message_id}' (status={res.get('status')}).")
            except Exception as exc:
                logger.error(f"Reconciliation execution failure for '{message_id}': {exc}")
                if (attempt + 1) >= self.max_retries:
                    self.lease_manager.dead_letter_work_item(
                        message_id=message_id,
                        lease_id=lease_id,
                        error_reason=str(exc),
                        error_details=leased_work_item
                    )
                    stats["dead_lettered"] += 1
                else:
                    # Release active lease
                    self.repository.delete_blob(f"work/active/{message_id}.json")
                    if message_id in self.lease_manager._active_leases:
                        del self.lease_manager._active_leases[message_id]
                    stats["retried"] += 1

        return stats
