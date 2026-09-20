import os
import uuid
import time
import datetime
import logging
from typing import Optional, Dict, Any, List, Tuple

from src.data.storage.blob_repo import BlobPathBuilder, BlobStorageRepository, StorageError

logger = logging.getLogger("WorkLeaseManager")


class LeaseError(Exception):
    """Base exception for lease operations."""
    pass


class WorkLeaseManager:
    """
    Manages work item leasing, renewal heartbeats, and lifecycle states in Azure Blob Storage:
    - inbox/{message_id}.json (backlog)
    - work/active/{message_id}.json (leased and in-flight)
    - work/dead-letter/{message_id}.json (poison messages / fatal failures)
    """

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        default_lease_duration_sec: int = 60
    ):
        self.repository = repository or BlobStorageRepository()
        self.default_lease_duration = default_lease_duration_sec
        # In-memory active lease registry: {message_id: (lease_id, expires_at_timestamp)}
        self._active_leases: Dict[str, Tuple[str, float]] = {}

    def scan_inbox(self, limit: int = 50) -> List[str]:
        """
        Scans `inbox/` for pending, unleased work items.
        Returns a list of message_ids.
        """
        all_inbox_blobs = self.repository.list_blobs(prefix="inbox/")
        now = time.time()
        available_message_ids = []

        for blob_path in all_inbox_blobs:
            # blob_path is e.g. "inbox/{message_id}.json"
            filename = os.path.basename(blob_path)
            if filename.endswith(".json"):
                msg_id = filename[:-5]
                # Check if currently leased and unexpired
                if msg_id in self._active_leases:
                    _, expires_at = self._active_leases[msg_id]
                    if now < expires_at:
                        continue  # Still actively leased by another worker
                available_message_ids.append(msg_id)
                if len(available_message_ids) >= limit:
                    break

        return available_message_ids

    def lease_work_item(
        self,
        message_id: str,
        duration_seconds: Optional[int] = None
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """
        Acquires an exclusive lease on an inbox work item.
        Writes to `work/active/{message_id}.json`.
        Returns Tuple[lease_id, work_item_data] if lease acquired, else None.
        """
        inbox_path = f"inbox/{message_id}.json"
        now = time.time()
        lease_duration = duration_seconds or self.default_lease_duration

        # 1. Check if already leased
        if message_id in self._active_leases:
            _, expires_at = self._active_leases[message_id]
            if now < expires_at:
                logger.info(f"Work item '{message_id}' is currently leased until {expires_at}.")
                return None

        # 2. Check inbox blob exists
        data = self.repository.load_json(inbox_path)
        if not data or not isinstance(data, dict):
            logger.warning(f"Work item '{message_id}' not found in inbox.")
            return None

        # 3. Create active lease
        lease_id = f"lease_{uuid.uuid4().hex[:12]}"
        expires_at = now + lease_duration
        self._active_leases[message_id] = (lease_id, expires_at)

        active_path = BlobPathBuilder.work_active_path(message_id)
        active_envelope = {
            "message_id": message_id,
            "lease_id": lease_id,
            "leased_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "expires_at": datetime.datetime.fromtimestamp(expires_at, tz=datetime.timezone.utc).isoformat(),
            "duration_seconds": lease_duration,
            "payload": data
        }

        try:
            self.repository.save_json(active_path, active_envelope)
            logger.info(f"Acquired lease [{lease_id}] on '{message_id}' for {lease_duration}s.")
            return lease_id, data
        except Exception as e:
            logger.error(f"Failed to record active lease for '{message_id}': {e}")
            if message_id in self._active_leases:
                del self._active_leases[message_id]
            return None

    def renew_lease(
        self,
        message_id: str,
        lease_id: str,
        extension_seconds: Optional[int] = None
    ) -> bool:
        """
        Renews an active lease heartbeat during long-running processing.
        """
        if message_id not in self._active_leases:
            logger.warning(f"Cannot renew lease for '{message_id}': no active lease found.")
            return False

        current_lease_id, _ = self._active_leases[message_id]
        if current_lease_id != lease_id:
            logger.warning(f"Cannot renew lease for '{message_id}': lease_id mismatch.")
            return False

        ext = extension_seconds or self.default_lease_duration
        now = time.time()
        new_expires_at = now + ext
        self._active_leases[message_id] = (lease_id, new_expires_at)

        active_path = BlobPathBuilder.work_active_path(message_id)
        active_data = self.repository.load_json(active_path)
        if active_data and isinstance(active_data, dict):
            active_data["expires_at"] = datetime.datetime.fromtimestamp(new_expires_at, tz=datetime.timezone.utc).isoformat()
            active_data["last_renewed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self.repository.save_json(active_path, active_data)

        logger.debug(f"Renewed lease [{lease_id}] for '{message_id}' (+{ext}s).")
        return True

    def complete_work_item(self, message_id: str, lease_id: str) -> bool:
        """
        Marks work item as completed:
        Deletes `inbox/{message_id}.json` and `work/active/{message_id}.json`, then releases in-memory lease.
        """
        inbox_path = f"inbox/{message_id}.json"
        active_path = BlobPathBuilder.work_active_path(message_id)

        self.repository.delete_blob(inbox_path)
        self.repository.delete_blob(active_path)

        if message_id in self._active_leases:
            del self._active_leases[message_id]

        logger.info(f"Completed and purged work item '{message_id}' [lease: {lease_id}].")
        return True

    def dead_letter_work_item(
        self,
        message_id: str,
        lease_id: str,
        error_reason: str,
        error_details: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Moves failed or poison message from inbox/ to work/dead-letter/{message_id}.json
        with error diagnostics, then releases the active lease.
        """
        inbox_path = f"inbox/{message_id}.json"
        active_path = BlobPathBuilder.work_active_path(message_id)
        dlq_path = BlobPathBuilder.work_dead_letter_path(message_id)

        inbox_data = self.repository.load_json(inbox_path) or {}

        dead_letter_payload = {
            "message_id": message_id,
            "lease_id": lease_id,
            "dead_lettered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "error_reason": error_reason,
            "error_details": error_details or {},
            "original_payload": inbox_data
        }

        self.repository.save_json(dlq_path, dead_letter_payload)
        self.repository.delete_blob(inbox_path)
        self.repository.delete_blob(active_path)

        if message_id in self._active_leases:
            del self._active_leases[message_id]

        logger.warning(f"Dead-lettered work item '{message_id}' to '{dlq_path}' (Reason: {error_reason}).")
        return dlq_path
