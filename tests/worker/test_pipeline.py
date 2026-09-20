import pytest
import asyncio
from unittest.mock import patch, MagicMock

from src.worker.pipeline import WorkerPipeline
from src.data.storage.blob_repo import BlobStorageRepository
from src.data.snapshots.publisher import SnapshotPublisher
from src.data.reader import MarketSnapshotReader
from src.contracts.v1 import (
    MarketObservation,
    DecisionAction,
    ExtractionIntent,
    IntelligenceOutput
)


@pytest.fixture
def repo_with_snapshot():
    repo = BlobStorageRepository(use_memory_store=True)
    # Seed fresh 7-day snapshot for Turmeric Finger in Erode
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


class TestWorkerPipeline:
    """Test suite for full end-to-end worker orchestration pipeline."""

    def test_end_to_end_complete_text_query_sell(self, repo_with_snapshot):
        pipeline = WorkerPipeline(repository=repo_with_snapshot)

        work_item = {
            "message_id": "msg_pipe_001",
            "channel": "whatsapp",
            "locale_hint": "ta-IN",
            "correlation_id": "corr_001",
            "input": {
                "kind": "text",
                "text": "ஈரோடு சந்தையில் விரலி மஞ்சள் ₹14,500 விலை தருகிறார்கள்"
            }
        }

        result = asyncio.run(pipeline.process_work_item(work_item))

        assert result["status"] == "SUCCESS"
        assert result["message_id"] == "msg_pipe_001"
        assert result["extraction"]["variety"] == "Finger"
        assert result["extraction"]["offered_price"] == 14500.0
        assert result["decision"]["action"] == DecisionAction.SELL.value
        assert "₹14,500" in result["delivery_payload"]["text_content"]
        assert "விற்பனை செய்வது நல்லது" in result["delivery_payload"]["text_content"]

    def test_end_to_end_clarification_branch_skips_decision_engine(self, repo_with_snapshot):
        pipeline = WorkerPipeline(repository=repo_with_snapshot)

        # Incomplete query missing variety
        work_item = {
            "message_id": "msg_pipe_002",
            "channel": "whatsapp",
            "locale_hint": "ta-IN",
            "correlation_id": "corr_002",
            "input": {
                "kind": "text",
                "text": "வியாபாரி ₹14,000 விலை தருகிறார்"
            }
        }

        result = asyncio.run(pipeline.process_work_item(work_item))

        assert result["status"] == "CLARIFICATION_NEEDED"
        assert result["decision"] is None
        assert "variety" in result["extraction"]["missing_fields"]
        assert "விரலி" in result["delivery_payload"]["text_content"]
        assert "கிழங்கு" in result["delivery_payload"]["text_content"]

    def test_end_to_end_voice_query_with_audio(self, repo_with_snapshot):
        pipeline = WorkerPipeline(repository=repo_with_snapshot)

        # Save dummy audio bytes to media/inbound/
        repo_with_snapshot.save_bytes("media/inbound/2026/09/20/msg_audio_003.ogg", b"dummy_audio_bytes")

        work_item = {
            "message_id": "msg_audio_003",
            "channel": "whatsapp",
            "locale_hint": "ta-IN",
            "correlation_id": "corr_003",
            "input": {
                "kind": "audio",
                "media_ref": "media/inbound/2026/09/20/msg_audio_003.ogg",
                "media_content_type": "audio/ogg"
            }
        }

        # Mock intelligence extraction for audio
        mock_extraction = IntelligenceOutput(
            crop="Turmeric",
            variety="Finger",
            offered_price=14500.0,
            unit="quintal",
            location="Erode",
            confidence=0.92,
            intent=ExtractionIntent.PRICE_EVALUATION
        )

        with patch.object(pipeline.intelligence, "process_input", return_value=mock_extraction):
            result = asyncio.run(pipeline.process_work_item(work_item))

            assert result["status"] == "SUCCESS"
            assert result["decision"]["action"] == DecisionAction.SELL.value
            assert result["delivery_payload"]["text_content"] is not None
