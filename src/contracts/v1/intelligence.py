from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator


class ExtractionIntent(str, Enum):
    """Farmer intent identified by the Intelligence Layer."""
    PRICE_EVALUATION = "PRICE_EVALUATION"
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED"
    UNSUPPORTED = "UNSUPPORTED"


class IntelligenceInput(BaseModel):
    """Input payload dispatched to the Intelligence Layer for entity extraction."""
    message_id: str = Field(..., description="Unique message identifier")
    kind: str = Field(..., description="'text' or 'audio'")
    text: Optional[str] = Field(default=None, description="Farmer text message (if text kind)")
    media_ref: Optional[str] = Field(default=None, description="Storage reference to audio asset (if audio kind)")
    media_content_type: Optional[str] = Field(default=None, description="MIME type of audio asset")
    locale_hint: Optional[str] = Field(default="ta-IN", description="Expected farmer locale (e.g. ta-IN)")
    correlation_id: str = Field(..., description="Correlation ID for distributed tracing")
    deadline_at: Optional[str] = Field(default=None, description="ISO 8601 deadline timestamp for extraction")


class IntelligenceOutput(BaseModel):
    """
    Structured extraction result emitted by the Intelligence Layer (Gemini).
    Strictly post-validated by the deterministic schema validator.
    """
    crop: Optional[str] = Field(default=None, description="Extracted canonical crop name (e.g. Turmeric)")
    variety: Optional[str] = Field(default=None, description="Extracted canonical variety name (e.g. Finger, Bulb)")
    offered_price: Optional[float] = Field(default=None, description="Offered price value")
    unit: Optional[str] = Field(default="quintal", description="Unit of measurement for price/quantity (e.g. quintal, kg)")
    quantity: Optional[float] = Field(default=None, ge=0.0, description="Optional quantity offered by farmer")
    location: Optional[str] = Field(default=None, description="Extracted market or district location (e.g. Erode)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall extraction confidence score (0.0 - 1.0)")
    intent: ExtractionIntent = Field(default=ExtractionIntent.PRICE_EVALUATION, description="Classified intent")
    missing_fields: List[str] = Field(default_factory=list, description="List of required fields missing from extraction")
    raw_extraction: Optional[Dict[str, Any]] = Field(default=None, description="Raw model extraction metadata for audit")

    @field_validator("offered_price")
    @classmethod
    def validate_positive_price(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError(f"Offered price must be strictly positive, got: {v}")
        return v

    @field_validator("unit")
    @classmethod
    def validate_known_unit(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            normalized = v.strip().lower()
            allowed = {"quintal", "kg", "kilogram", "tonne", "ton", "bag"}
            if normalized not in allowed:
                raise ValueError(f"Unsupported unit: '{v}'. Must be one of {allowed}")
            return normalized
        return v

    @model_validator(mode="after")
    def validate_intent_and_missing_fields(self) -> "IntelligenceOutput":
        """
        Enforce fail-closed safety: If intent is PRICE_EVALUATION but either
        variety or offered_price is missing, automatically flag missing fields
        and adjust intent to CLARIFICATION_NEEDED.
        """
        missing = list(self.missing_fields)
        if self.intent == ExtractionIntent.PRICE_EVALUATION:
            if not self.variety and "variety" not in missing:
                missing.append("variety")
            if self.offered_price is None and "offered_price" not in missing:
                missing.append("offered_price")

            if missing:
                self.intent = ExtractionIntent.CLARIFICATION_NEEDED
                self.missing_fields = missing
        return self
