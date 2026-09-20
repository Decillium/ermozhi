import pytest
import asyncio
from unittest.mock import MagicMock, patch
from src.contracts.v1 import (
    ActionType,
    DecisionAction,
    DecisionOutput,
    DecisionExplanation,
    ReasonCode,
    Money,
    FallbackStatus,
    LanguageInput,
    LanguageOutput
)
from src.language.templates import LanguageTemplateEngine
from src.language.tts import TTSAdapter
from src.language.engine import LanguageEngine
from src.data.storage.blob_repo import BlobStorageRepository


@pytest.fixture
def repo():
    return BlobStorageRepository(use_memory_store=True)


@pytest.fixture
def sample_decision():
    return DecisionOutput(
        decision_id="dec_test_001",
        action=ActionType.SELL,
        offer=Money(value=14500.0, unit="quintal"),
        reference=Money(value=14200.0, unit="quintal"),
        offer_ratio=1.021,
        difference_percent=2.11,
        score={"offer_score": 95.0, "decision_score": 94.5},
        confidence={"value": 0.92, "band": "HIGH"},
        risk={"level": "LOW"},
        explanation=DecisionExplanation(
            action=ActionType.SELL,
            headline_code="OFFER_AT_OR_ABOVE_REFERENCE",
            reason_codes=[ReasonCode.OFFER_AT_OR_ABOVE_REFERENCE],
            facts={"crop": "Turmeric", "variety": "Finger", "district": "Erode"}
        ),
        evidence={"observed_at": "2026-09-20", "source": "AGMARKNET"},
        policy_version="1.0.0",
        engine_version="1.0.0",
        created_at="2026-09-20T12:00:00Z"
    )


class TestLanguageAndTTS:
    """Test suite for rural-first localization, fact binding, and resilient voice synthesis."""

    def test_decision_template_fact_binding_tamil(self, sample_decision):
        text, disclosure, tpl_id = LanguageTemplateEngine.render_decision_response(sample_decision, locale="ta-IN")
        assert "₹14,500" in text
        assert "₹14,200" in text
        assert "விற்பனை செய்வது நல்லது" in text
        assert "Erode" in disclosure or "ஒழுங்குமுறை விற்பனைக்கூடம்" in disclosure
        assert "2026-09-20" in disclosure
        assert tpl_id == "tpl_sell_v1"

    def test_decision_template_fact_binding_negotiate(self, sample_decision):
        sample_decision.action = ActionType.NEGOTIATE
        sample_decision.offer = Money(value=12000.0, unit="quintal")
        sample_decision.reference = Money(value=14200.0, unit="quintal")
        text, disclosure, tpl_id = LanguageTemplateEngine.render_decision_response(sample_decision, locale="ta-IN")
        assert "₹12,000" in text
        assert "பேசிப்பார்க்க" in text
        assert tpl_id == "tpl_negotiate_v1"

    def test_decision_template_fact_binding_hold(self, sample_decision):
        sample_decision.action = ActionType.HOLD
        sample_decision.offer = Money(value=10000.0, unit="quintal")
        sample_decision.reference = Money(value=14200.0, unit="quintal")
        text, disclosure, tpl_id = LanguageTemplateEngine.render_decision_response(sample_decision, locale="ta-IN")
        assert "₹10,000" in text
        assert "பொறுத்திருந்து" in text or "இருப்பு" in text
        assert tpl_id == "tpl_hold_v1"

    def test_decision_template_fact_binding_wait(self, sample_decision):
        sample_decision.action = DecisionAction.WAIT
        text, disclosure, tpl_id = LanguageTemplateEngine.render_decision_response(sample_decision, locale="ta-IN")
        assert "போதிய சமீபத்திய விலை விவரங்கள் பதிவாகவில்லை" in text
        assert tpl_id == "tpl_wait_v1"

    def test_clarification_template_targeted_questions(self):
        # Missing variety
        text_var, _, _ = LanguageTemplateEngine.render_clarification_response(["variety"], locale="ta-IN")
        assert "விரலி" in text_var and "கிழங்கு" in text_var

        # Missing price
        text_price, _, _ = LanguageTemplateEngine.render_clarification_response(["offered_price"], locale="ta-IN")
        assert "விலை" in text_price

        # Missing both
        text_both, _, _ = LanguageTemplateEngine.render_clarification_response(["variety", "offered_price"], locale="ta-IN")
        assert "வகை" in text_both and "விலை" in text_both

    def test_tts_graceful_degradation_when_disabled(self, repo):
        tts = TTSAdapter(repository=repo, enable_tts=False)
        sas_url, duration, fallback = asyncio.run(tts.synthesize_to_storage("டெஸ்ட் உரை", "resp_001"))
        assert sas_url is None
        assert duration is None
        assert fallback == FallbackStatus.TEXT_ONLY

    def test_language_engine_text_only_mode(self, repo, sample_decision):
        engine = LanguageEngine(repository=repo)
        lang_input = LanguageInput(
            message_id="msg_001",
            kind="text",
            locale_hint="ta-IN"
        )
        output: LanguageOutput = asyncio.run(engine.render_decision(sample_decision, lang_input))
        assert output.message_id == "msg_001"
        assert output.media_ref is None
        assert output.fallback_status == FallbackStatus.NONE
        assert "₹14,500" in output.text_content
