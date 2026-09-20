import os
import time
import logging
import datetime
from typing import Optional, Dict, Any, List

from src.data.storage.blob_repo import BlobStorageRepository

logger = logging.getLogger("MediaCleanupJob")


class CleanupJob:
    """
    Scheduled retention and garbage collection job for Azure Blob Storage:
    - Purges inbound and outbound audio blobs older than retention_days (e.g. 30 days).
    - Cleans up stale orphaned work/active/ lease envelopes (> 1 hour old with expired timestamp).
    """

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        retention_days: int = 30,
        stale_lease_seconds: int = 3600
    ):
        self.repository = repository or BlobStorageRepository()
        self.retention_days = retention_days
        self.stale_lease_seconds = stale_lease_seconds

    def run_cleanup(self, current_time: Optional[datetime.datetime] = None) -> Dict[str, Any]:
        """
        Executes media and active lease cleanup.
        """
        now = current_time or datetime.datetime.now(datetime.timezone.utc)
        stats = {
            "media_scanned": 0,
            "media_deleted": 0,
            "stale_leases_scanned": 0,
            "stale_leases_deleted": 0
        }

        # 1. Cleanup media/ (inbound and outbound)
        media_blobs = self.repository.list_blobs(prefix="media/")
        stats["media_scanned"] = len(media_blobs)

        for blob_path in media_blobs:
            # Parse YYYY/MM/DD from path: media/inbound/YYYY/MM/DD/message_id.ogg
            parts = blob_path.split("/")
            if len(parts) >= 5:
                try:
                    yyyy, mm, dd = int(parts[2]), int(parts[3]), int(parts[4])
                    blob_date = datetime.datetime(yyyy, mm, dd, tzinfo=datetime.timezone.utc)
                    age_days = (now - blob_date).days
                    if age_days >= self.retention_days:
                        self.repository.delete_blob(blob_path)
                        stats["media_deleted"] += 1
                        logger.info(f"Purged expired media blob: {blob_path} (Age: {age_days} days).")
                except Exception as e:
                    logger.debug(f"Could not parse date from media path '{blob_path}': {e}")

        # 2. Cleanup work/active/ stale leases
        active_blobs = self.repository.list_blobs(prefix="work/active/")
        stats["stale_leases_scanned"] = len(active_blobs)

        for blob_path in active_blobs:
            data = self.repository.load_json(blob_path)
            if data and isinstance(data, dict):
                expires_at_str = data.get("expires_at")
                if expires_at_str:
                    try:
                        exp_dt = datetime.datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=datetime.timezone.utc)
                        # If expired by more than stale_lease_seconds
                        if (now - exp_dt).total_seconds() > self.stale_lease_seconds:
                            self.repository.delete_blob(blob_path)
                            stats["stale_leases_deleted"] += 1
                            logger.info(f"Purged stale active lease envelope: {blob_path}")
                    except Exception as e:
                        logger.debug(f"Error parsing expires_at in '{blob_path}': {e}")

        return stats


def main():
    job = CleanupJob()
    stats = job.run_cleanup()
    print(f"Cleanup Job Complete: {stats}")


if __name__ == "__main__":
    main()
