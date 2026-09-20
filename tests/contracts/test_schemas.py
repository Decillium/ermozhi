import pytest
from pydantic import ValidationError

from src.contracts.v1 import (
    # Events
    ProcessingStatus,
    InboundInput,
    CanonicalInboundMessage,
    EventEnvelope,
    # Intelligence
    ExtractionIntent,
    IntelligenceInput,
    IntelligenceOutput,
    # Market
    DataFreshnessState,
    MarketObservation,
    MarketAggregates,
    MarketDataSnapshot,
    # Decision
    ActionType,
    RiskLevel,
    ConfidenceBand,
    ReasonCode,
    Money,
    Quantity,
    DecisionExplanation,
    DecisionInput,
    DecisionOutput,
    ConfidenceStr,
    # Language
    FallbackStatus,
    LanguageInput,
    LanguageOutput,
)


class TestEventSchemas:
    """Tests for CanonicalInboundMessage, InboundInput, and EventEnvelope."""

    def test_canonical_inbound_message_valid(self):
        msg = CanonicalInboundMessage(
            message_id="msg_123",
            channel="whatsapp",
            provider="meta",
            provider_message_id="wamid.HBgLMTIzNDU2Nzg5MA==",
            participant_ref="part_456",
            conversation_ref="conv_789",
            input=InboundInput(
                kind="audio",
                media_ref="https://lookaside.fbsbx.com/media/test.ogg",
                media_content_type="audio/ogg",
                media_duration_seconds=12.5,
            ),
            received_at="2026-09-20T12:00:00Z",
            locale_hint="ta-IN",
            correlation_id="corr_999",
        )
        assert msg.message_id == "msg_123"
        assert msg.input.kind == "audio"
        assert msg.input.media_duration_seconds == 12.5
        data = msg.model_dump()
        assert data["channel"] == "whatsapp"

    def test_canonical_inbound_message_missing_fields(self):
        with pytest.raises(ValidationError):
            CanonicalInboundMessage(
                message_id="msg_123",
                # missing provider, provider_message_id, participant_ref, etc.
            )

    def test_event_envelope_defaults_and_serialization(self):
        env = EventEnvelope(
            event_id="evt_001",
            event_type="InboundMessageAccepted",
            message_id="msg_123",
            conversation_id="conv_789",
            correlation_id="corr_999",
            occurred_at="2026-09-20T12:00:00Z",
            payload={"status": ProcessingStatus.ACCEPTED.value},
        )
        assert env.attempt == 1
        assert env.schema_version == "1.0.0"
        json_str = env.model_dump_json()
        assert "InboundMessageAccepted" in json_str


class TestIntelligenceSchemas:
    """Tests for IntelligenceInput and IntelligenceOutput."""

    def test_intelligence_output_valid(self):
        out = IntelligenceOutput(
            crop="Turmeric",
            variety="Finger",
            offered_price=15500.0,
            unit="quintal",
            quantity=10.0,
            location="Erode",
            confidence=0.95,
            intent=ExtractionIntent.PRICE_EVALUATION,
        )
        assert out.crop == "Turmeric"
        assert out.variety == "Finger"
        assert out.offered_price == 15500.0
        assert out.intent == ExtractionIntent.PRICE_EVALUATION
        assert len(out.missing_fields) == 0

    def test_intelligence_output_negative_price_rejected(self):
        with pytest.raises(ValidationError, match="strictly positive"):
            IntelligenceOutput(
                crop="Turmeric",
                variety="Finger",
                offered_price=-500.0,
                confidence=0.90,
            )

    def test_intelligence_output_zero_price_rejected(self):
        with pytest.raises(ValidationError, match="strictly positive"):
            IntelligenceOutput(
                crop="Turmeric",
                variety="Finger",
                offered_price=0.0,
                confidence=0.90,
            )

    def test_intelligence_output_invalid_unit_rejected(self):
        with pytest.raises(ValidationError, match="Unsupported unit"):
            IntelligenceOutput(
                crop="Turmeric",
                variety="Finger",
                offered_price=15000.0,
                unit="liters",
                confidence=0.90,
            )

    def test_intelligence_output_confidence_out_of_bounds(self):
        with pytest.raises(ValidationError):
            IntelligenceOutput(
                crop="Turmeric",
                variety="Finger",
                offered_price=15000.0,
                confidence=1.5,  # must be <= 1.0
            )

    def test_intelligence_output_fail_closed_missing_variety(self):
        """Missing variety for PRICE_EVALUATION triggers CLARIFICATION_NEEDED."""
        out = IntelligenceOutput(
            crop="Turmeric",
            variety=None,  # Missing variety!
            offered_price=15000.0,
            confidence=0.90,
            intent=ExtractionIntent.PRICE_EVALUATION,
        )
        assert out.intent == ExtractionIntent.CLARIFICATION_NEEDED
        assert "variety" in out.missing_fields

    def test_intelligence_output_fail_closed_missing_price(self):
        """Missing price for PRICE_EVALUATION triggers CLARIFICATION_NEEDED."""
        out = IntelligenceOutput(
            crop="Turmeric",
            variety="Finger",
            offered_price=None,  # Missing price!
            confidence=0.90,
            intent=ExtractionIntent.PRICE_EVALUATION,
        )
        assert out.intent == ExtractionIntent.CLARIFICATION_NEEDED
        assert "offered_price" in out.missing_fields


