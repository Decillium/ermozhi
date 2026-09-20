import pytest
from unittest.mock import MagicMock, patch
from src.intelligence.validator import DeterministicValidator
from src.intelligence.adapter import GeminiIntelligenceAdapter
from src.contracts.v1 import ExtractionIntent, IntelligenceInput
from src.data.storage.blob_repo import BlobStorageRepository, BlobPathBuilder


@pytest.fixture
def repo():
    return BlobStorageRepository(use_memory_store=True)


@pytest.fixture
def adapter(repo):
    return GeminiIntelligenceAdapter(repository=repo)


class TestIntelligenceAdapterAndValidation:
    """Test suite for multimodal intelligence adapter, dialect normalization, and clarification logic."""

    @pytest.mark.parametrize("raw_variety,expected_canonical", [
        ("விரலி", "Finger"),
        ("விரலி மஞ்சள்", "Finger"),
        ("நாட்டு", "Finger"),
        ("நாட்டு மஞ்சள்", "Finger"),
        ("nattu", "Finger"),
        ("virali", "Finger"),
        ("salem", "Finger"),
        ("Finger", "Finger"),
        ("கிழங்கு", "Bulb"),
        ("கிழங்கு மஞ்சள்", "Bulb"),
        ("முட்டை", "Bulb"),
        ("kizhangu", "Bulb"),
        ("gatta", "Bulb"),
        ("Bulb", "Bulb"),
    ])
    def test_variety_dialect_normalization(self, raw_variety, expected_canonical):
        res = DeterministicValidator.normalize_variety(raw_variety)
        assert res == expected_canonical

    def test_structured_json_parsing_complete(self):
        raw = {
            "crop": "Turmeric",
            "variety": "விரலி",
            "offered_price": "₹14,500",
            "unit": "quintal",
            "quantity": 25,
            "location": "Erode",
            "intent": "PRICE_EVALUATION",
            "confidence": 0.95
        }
        output = DeterministicValidator.validate(raw)
        assert output.crop == "Turmeric"
        assert output.variety == "Finger"
        assert output.offered_price == 14500.0
        assert output.quantity == 25.0
        assert output.unit == "quintal"
        assert output.intent == ExtractionIntent.PRICE_EVALUATION
        assert output.missing_fields == []
        assert output.confidence == 0.95

    def test_missing_variety_triggers_clarification(self):
        raw = {
            "crop": "Turmeric",
            "offered_price": 14000.0,
            "location": "Erode",
            "intent": "PRICE_EVALUATION"
        }
        output = DeterministicValidator.validate(raw)
        assert output.intent == ExtractionIntent.CLARIFICATION_NEEDED
        assert "variety" in output.missing_fields
        assert output.offered_price == 14000.0

    def test_missing_price_triggers_clarification(self):
        raw = {
            "crop": "Turmeric",
            "variety": "Virali",
            "location": "Erode",
            "intent": "PRICE_EVALUATION"
        }
        output = DeterministicValidator.validate(raw)
        assert output.intent == ExtractionIntent.CLARIFICATION_NEEDED
        assert "offered_price" in output.missing_fields
        assert output.variety == "Finger"

    def test_heuristic_extraction_fallback(self, adapter):
        # Heuristic extraction when external GenAI client is unconfigured
        text = "வியாபாரி நாட்டு மஞ்சள் ₹14800 விலை கேட்கிறார் ஈரோடு"
        output = adapter.extract_from_text(text)
        assert output.variety == "Finger"
        assert output.offered_price == 14800.0
        assert output.intent == ExtractionIntent.PRICE_EVALUATION

    def test_inbound_media_streaming_to_storage(self, repo, adapter):
        # Mock requests.get to return simulated OGG audio bytes
        mock_audio_bytes = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00test_opus_stream"
        
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = mock_audio_bytes
            mock_get.return_value = mock_resp

            blob_path, stored_bytes = adapter.fetch_and_store_media(
                media_url="https://lookaside.fbsbx.com/mock_audio.ogg",
                message_id="msg_audio_001",
                content_type="audio/ogg"
            )

            assert "media/inbound/" in blob_path
            assert "msg_audio_001.ogg" in blob_path
            assert stored_bytes == mock_audio_bytes
            assert repo.exists(blob_path)
            assert repo.load_bytes(blob_path) == mock_audio_bytes
