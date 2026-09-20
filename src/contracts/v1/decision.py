from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from src.contracts.v1.market import MarketDataSnapshot


class ActionType(str, Enum):
    """Canonical action recommendations emitted by the Decision Engine."""
    SELL = "SELL"
    NEGOTIATE = "NEGOTIATE"
    HOLD = "HOLD"
    WAIT = "WAIT"


# Alias for backward compatibility
DecisionAction = ActionType


class RiskLevel(str, Enum):
    """Risk classification levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ConfidenceBand(str, Enum):
    """Confidence rating bands."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ReasonCode(str, Enum):
    """Standardized machine-readable explanation reason codes."""
    OFFER_AT_OR_ABOVE_REFERENCE = "OFFER_AT_OR_ABOVE_REFERENCE"
    OFFER_BELOW_REFERENCE = "OFFER_BELOW_REFERENCE"
    OFFER_MATERIALLY_LOW = "OFFER_MATERIALLY_LOW"
    MARKET_DATA_FRESH = "MARKET_DATA_FRESH"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LIMITED_DATE_COVERAGE = "LIMITED_DATE_COVERAGE"
    VARIETY_MISMATCH_RISK = "VARIETY_MISMATCH_RISK"
    EXTRACTION_UNCERTAIN = "EXTRACTION_UNCERTAIN"
    HOLDING_CONTEXT_UNKNOWN = "HOLDING_CONTEXT_UNKNOWN"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class Money(BaseModel):
    """Monetary amount with currency and quantity unit."""
    value: float = Field(..., description="Numeric monetary value")
    currency: str = Field(default="INR", description="Currency code (e.g. INR)")
    unit: str = Field(default="quintal", description="Unit of measurement (e.g. quintal, kg)")

    @field_validator("value")
    @classmethod
    def validate_positive_value(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"Monetary value must be strictly positive, got: {v}")
        return v

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, v: str) -> str:
        allowed = {"quintal", "kg", "kilogram", "tonne", "ton", "bag"}
        normalized = v.strip().lower()
        if normalized not in allowed:
            raise ValueError(f"Unsupported unit: '{v}'. Must be one of {allowed}")
        return normalized


class Quantity(BaseModel):
    """Commodity quantity with unit."""
    value: float = Field(..., gt=0.0, description="Numeric quantity")
    unit: str = Field(default="quintal", description="Unit of measurement")


class DecisionExplanation(BaseModel):
    """Structured explainability facts and reason codes for the farmer response."""
    action: ActionType = Field(..., description="Selected canonical action")
    headline_code: str = Field(..., description="Primary headline summary code")
    reason_codes: List[ReasonCode] = Field(default_factory=list, description="Detailed reason codes")
    facts: Dict[str, Any] = Field(default_factory=dict, description="Key numerical and contextual facts")
    evidence_refs: List[str] = Field(default_factory=list, description="Pointers to snapshots and records")
    limitations: List[str] = Field(default_factory=list, description="Known caveats or limitations")


class DecisionInput(BaseModel):
    """Input contract for the Decision Engine."""
    request_id: str = Field(..., description="Unique request identifier")
    crop: str = Field(default="Turmeric", description="Canonical crop name")
    variety: str = Field(default="Finger", description="Canonical variety name")
    district: str = Field(default="Erode", description="Canonical district name")
    market: Optional[str] = Field(default=None, description="Optional specific market name")
    offered_price: Money = Field(..., description="Farmer or trader offered price")
    quantity: Optional[Quantity] = Field(default=None, description="Optional quantity offered")
    historical_data: MarketDataSnapshot = Field(..., description="Quality-approved market snapshot")
    extraction_confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="Confidence of entity extraction")
    policy_version: str = Field(default="1.0.0", description="Decision policy version")
    engine_version: str = Field(default="1.0.0", description="Decision engine version")


class ConfidenceStr(str):
    """
    Dual-compatible Confidence type.
    Acts as a percentage string (e.g. '85%') with .endswith('%') for legacy callers,
    while also supporting dict access (['value'], ['band'], ['caps_applied']) for the new architecture.
    """
    def __new__(cls, val_str: str, value: float = 0.0, band: str = "LOW", caps_applied: Optional[List[str]] = None):
        s = super().__new__(cls, val_str)
        s.value = value
        s.band = band
        s.caps_applied = caps_applied or []
        return s

    def __getitem__(self, item):
        if item == "value":
            return self.value
        if item == "band":
            return self.band
        if item == "caps_applied":
            return self.caps_applied
        return super().__getitem__(item)

    def get(self, item, default=None):
        if item == "value":
            return self.value
        if item == "band":
            return self.band
        if item == "caps_applied":
            return self.caps_applied
        return default


class DecisionOutput(BaseModel):
    """Output contract produced by the Decision Engine."""
    decision_id: str = Field(..., description="Unique decision identifier")
    action: ActionType = Field(..., description="Canonical action: SELL, NEGOTIATE, HOLD, WAIT")
    offer: Money = Field(..., description="Normalized offer price")
    reference: Money = Field(..., description="Reference market price (median)")
    offer_ratio: float = Field(..., description="Ratio of offer to reference price")
    difference_percent: float = Field(..., description="Percentage difference ((offer - ref) / ref) * 100")
    score: Dict[str, float] = Field(default_factory=dict, description="offer_score, evidence_score, decision_score")
    confidence: Any = Field(default_factory=dict, description="value, band, caps_applied")
    risk: Dict[str, Any] = Field(default_factory=dict, description="level, factors, unknowns")
    explanation: DecisionExplanation = Field(..., description="Structured explanation")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Snapshot ID, source references, window")
    policy_version: str = Field(default="1.0.0", description="Policy version used")
    engine_version: str = Field(default="1.0.0", description="Engine version used")
    created_at: str = Field(..., description="ISO 8601 creation timestamp")

    # Backward compatibility fields for legacy callers (src/main.py, src/response_generation_layer.py)
    decision: Optional[str] = Field(default=None, description="Legacy classification string")
    offer_price: Optional[float] = Field(default=None, description="Legacy offer price float")
    reference_price: Optional[float] = Field(default=None, description="Legacy reference price float")
    difference_pct: Optional[float] = Field(default=None, description="Legacy difference percent float")
    reason: Optional[str] = Field(default=None, description="Legacy one-line reason string")

    @model_validator(mode="after")
    def populate_legacy_fields(self) -> "DecisionOutput":
        """Ensures legacy fields are always populated for backward compatibility."""
        if self.decision is None:
            action_map = {
                ActionType.SELL: "Fair Price",
                ActionType.NEGOTIATE: "Negotiate",
                ActionType.HOLD: "Too Low",
                ActionType.WAIT: "Wait"
            }
            self.decision = action_map.get(self.action, "Negotiate")

        if self.offer_price is None and self.offer:
            self.offer_price = round(self.offer.value, 2)

        if self.reference_price is None and self.reference:
            self.reference_price = round(self.reference.value, 2)

        if self.difference_pct is None:
            self.difference_pct = round(self.difference_percent, 1)

        if self.reason is None and self.explanation:
            abs_diff = abs(round(self.difference_percent, 1))
            if self.action == ActionType.WAIT:
                self.reason = f"Market data requires verification or clarification: {self.explanation.headline_code}"
            elif self.difference_percent >= 0:
                self.reason = f"Trader offer is {abs_diff}% above recent market reference."
            else:
                self.reason = f"Trader offer is {abs_diff}% below recent market reference."

        return self
