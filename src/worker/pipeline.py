import logging
from typing import Dict, Any, Optional, Tuple

from src.contracts.v1 import (
    IntelligenceInput,
    IntelligenceOutput,
    ExtractionIntent,
    DecisionInput,
    DecisionOutput,
    LanguageInput,
    LanguageOutput,
    MarketDataSnapshot,
    Money
)
from src.intelligence.adapter import GeminiIntelligenceAdapter
from src.decision_engine.engine import DecisionEngine
from src.data.reader import MarketSnapshotReader
from src.language.engine import LanguageEngine
from src.channels.meta.client import MetaWhatsAppClient
from src.data.storage.blob_repo import BlobStorageRepository

logger = logging.getLogger("WorkerPipeline")


class WorkerPipeline:
    """
    End-to-end asynchronous processing pipeline executed by private worker replicas:
    1. Multimodal Entity Extraction (Gemini Intelligence Adapter)
    2. Deterministic Post-Validation & Clarification Branch
    3. Low-latency Market Snapshot Lookup (< 50ms)
    4. Pure Decision Engine Evaluation
    5. Localized Tamil/English Language & Voice Synthesis (Language Engine)
    6. Proactive Outbound Channel Dispatch (Meta WhatsApp Cloud API)
    """

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        intelligence_adapter: Optional[GeminiIntelligenceAdapter] = None,
        snapshot_reader: Optional[MarketSnapshotReader] = None,
        language_engine: Optional[LanguageEngine] = None,
        meta_client: Optional[MetaWhatsAppClient] = None
    ):
        self.repository = repository or BlobStorageRepository()
        self.intelligence = intelligence_adapter or GeminiIntelligenceAdapter(repository=self.repository)
        self.snapshot_reader = snapshot_reader or MarketSnapshotReader(repository=self.repository)
        self.language = language_engine or LanguageEngine(repository=self.repository)
        self.meta_client = meta_client or MetaWhatsAppClient()

    async def _dispatch_outbound(
        self,
        work_item: Dict[str, Any],
        lang_output: LanguageOutput,
        correlation_id: str
    ) -> Dict[str, Any]:
        """
        Dispatches localized recommendation/clarification via Meta WhatsApp Cloud API.
        """
        participant_ref = work_item.get("participant_ref") or work_item.get("input", {}).get("from", "+919876543210")
        enqueued_at = work_item.get("enqueued_at") or work_item.get("received_at")

        return await self.meta_client.send_message(
            to_phone=participant_ref,
            text=lang_output.text_content,
            media_url=lang_output.media_ref,
            inbound_timestamp=enqueued_at,
            correlation_id=correlation_id
        )

    async def process_work_item(self, work_item: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes a leased inbox work item through the 6-stage pipeline.
        """
        message_id = work_item.get("message_id", "unknown")
        input_data = work_item.get("input", {})
        kind = input_data.get("kind", "text")
        text = input_data.get("text")
        media_ref = input_data.get("media_ref")
        media_content_type = input_data.get("media_content_type")
        locale_hint = work_item.get("locale_hint", "ta-IN")
        correlation_id = work_item.get("correlation_id", "corr_unknown")

        logger.info(f"Starting processing for message '{message_id}' (kind={kind}, locale={locale_hint})...")

        # -------------------------------------------------------------
        # Stage 1: Multimodal Entity Extraction
        # -------------------------------------------------------------
        intel_input = IntelligenceInput(
            message_id=message_id,
            kind=kind,
            text=text,
            media_ref=media_ref,
            media_content_type=media_content_type,
            locale_hint=locale_hint,
            correlation_id=correlation_id
        )
        extraction: IntelligenceOutput = self.intelligence.process_input(intel_input)
        logger.info(f"Extraction result: crop={extraction.crop}, variety={extraction.variety}, price={extraction.offered_price}, intent={extraction.intent}")

        # -------------------------------------------------------------
        # Stage 2: Clarification Branch (Skip Decision Engine if info missing)
        # -------------------------------------------------------------
        is_voice = (kind == "audio")
        lang_input = LanguageInput(
            message_id=message_id,
            channel=work_item.get("channel", "whatsapp"),
            kind="voice" if is_voice else "text",
            locale_hint=locale_hint
        )

        if extraction.intent == ExtractionIntent.CLARIFICATION_NEEDED or extraction.missing_fields:
            logger.info(f"Clarification needed for fields: {extraction.missing_fields}. Bypassing Decision Engine.")
            lang_output: LanguageOutput = await self.language.render_clarification(
                missing_fields=extraction.missing_fields,
                input_dto=lang_input
            )
            # Stage 6: Outbound dispatch
            delivery_res = await self._dispatch_outbound(work_item, lang_output, correlation_id)
            return {
                "status": "CLARIFICATION_NEEDED",
                "message_id": message_id,
                "extraction": extraction.model_dump(),
                "decision": None,
                "delivery_payload": lang_output.model_dump(),
                "delivery_result": delivery_res
            }

        # -------------------------------------------------------------
        # Stage 3: Low-Latency Market Snapshot Lookup
        # -------------------------------------------------------------
        crop = extraction.crop or "Turmeric"
        variety = extraction.variety or "Finger"
        district = extraction.location or "Erode"
        snapshot = self.snapshot_reader.get_latest_snapshot(
            commodity=crop,
            variety=variety,
            district=district
        )

        # -------------------------------------------------------------
        # Stage 4: Pure Decision Engine Evaluation
        # -------------------------------------------------------------
        decision_input = DecisionInput(
            request_id=message_id,
            crop=crop,
            variety=variety,
            district=district,
            offered_price=Money(value=float(extraction.offered_price or 1.0), unit=extraction.unit or "quintal"),
            historical_data=snapshot,
            extraction_confidence=extraction.confidence,
            policy_version="1.0.0",
            engine_version="1.0.0"
        )
        engine = DecisionEngine()
        decision: DecisionOutput = engine.evaluate(decision_input)
        logger.info(f"Decision evaluated: action={decision.action}, offer_ratio={decision.offer_ratio:.2f}")

        # -------------------------------------------------------------
        # Stage 5: Localized Response & TTS Synthesis
        # -------------------------------------------------------------
        lang_output: LanguageOutput = await self.language.render_decision(
            decision=decision,
            input_dto=lang_input
        )

        # -------------------------------------------------------------
        # Stage 6: Proactive Outbound Channel Dispatch
        # -------------------------------------------------------------
        delivery_res = await self._dispatch_outbound(work_item, lang_output, correlation_id)

        return {
            "status": "SUCCESS",
            "message_id": message_id,
            "extraction": extraction.model_dump(),
            "decision": decision.model_dump(),
            "delivery_payload": lang_output.model_dump(),
            "delivery_result": delivery_res
        }
