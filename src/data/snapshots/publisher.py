import uuid
import datetime
import statistics
import logging
from typing import List, Dict, Any, Optional

from src.contracts.v1 import (
    DataFreshnessState,
    MarketObservation,
    MarketAggregates,
    MarketDataSnapshot,
)
from src.data.storage.blob_repo import BlobPathBuilder, BlobStorageRepository

logger = logging.getLogger("SnapshotPublisher")


class SnapshotPublisher:
    """
    Calculates statistical aggregates, enforces freshness SLAs,
    and publishes immutable market snapshots to Azure Blob Storage.
    """

    FRESHNESS_SLA_HOURS: int = 72
    MIN_DISTINCT_DATES_FOR_FRESH: int = 3

    @classmethod
    def build_snapshot(
        cls,
        commodity: str,
        variety: str,
        district: str,
        observations: List[MarketObservation],
        snapshot_id: Optional[str] = None,
        reference_time: Optional[datetime.datetime] = None
    ) -> MarketDataSnapshot:
        """
        Builds a canonical MarketDataSnapshot from a list of normalized MarketObservation records.
        """
        now = reference_time or datetime.datetime.now(datetime.timezone.utc)
        snap_id = snapshot_id or f"snap_{uuid.uuid4().hex[:12]}"

        # Filter and sort observations by date descending
        valid_obs = [
            obs for obs in observations
            if obs.modal_price > 0
        ]
        valid_obs.sort(key=lambda o: o.date, reverse=True)

        # 1. Zero observations case -> UNAVAILABLE
        if not valid_obs:
            empty_aggs = MarketAggregates(
                median=0.0,
                mean=0.0,
                min=0.0,
                max=0.0,
                volatility=0.0,
                trend="STABLE"
            )
            return MarketDataSnapshot(
                snapshot_id=snap_id,
                crop=commodity,
                variety=variety,
                district=district,
                observations=[],
                aggregates=empty_aggs,
                observation_count=0,
                distinct_date_count=0,
                observed_at=now.strftime("%Y-%m-%d"),
                retrieved_at=now.isoformat(),
                freshness_status=DataFreshnessState.UNAVAILABLE,
                quality_status="QUARANTINED"
            )

        # 2. Extract modal prices and dates
        prices = [obs.modal_price for obs in valid_obs]
        dates = [obs.date for obs in valid_obs]
        unique_dates = sorted(list(set(dates)), reverse=True)
        distinct_date_count = len(unique_dates)
        observation_count = len(valid_obs)

        # 3. Statistical Calculations
        med_price = float(statistics.median(prices))
        mean_price = float(statistics.mean(prices))
        min_price = min(prices)
        max_price = max(prices)
        stdev_price = float(statistics.stdev(prices)) if len(prices) > 1 else 0.0
        volatility = round((stdev_price / mean_price) * 100.0, 2) if mean_price > 0 else 0.0

        # 4. Trend Determination
        trend = "STABLE"
        if distinct_date_count >= 3:
            mid = len(unique_dates) // 2
            recent_dates = set(unique_dates[:mid])
            older_dates = set(unique_dates[mid:])

            recent_prices = [obs.modal_price for obs in valid_obs if obs.date in recent_dates]
            older_prices = [obs.modal_price for obs in valid_obs if obs.date in older_dates]

            if recent_prices and older_prices:
                rec_med = statistics.median(recent_prices)
                old_med = statistics.median(older_prices)
                pct_change = ((rec_med - old_med) / old_med) * 100.0 if old_med > 0 else 0.0
                if pct_change >= 2.0:
                    trend = "RISING"
                elif pct_change <= -2.0:
                    trend = "FALLING"

        aggregates = MarketAggregates(
            median=round(med_price, 2),
            mean=round(mean_price, 2),
            min=round(min_price, 2),
            max=round(max_price, 2),
            volatility=volatility,
            trend=trend
        )

        # 5. Freshness Evaluation
        latest_date_str = unique_dates[0]
        try:
            latest_date = datetime.date.fromisoformat(latest_date_str)
            ref_date = now.date() if isinstance(now, datetime.datetime) else now
            age_days = (ref_date - latest_date).days
            age_hours = age_days * 24
        except Exception:
            age_hours = 0

        if age_hours > cls.FRESHNESS_SLA_HOURS:
            freshness = DataFreshnessState.STALE
        elif distinct_date_count < cls.MIN_DISTINCT_DATES_FOR_FRESH:
            freshness = DataFreshnessState.INSUFFICIENT
        else:
            freshness = DataFreshnessState.FRESH

        return MarketDataSnapshot(
            snapshot_id=snap_id,
            crop=commodity,
            variety=variety,
            district=district,
            observations=valid_obs,
            aggregates=aggregates,
            observation_count=observation_count,
            distinct_date_count=distinct_date_count,
            observed_at=latest_date_str,
            retrieved_at=now.isoformat(),
            freshness_status=freshness,
            quality_status="APPROVED"
        )

    @classmethod
    def publish(
        cls,
        snapshot: MarketDataSnapshot,
        repository: BlobStorageRepository,
        batch_id: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Publishes the snapshot to Blob Storage:
        1. Atomic overwrite of 'latest.json'.
        2. Append immutable versioned snapshot.
        """
        bid = batch_id or uuid.uuid4().hex[:8]
        timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        latest_path = BlobPathBuilder.snapshot_latest_path(
            commodity=snapshot.crop,
            variety=snapshot.variety,
            district=snapshot.district
        )
        versioned_path = BlobPathBuilder.snapshot_versioned_path(
            commodity=snapshot.crop,
            variety=snapshot.variety,
            district=snapshot.district,
            timestamp_str=timestamp_str,
            batch_id=bid
        )

        snapshot_dict = snapshot.model_dump()

        # Save both latest and versioned blobs
        repository.save_json(latest_path, snapshot_dict)
        repository.save_json(versioned_path, snapshot_dict)

        logger.info(f"Published snapshot '{snapshot.snapshot_id}' to '{latest_path}' and '{versioned_path}'.")
        return {"latest": latest_path, "versioned": versioned_path}
