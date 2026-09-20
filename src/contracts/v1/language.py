from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class FallbackStatus(str, Enum):
    """Fallback status of language rendering (e.g. if TTS fails)."""
    NONE = "NONE"
    TEXT_ONLY = "TEXT_ONLY"
    CLARIFICATION = "CLARIFICATION"


class LanguageInput(BaseModel):
    """Input payload dispatched to the Language Layer for localization and synthesis."""
    message_id: str = Field(..., description="Unique message identifier")
    channel: str = Field(default="whatsapp", description="Target messaging channel")
    kind: str = Field(default="voice", description="Farmer requested medium ('voice' or 'text')")
    media_ref: Optional[str] = Field(default=None, description="Storage URI for incoming audio asset")
    media_content_type: Optional[str] = Field(default=None, description="MIME type of incoming audio")
    text: Optional[str] = Field(default=None, description="Incoming text if available")
    locale_hint: str = Field(default="ta-IN", description="Farmer locale (e.g. ta-IN, en-IN)")
    user_language_preference: Optional[str] = Field(default="ta-IN", description="User preferred locale")
    context_ref: Optional[str] = Field(default=None, description="Conversation context reference")
    deadline_at: Optional[str] = Field(default=None, description="ISO 8601 deadline timestamp")
    contract_version: str = Field(default="1.0.0", description="Contract schema version")


class LanguageOutput(BaseModel):
    """
    Localized output produced by the Language Layer.
    Contains culturally appropriate Tamil/English text and optional durable audio asset reference.
    """
    message_id: str = Field(..., description="Unique message identifier")
    locale: str = Field(default="ta-IN", description="Response locale (e.g. ta-IN, en-IN)")
    text_content: str = Field(..., description="Localized text message for the farmer")
    media_ref: Optional[str] = Field(default=None, description="Durable Azure Blob Storage SAS URL or object URI for audio")
    media_content_type: Optional[str] = Field(default="audio/mpeg", description="MIME type of generated voice audio")
    media_duration_seconds: Optional[float] = Field(default=None, ge=0.0, description="Duration in seconds of voice note")
    media_expires_at: Optional[str] = Field(default=None, description="ISO 8601 expiration timestamp for SAS URL")
    fallback_status: FallbackStatus = Field(default=FallbackStatus.NONE, description="Fallback status (e.g. TEXT_ONLY if TTS failed)")
    template_id: Optional[str] = Field(default=None, description="Identifies the localization template used")
    source_disclosure: Optional[str] = Field(default=None, description="Official source/date disclaimer for farmer transparency")
    contract_version: str = Field(default="1.0.0", description="Contract schema version")
