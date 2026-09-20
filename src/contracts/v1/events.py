from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    """Canonical lifecycle status for an inbound message / event."""
    ACCEPTED = "ACCEPTED"
    PROCESSING = "PROCESSING"
    WAITING_FOR_CLARIFICATION = "WAITING_FOR_CLARIFICATION"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class InboundInput(BaseModel):
    """Payload details for the inbound farmer message."""
    kind: str = Field(..., description="'text' or 'audio'")
    text: Optional[str] = Field(default=None, description="Raw text content if text message")
    media_ref: Optional[str] = Field(default=None, description="Reference or URI to media asset")
    media_content_type: Optional[str] = Field(default=None, description="MIME type of media asset")
    media_duration_seconds: Optional[float] = Field(default=None, ge=0.0, description="Duration in seconds if audio")


class CanonicalInboundMessage(BaseModel):
    """
    Channel-agnostic canonical representation of an incoming farmer message.
    Translated by the Interface/Gateway layer from Meta WhatsApp or future channels.
    """
    message_id: str = Field(..., description="Unique internal message identifier (UUID)")
    channel: str = Field(default="whatsapp", description="Ingress channel (e.g., whatsapp, sms, ivr)")
    provider: str = Field(default="meta", description="Provider identifier (e.g., meta, meta_whatsapp)")
    provider_message_id: str = Field(..., description="Provider-assigned message identifier")
    participant_ref: str = Field(..., description="Hashed or tokenized participant identifier")
    conversation_ref: str = Field(..., description="Conversation or session thread identifier")
    input: InboundInput = Field(..., description="Input payload content")
    received_at: str = Field(..., description="ISO 8601 timestamp when received by gateway")
    locale_hint: Optional[str] = Field(default="ta-IN", description="Language/locale hint (e.g. ta-IN, en-IN)")
    correlation_id: str = Field(..., description="Correlation ID for distributed tracing")
    schema_version: str = Field(default="1.0.0", description="Contract schema version")


class EventEnvelope(BaseModel):
    """
    Standard event envelope for immutable event storage and queue dispatch.
    Stored in Azure Blob Storage under events/ and inbox/.
    """
    event_id: str = Field(..., description="Unique event identifier (UUID)")
    event_type: str = Field(..., description="Event type name (e.g. InboundMessageAccepted)")
    message_id: str = Field(..., description="Associated message identifier")
    conversation_id: str = Field(..., description="Associated conversation identifier")
    correlation_id: str = Field(..., description="Distributed tracing correlation ID")
    attempt: int = Field(default=1, ge=1, description="Processing attempt count")
    occurred_at: str = Field(..., description="ISO 8601 timestamp when the event occurred")
    schema_version: str = Field(default="1.0.0", description="Envelope schema version")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Redacted or sanitized event payload")
