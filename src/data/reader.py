import time
import logging
from typing import Optional, Dict, Tuple

from src.contracts.v1 import (
    DataFreshnessState,
    MarketAggregates,
    MarketDataSnapshot,
)
from src.data.storage.blob_repo import BlobPathBuilder, BlobStorageRepository

logger = logging.getLogger("MarketSnapshotReader")


class MarketSnapshotReader:
    """
    Ultra-low latency, read-only market snapshot accessor for downstream workers.
    Guarantees < 50ms retrieval by reading directly from precomputed storage blobs
    with an in-memory TTL cache, eliminating blocking external API requests.
    """

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        cache_ttl_seconds: int = 60
    ):
        self.repository = repository or BlobStorageRepository()
        self.cache_ttl = cache_ttl_seconds
        self._cache: Dict[str, Tuple[float, MarketDataSnapshot]] = {}

    def get_latest_snapshot(
        self,
        commodity: str = "Turmeric",
        variety: str = "Finger",
        district: str = "Erode"
    ) -> MarketDataSnapshot:
        """
        Retrieves the precomputed MarketDataSnapshot for a given commodity/variety/district.
        Checks in-memory cache first, then loads from Azure Blob Storage.
        Falls back safely to an UNAVAILABLE snapshot if storage is empty.
        """
        c = commodity.strip().lower()
        v = variety.strip().lower()
        d = district.strip().lower().replace(" ", "_")
        cache_key = f"{c}:{v}:{d}"
        now = time.time()

        # 1. Check in-memory TTL cache
        if cache_key in self._cache:
            cached_time, snapshot = self._cache[cache_key]
            if (now - cached_time) < self.cache_ttl:
                return snapshot

        # 2. Load from storage
        blob_path = BlobPathBuilder.snapshot_latest_path(commodity=c, variety=v, district=d)
        data = self.repository.load_json(blob_path)

        if data and isinstance(data, dict):
            try:
                snapshot = MarketDataSnapshot.model_validate(data)
                self._cache[cache_key] = (now, snapshot)
                return snapshot
            except Exception as e:
                logger.error(f"Failed to validate cached snapshot at '{blob_path}': {e}")

        # 3. Fallback to canonical UNAVAILABLE snapshot
        fallback = self._create_unavailable_snapshot(commodity=commodity, variety=variety, district=district)
        return fallback

    def invalidate_cache(self) -> None:
        """Clears the in-memory cache."""
        self._cache.clear()

    @staticmethod
    def _create_unavailable_snapshot(
        commodity: str,
        variety: str,
        district: str
    ) -> MarketDataSnapshot:
        """Constructs a deterministic canonical UNAVAILABLE snapshot when data is missing."""
        empty_aggs = MarketAggregates(
            median=0.0,
            mean=0.0,
            min=0.0,
            max=0.0,
            volatility=0.0,
            trend="STABLE"
        )
        return MarketDataSnapshot(
            snapshot_id="snap_unavailable",
            crop=commodity,
            variety=variety,
            district=district,
            observations=[],
            aggregates=empty_aggs,
            observation_count=0,
            distinct_date_count=0,
            observed_at="",
            retrieved_at="",
            freshness_status=DataFreshnessState.UNAVAILABLE,
            quality_status="QUARANTINED"
        )