class TestMarketSchemas:
    """Tests for MarketObservation and MarketDataSnapshot."""

    def test_market_observation_valid(self):
        obs = MarketObservation(
            date="2026-09-18",
            modal_price=15800.0,
            min_price=15600.0,
            max_price=16000.0,
            market="Erode",
            source="AGMARKNET",
        )
        assert obs.date == "2026-09-18"
        assert obs.modal_price == 15800.0

    def test_market_observation_invalid_date(self):
        with pytest.raises(ValidationError, match="YYYY-MM-DD"):
            MarketObservation(
                date="18-09-2026",  # Invalid format
                modal_price=15800.0,
            )

    def test_market_observation_negative_price(self):
        with pytest.raises(ValidationError):
            MarketObservation(
                date="2026-09-18",
                modal_price=-100.0,
            )

    def test_market_snapshot_valid(self):
        obs = MarketObservation(
            date="2026-09-18",
            modal_price=16000.0,
            market="Erode",
        )
        snap = MarketDataSnapshot(
            snapshot_id="snap_001",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            observations=[obs],
            aggregates=MarketAggregates(
                median=16000.0,
                mean=16000.0,
                min=15800.0,
                max=16200.0,
                volatility=2.1,
            ),
            observation_count=1,
            distinct_date_count=1,
            observed_at="2026-09-18",
            retrieved_at="2026-09-20T12:00:00Z",
            freshness_status=DataFreshnessState.FRESH,
        )
        assert snap.snapshot_id == "snap_001"
        assert snap.freshness_status == DataFreshnessState.FRESH


class TestDecisionSchemas:
    """Tests for Money, Quantity, DecisionInput, and DecisionOutput."""

    def test_money_valid(self):
        m = Money(value=15000.0, currency="INR", unit="quintal")
        assert m.value == 15000.0
        assert m.unit == "quintal"

    def test_money_negative_or_zero_rejected(self):
        with pytest.raises(ValidationError, match="strictly positive"):
            Money(value=-10.0)

        with pytest.raises(ValidationError, match="strictly positive"):
            Money(value=0.0)

    def test_money_invalid_unit_rejected(self):
        with pytest.raises(ValidationError, match="Unsupported unit"):
            Money(value=100.0, unit="barrels")

    def test_decision_output_backward_compatibility(self):
        """Verify DecisionOutput computes legacy fields seamlessly."""
        output = DecisionOutput(
            decision_id="dec_test_001",
            action=ActionType.SELL,
            offer=Money(value=16200.0),
            reference=Money(value=16000.0),
            offer_ratio=1.0125,
            difference_percent=1.3,
            explanation=DecisionExplanation(
                action=ActionType.SELL,
                headline_code="OFFER_AT_OR_ABOVE_REFERENCE",
                reason_codes=[ReasonCode.OFFER_AT_OR_ABOVE_REFERENCE],
            ),
            policy_version="1.0.0",
            engine_version="1.0.0",
            created_at="2026-09-20T12:00:00Z",
        )
        # Legacy fields must be automatically populated
        assert output.decision == "Fair Price"
        assert output.offer_price == 16200.0
        assert output.reference_price == 16000.0
        assert output.difference_pct == 1.3
        assert "above recent market reference" in output.reason

    def test_confidence_str_dual_compatibility(self):
        c = ConfidenceStr("85%", value=85.0, band="HIGH", caps_applied=["CAP_1"])
        assert c == "85%"
        assert c.endswith("%")
        assert c["value"] == 85.0
        assert c["band"] == "HIGH"
        assert c["caps_applied"] == ["CAP_1"]
        assert c.get("value") == 85.0


class TestLanguageSchemas:
    """Tests for LanguageInput and LanguageOutput."""

    def test_language_output_valid(self):
        lang_out = LanguageOutput(
            message_id="msg_123",
            locale="ta-IN",
            text_content="உங்கள் விலை ₹16,000 சந்தை விலைக்கு ஏற்ப நியாயமானது.",
            media_ref="https://storage.blob.core.windows.net/media/outbound/audio_123.mp3",
            media_duration_seconds=8.2,
            fallback_status=FallbackStatus.NONE,
            template_id="tpl_sell_001",
        )
        assert lang_out.message_id == "msg_123"
        assert lang_out.fallback_status == FallbackStatus.NONE
        assert lang_out.media_duration_seconds == 8.2

    def test_language_output_negative_duration_rejected(self):
        with pytest.raises(ValidationError):
            LanguageOutput(
                message_id="msg_123",
                text_content="Sample text",
                media_duration_seconds=-2.0,
            )
