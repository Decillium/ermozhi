import time
import datetime
import pytest
from src.contracts.v1 import DataFreshnessState, MarketObservation
from src.data.snapshots.publisher import SnapshotPublisher
from src.data.storage.blob_repo import BlobStorageRepository, BlobPathBuilder
from src.data.reader import MarketSnapshotReader


class TestMarketSnapshots:
    """Test suite for snapshot statistical calculations, freshness state machine, and fast reader access."""

    def test_snapshot_statistical_aggregates(self):
        # 4 distinct dates of observations
        obs_list = [
            MarketObservation(date="2026-09-20", modal_price=14500.0, market="Erode"),
            MarketObservation(date="2026-09-19", modal_price=14200.0, market="Perundurai"),
            MarketObservation(date="2026-09-18", modal_price=14000.0, market="Gobichettipalayam"),
            MarketObservation(date="2026-09-17", modal_price=13800.0, market="Erode"),
        ]

        now = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        snapshot = SnapshotPublisher.build_snapshot(
            commodity="Turmeric",
            variety="Finger",
            district="Erode",
            observations=obs_list,
            reference_time=now
        )

        assert snapshot.crop == "Turmeric"
        assert snapshot.variety == "Finger"
        assert snapshot.district == "Erode"
        assert snapshot.observation_count == 4
        assert snapshot.distinct_date_count == 4
        assert snapshot.aggregates.median == 14100.0  # median of [14500, 14200, 14000, 13800] -> (14200+14000)/2 = 14100
        assert snapshot.aggregates.min == 13800.0
        assert snapshot.aggregates.max == 14500.0
        assert snapshot.aggregates.volatility > 0.0
        assert snapshot.aggregates.trend in ["RISING", "STABLE", "FALLING"]
        assert snapshot.freshness_status == DataFreshnessState.FRESH

    def test_snapshot_freshness_fresh_state(self):
        # Exactly 3 distinct observation dates within 72 hours
        obs_list = [
            MarketObservation(date="2026-09-20", modal_price=14200.0, market="Erode"),
            MarketObservation(date="2026-09-19", modal_price=14100.0, market="Perundurai"),
            MarketObservation(date="2026-09-18", modal_price=13900.0, market="Gobichettipalayam"),
        ]
        ref_time = datetime.datetime(2026, 9, 20, 15, 0, 0, tzinfo=datetime.timezone.utc)
        snapshot = SnapshotPublisher.build_snapshot(
            commodity="Turmeric",
            variety="Finger",
            district="Erode",
            observations=obs_list,
            reference_time=ref_time
        )
        assert snapshot.freshness_status == DataFreshnessState.FRESH
        assert snapshot.distinct_date_count == 3

    def test_snapshot_freshness_stale_state(self):
        # Data is older than 72 hours (e.g. 5 days old)
        obs_list = [
            MarketObservation(date="2026-09-10", modal_price=13500.0, market="Erode"),
            MarketObservation(date="2026-09-09", modal_price=13400.0, market="Perundurai"),
            MarketObservation(date="2026-09-08", modal_price=13300.0, market="Gobichettipalayam"),
        ]
        # Reference time is 10 days later
        ref_time = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        snapshot = SnapshotPublisher.build_snapshot(
            commodity="Turmeric",
            variety="Finger",
            district="Erode",
            observations=obs_list,
            reference_time=ref_time
        )
        assert snapshot.freshness_status == DataFreshnessState.STALE
        assert snapshot.distinct_date_count == 3

    def test_snapshot_freshness_insufficient_state(self):
        # Only 2 distinct dates (minimum 3 required for FRESH)
        obs_list = [
            MarketObservation(date="2026-09-20", modal_price=14200.0, market="Erode"),
            MarketObservation(date="2026-09-20", modal_price=14150.0, market="Perundurai"),
            MarketObservation(date="2026-09-19", modal_price=14100.0, market="Gobichettipalayam"),
        ]
        ref_time = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        snapshot = SnapshotPublisher.build_snapshot(
            commodity="Turmeric",
            variety="Finger",
            district="Erode",
            observations=obs_list,
            reference_time=ref_time
        )
        assert snapshot.freshness_status == DataFreshnessState.INSUFFICIENT
        assert snapshot.distinct_date_count == 2

    def test_snapshot_unavailable_when_empty(self):
        ref_time = datetime.datetime(2026, 9, 20, 12, 0, 0, tzinfo=datetime.timezone.utc)
        snapshot = SnapshotPublisher.build_snapshot(
            commodity="Turmeric",
            variety="Finger",
            district="Erode",
            observations=[],
            reference_time=ref_time
        )
        assert snapshot.freshness_status == DataFreshnessState.UNAVAILABLE
        assert snapshot.observation_count == 0
        assert snapshot.aggregates.median == 0.0

    def test_snapshot_publication_and_fast_reader(self):
        repo = BlobStorageRepository(use_memory_store=True)
        obs_list = [
            MarketObservation(date="2026-09-20", modal_price=14200.0, market="Erode"),
            MarketObservation(date="2026-09-19", modal_price=14100.0, market="Perundurai"),
            MarketObservation(date="2026-09-18", modal_price=13900.0, market="Gobichettipalayam"),
        ]
        snapshot = SnapshotPublisher.build_snapshot(
            commodity="Turmeric",
            variety="Finger",
            district="Erode",
            observations=obs_list
        )

        paths = SnapshotPublisher.publish(snapshot=snapshot, repository=repo, batch_id="test_b1")
        assert "latest" in paths
        assert "versioned" in paths
        assert repo.exists(paths["latest"])
        assert repo.exists(paths["versioned"])

        # Test MarketSnapshotReader speed and content
        reader = MarketSnapshotReader(repository=repo, cache_ttl_seconds=10)
        
        start_time = time.perf_counter()
        loaded_snapshot = reader.get_latest_snapshot(commodity="Turmeric", variety="Finger", district="Erode")
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        assert elapsed_ms < 50.0  # Fast retrieval requirement
        assert loaded_snapshot.crop == "Turmeric"
        assert loaded_snapshot.variety == "Finger"
        assert loaded_snapshot.district == "Erode"
        assert loaded_snapshot.aggregates.median == 14100.0

        # Repeated call from in-memory cache should be virtually 0ms
        start_cached = time.perf_counter()
        cached_snapshot = reader.get_latest_snapshot(commodity="Turmeric", variety="Finger", district="Erode")
        elapsed_cached_ms = (time.perf_counter() - start_cached) * 1000
        assert elapsed_cached_ms < 5.0
        assert cached_snapshot.snapshot_id == loaded_snapshot.snapshot_id

    def test_reader_missing_snapshot_safe_fallback(self):
        repo = BlobStorageRepository(use_memory_store=True)
        reader = MarketSnapshotReader(repository=repo)

        fallback = reader.get_latest_snapshot(commodity="Cardamom", variety="Small", district="Idukki")
        assert fallback.freshness_status == DataFreshnessState.UNAVAILABLE
        assert fallback.aggregates.median == 0.0
        assert fallback.observation_count == 0
