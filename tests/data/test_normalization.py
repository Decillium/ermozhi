import os
import json
import pytest
import datetime
from src.data.ingestion.normalizer import MarketRecordNormalizer, RecordNormalizationError
from src.data.ingestion.runner import IngestionRunner
from src.data.storage.blob_repo import BlobStorageRepository


class TestMarketRecordNormalization:
    """Test suite for variety synonym mapping, date parsing, price validation, and anomaly quarantine."""

    @pytest.mark.parametrize("input_variety,expected_canonical", [
        ("finger", "Finger"),
        ("Finger", "Finger"),
        ("virali", "Finger"),
        ("VIRALI", "Finger"),
        ("விரலி", "Finger"),
        ("விரலி மஞ்சள்", "Finger"),
        ("salem", "Finger"),
        ("erode local", "Finger"),
        ("local", "Finger"),
        ("1st sort", "Finger"),
        ("bulb", "Bulb"),
        ("Bulb", "Bulb"),
        ("gatta", "Bulb"),
        ("kizhangu", "Bulb"),
        ("கிழங்கு", "Bulb"),
        ("கிழங்கு மஞ்சள்", "Bulb"),
        ("round", "Bulb"),
        ("2nd sort", "Bulb"),
    ])
    def test_variety_normalization_known_aliases(self, input_variety, expected_canonical):
        result = MarketRecordNormalizer.normalize_variety(input_variety)
        assert result == expected_canonical

    def test_variety_normalization_unknown_preserves_title(self):
        assert MarketRecordNormalizer.normalize_variety("rajapore") == "Rajapore"
        assert MarketRecordNormalizer.normalize_variety("pratibha") == "Pratibha"
        assert MarketRecordNormalizer.normalize_variety(None) is None

    @pytest.mark.parametrize("raw_date,expected_iso", [
        ("2026-09-20", "2026-09-20"),
        ("20/09/2026", "2026-09-20"),
        ("20-09-2026", "2026-09-20"),
        ("2026/09/20", "2026-09-20"),
        ("5/9/2026", "2026-09-05"),
        ("5-9-2026", "2026-09-05"),
    ])
    def test_date_parsing_valid_formats(self, raw_date, expected_iso):
        parsed = MarketRecordNormalizer.parse_arrival_date(raw_date)
        assert parsed == expected_iso

    @pytest.mark.parametrize("invalid_date", [
        "",
        None,
        "not_a_date",
        "2026-02-31",  # Invalid calendar date
        "2026-13-01",  # Invalid month
        "32/01/2026",  # Invalid day
    ])
    def test_date_parsing_invalid_raises_error(self, invalid_date):
        with pytest.raises(RecordNormalizationError):
            MarketRecordNormalizer.parse_arrival_date(invalid_date)

    def test_normalize_valid_record(self):
        raw = {
            "State": "Tamil Nadu",
            "District": "Erode",
            "Market": "Perundurai",
            "Commodity": "Turmeric",
            "Variety": "Virali",
            "Grade": "FAQ",
            "Arrival_Date": "20/09/2026",
            "Min_Price": "13600",
            "Max_Price": "14400",
            "Modal_Price": "14100"
        }
        obs, error = MarketRecordNormalizer.normalize_record(raw, source="DATA_GOV_IN")
        assert error is None
        assert obs is not None
        assert obs.date == "2026-09-20"
        assert obs.modal_price == 14100.0
        assert obs.min_price == 13600.0
        assert obs.max_price == 14400.0
        assert obs.market == "Perundurai"
        assert obs.source == "DATA_GOV_IN"

    def test_normalize_invalid_price_records(self):
        # Negative price
        raw_neg = {"Modal_Price": "-100", "Arrival_Date": "2026-09-20"}
        obs, err = MarketRecordNormalizer.normalize_record(raw_neg)
        assert obs is None
        assert "Non-positive" in err

        # String non-numeric price
        raw_str = {"Modal_Price": "free", "Arrival_Date": "2026-09-20"}
        obs, err = MarketRecordNormalizer.normalize_record(raw_str)
        assert obs is None
        assert "Non-numeric" in err

        # Missing price
        raw_missing = {"Arrival_Date": "2026-09-20"}
        obs, err = MarketRecordNormalizer.normalize_record(raw_missing)
        assert obs is None
        assert "Missing modal price" in err

    def test_composite_fingerprint_deduplication(self):
        rec1 = {
            "State": "Tamil Nadu",
            "District": "Erode",
            "Market": "Erode",
            "Commodity": "Turmeric",
            "Variety": "Finger",
            "Grade": "FAQ",
            "Arrival_Date": "2026-09-20",
            "Modal_Price": "14200"
        }
        # Duplicate with different casing and Tamil synonym
        rec2 = {
            "State": "tamil nadu",
            "District": "ERODE",
            "Market": "erode",
            "Commodity": "turmeric",
            "Variety": "virali",
            "Grade": "faq",
            "Arrival_Date": "20/09/2026",
            "Modal_Price": "14200"
        }
        fp1 = MarketRecordNormalizer.generate_fingerprint(rec1, source="AGMARKNET")
        fp2 = MarketRecordNormalizer.generate_fingerprint(rec2, source="AGMARKNET")
        assert fp1 == fp2

    def test_ingestion_runner_deduplication_and_anomaly_quarantine(self):
        repo = BlobStorageRepository(use_memory_store=True)
        runner = IngestionRunner(repository=repo)

        # Batch with 2 valid records, 1 duplicate, and 2 corrupt/anomalous records
        records = [
            # Valid 1
            {
                "State": "Tamil Nadu",
                "District": "Erode",
                "Market": "Erode",
                "Commodity": "Turmeric",
                "Variety": "Finger",
                "Grade": "FAQ",
                "Arrival_Date": "2026-09-20",
                "Modal_Price": "14200"
            },
            # Valid 2
            {
                "State": "Tamil Nadu",
                "District": "Erode",
                "Market": "Perundurai",
                "Commodity": "Turmeric",
                "Variety": "Finger",
                "Grade": "FAQ",
                "Arrival_Date": "2026-09-19",
                "Modal_Price": "14100"
            },
            # Duplicate of Valid 1
            {
                "State": "Tamil Nadu",
                "District": "Erode",
                "Market": "Erode",
                "Commodity": "Turmeric",
                "Variety": "Finger",
                "Grade": "FAQ",
                "Arrival_Date": "2026-09-20",
                "Modal_Price": "14200"
            },
            # Anomaly 1: Invalid price
            {
                "State": "Tamil Nadu",
                "District": "Erode",
                "Market": "Gobichettipalayam",
                "Commodity": "Turmeric",
                "Variety": "Finger",
                "Grade": "FAQ",
                "Arrival_Date": "2026-09-18",
                "Modal_Price": "-500"
            },
            # Anomaly 2: Corrupted Date
            {
                "State": "Tamil Nadu",
                "District": "Erode",
                "Market": "Gobichettipalayam",
                "Commodity": "Turmeric",
                "Variety": "Finger",
                "Grade": "FAQ",
                "Arrival_Date": "corrupt_date",
                "Modal_Price": "13900"
            }
        ]

        summary = runner.run_ingestion(
            commodity="Turmeric",
            state="Tamil Nadu",
            district="Erode",
            raw_records=records,
            reference_time=datetime.datetime(2026, 9, 20, 10, 0, 0, tzinfo=datetime.timezone.utc)
        )

        assert summary["raw_count"] == 5
        assert summary["valid_count"] == 2
        assert summary["deduplicated_count"] == 1
        assert summary["quarantined_count"] == 2
        assert summary["quarantine_path"] is not None

        # Verify quarantine payload in storage
        quarantine_data = repo.load_json(summary["quarantine_path"])
        assert quarantine_data is not None
        assert quarantine_data["quarantined_count"] == 2
        assert len(quarantine_data["items"]) == 2
