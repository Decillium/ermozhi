import uuid
import logging
from typing import Optional, List, Tuple

from src.contracts.v1 import (
    LanguageInput,
    LanguageOutput,
    DecisionOutput,
    FallbackStatus
)
from src.language.templates import LanguageTemplateEngine
from src.language.tts import TTSAdapter
from src.data.storage.blob_repo import BlobStorageRepository

logger = logging.getLogger("LanguageEngine")


class LanguageEngine:
    """
    Renders localized farmer responses and synthesizes voice audio with zero disk I/O.
    """

    def __init__(
        self,
        tts_adapter: Optional[TTSAdapter] = None,
        repository: Optional[BlobStorageRepository] = None
    ):
        self.repository = repository or BlobStorageRepository()
        self.tts = tts_adapter or TTSAdapter(repository=self.repository)

    async def render_decision(
        self,
        decision: DecisionOutput,
        input_dto: LanguageInput
    ) -> LanguageOutput:
        """Renders localized decision text and synthesizes audio if requested."""
        locale = input_dto.locale_hint or "ta-IN"
        text, disclosure, template_id = LanguageTemplateEngine.render_decision_response(decision, locale=locale)
        response_id = f"resp_{uuid.uuid4().hex[:12]}"

        media_url = None
        duration = None
        fallback_status = FallbackStatus.NONE

        if input_dto.kind == "voice":
            media_url, duration, fallback_status = await self.tts.synthesize_to_storage(
                text=text,
                response_id=response_id,
                locale=locale
            )

        return LanguageOutput(
            message_id=input_dto.message_id,
            locale=locale,
            text_content=text,
            media_ref=media_url,
            media_content_type="audio/mpeg" if media_url else None,
            media_duration_seconds=duration,
            fallback_status=fallback_status,
            template_id=template_id,
            source_disclosure=disclosure,
            contract_version=input_dto.contract_version
        )

    async def render_clarification(
        self,
        missing_fields: List[str],
        input_dto: LanguageInput
    ) -> LanguageOutput:
        """Renders targeted clarification text and synthesizes audio if requested."""
        locale = input_dto.locale_hint or "ta-IN"
        text, disclosure, template_id = LanguageTemplateEngine.render_clarification_response(missing_fields, locale=locale)
        response_id = f"resp_{uuid.uuid4().hex[:12]}"

        media_url = None
        duration = None
        fallback_status = FallbackStatus.CLARIFICATION

        if input_dto.kind == "voice":
            media_url, duration, _ = await self.tts.synthesize_to_storage(
                text=text,
                response_id=response_id,
                locale=locale
            )

        return LanguageOutput(
            message_id=input_dto.message_id,
            locale=locale,
            text_content=text,
            media_ref=media_url,
            media_content_type="audio/mpeg" if media_url else None,
            media_duration_seconds=duration,
            fallback_status=fallback_status,
            template_id=template_id,
            source_disclosure=disclosure,
            contract_version=input_dto.contract_version
        )
