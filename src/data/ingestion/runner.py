import os
import uuid
import datetime
import logging
from typing import List, Dict, Any, Optional, Tuple

from src.contracts.v1 import MarketObservation, MarketDataSnapshot
from src.data.storage.blob_repo import BlobPathBuilder, BlobStorageRepository
from src.data.ingestion.adapters import BaseSourceAdapter, DataGovInAdapter
from src.data.ingestion.normalizer import MarketRecordNormalizer
from src.data.snapshots.publisher import SnapshotPublisher

logger = logging.getLogger("IngestionRunner")


class IngestionRunner:
    """
    Independent market data ingestion runner designed for execution as an Azure Container Apps Job.
    Coordinates:
      1. Fetching raw payloads from source adapters (with retry & pagination).
      2. Writing immutable raw responses to `market/raw/{source}/{YYYY}/{MM}/{DD}/{batch_id}.json`.
      3. Normalizing observations, capturing invalid/corrupted records into `market/quarantine/{batch_id}.json`.
      4. Deduplicating records using composite fingerprints.
      5. Saving curated monthly records to `market/curated/{commodity}/{state}/{district}/{YYYY}/{MM}.json`.
      6. Publishing rolling snapshots to `market/snapshots/{commodity}/{variety}/{district}/latest.json`.
    """

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        adapter: Optional[BaseSourceAdapter] = None
    ):
        self.repository = repository or BlobStorageRepository()
        self.adapter = adapter or DataGovInAdapter()

    def run_ingestion(
        self,
        commodity: str = "Turmeric",
        state: str = "Tamil Nadu",
        district: str = "Erode",
        varieties: Optional[List[str]] = None,
        source_name: str = "DATA_GOV_IN",
        raw_records: Optional[List[Dict[str, Any]]] = None,
        reference_time: Optional[datetime.datetime] = None
    ) -> Dict[str, Any]:
        """
        Executes an end-to-end ingestion cycle.
        If `raw_records` is provided, skips external adapter network fetch (ideal for deterministic job triggers/testing).
        """
        now = reference_time or datetime.datetime.now(datetime.timezone.utc)
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        target_varieties = varieties or ["Finger", "Bulb"]

        logger.info(f"Starting ingestion cycle [{batch_id}] for {commodity} in {district}, {state}...")

        # 1. Fetch raw data
        if raw_records is None:
            try:
                records = self.adapter.fetch_observations(
                    commodity=commodity,
                    state=state,
                    district=district
                )
            except Exception as e:
                logger.error(f"Ingestion adapter failed: {e}")
                records = []
        else:
            records = raw_records

        raw_count = len(records)
        logger.info(f"Received {raw_count} raw records.")

        # 2. Save immutable raw response payload
        raw_path = BlobPathBuilder.raw_path(source=source_name, dt=now, batch_id=batch_id)
        raw_payload = {
            "batch_id": batch_id,
            "source": source_name,
            "commodity": commodity,
            "state": state,
            "district": district,
            "fetched_at": now.isoformat(),
            "record_count": raw_count,
            "records": records
        }
        self.repository.save_json(raw_path, raw_payload)
        logger.info(f"Saved immutable raw payload to '{raw_path}'.")

        # 3. Normalize, Validate, Anomaly Quarantine, and Deduplicate
        valid_observations: List[Tuple[str, MarketObservation]] = []  # (variety, observation)
        quarantined_records: List[Dict[str, Any]] = []
        seen_fingerprints = set()
        dedup_count = 0

        for raw_rec in records:
            # Check composite fingerprint for deduplication
            try:
                fp = MarketRecordNormalizer.generate_fingerprint(raw_rec, source=source_name)
                if fp in seen_fingerprints:
                    dedup_count += 1
                    continue
                seen_fingerprints.add(fp)
            except Exception as e:
                quarantined_records.append({
                    "record": raw_rec,
                    "reason": f"Fingerprint generation failed: {e}"
                })
                continue

            # Normalize variety
            raw_var = str(raw_rec.get("variety") or raw_rec.get("Variety") or "Finger")
            normalized_variety = MarketRecordNormalizer.normalize_variety(raw_var) or "Finger"

            # Normalize observation
            obs, error = MarketRecordNormalizer.normalize_record(raw_rec, source=source_name)
            if error or obs is None:
                quarantined_records.append({
                    "record": raw_rec,
                    "reason": error or "Unknown normalization failure"
                })
            else:
                valid_observations.append((normalized_variety, obs))

        # Save quarantined records if any anomalies found
        quarantine_path = None
        if quarantined_records:
            quarantine_path = BlobPathBuilder.quarantine_path(batch_id=batch_id)
            self.repository.save_json(quarantine_path, {
                "batch_id": batch_id,
                "quarantined_at": now.isoformat(),
                "commodity": commodity,
                "state": state,
                "district": district,
                "quarantined_count": len(quarantined_records),
                "items": quarantined_records
            })
            logger.warning(f"Quarantined {len(quarantined_records)} anomalous records to '{quarantine_path}'.")

        # 4. Save Curated Monthly Records
        # Group observations by Year-Month
        monthly_groups: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
        for variety, obs in valid_observations:
            obs_dt = datetime.date.fromisoformat(obs.date)
            ym = (obs_dt.year, obs_dt.month)
            if ym not in monthly_groups:
                monthly_groups[ym] = []
            obs_dict = obs.model_dump()
            obs_dict["variety"] = variety
            monthly_groups[ym].append(obs_dict)

        for (year, month), obs_list in monthly_groups.items():
            curated_path = BlobPathBuilder.curated_path(
                commodity=commodity,
                state=state,
                district=district,
                year=year,
                month=month
            )
            existing = self.repository.load_json(curated_path) or []
            if isinstance(existing, dict) and "observations" in existing:
                existing_obs = existing["observations"]
            elif isinstance(existing, list):
                existing_obs = existing
            else:
                existing_obs = []

            # Merge and deduplicate with existing curated records
            curated_merged = {
                f"{o.get('source')}:{o.get('date')}:{o.get('market')}:{o.get('variety')}:{o.get('modal_price')}": o
                for o in (existing_obs + obs_list)
            }
            self.repository.save_json(curated_path, list(curated_merged.values()))

        # 5. Build and Publish Snapshots for each target variety
        published_snapshots: Dict[str, MarketDataSnapshot] = {}
        for target_var in target_varieties:
            variety_obs = [
                obs for (var, obs) in valid_observations
                if var.lower() == target_var.lower()
            ]

            snapshot = SnapshotPublisher.build_snapshot(
                commodity=commodity,
                variety=target_var,
                district=district,
                observations=variety_obs,
                reference_time=now
            )
            SnapshotPublisher.publish(
                snapshot=snapshot,
                repository=self.repository,
                batch_id=batch_id
            )
            published_snapshots[target_var] = snapshot

        return {
            "batch_id": batch_id,
            "raw_count": raw_count,
            "valid_count": len(valid_observations),
            "deduplicated_count": dedup_count,
            "quarantined_count": len(quarantined_records),
            "raw_path": raw_path,
            "quarantine_path": quarantine_path,
            "published_varieties": list(published_snapshots.keys()),
            "snapshots": published_snapshots
        }
