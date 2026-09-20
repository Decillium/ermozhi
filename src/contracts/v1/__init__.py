"""
Canonical Data Contracts (v1) for Ermozhi.
Defines immutable, strongly-typed Pydantic schemas across all layer boundaries.
"""

from src.contracts.v1.events import (
    ProcessingStatus,
    InboundInput,
    CanonicalInboundMessage,
    EventEnvelope,
)

from src.contracts.v1.intelligence import (
    ExtractionIntent,
    IntelligenceInput,
    IntelligenceOutput,
)

from src.contracts.v1.market import (
    DataFreshnessState,
    FreshnessStatus,
    MarketObservation,
    MarketAggregates,
    MarketDataSnapshot,
    MarketSnapshot,
)

from src.contracts.v1.decision import (
    ActionType,
    DecisionAction,
    RiskLevel,
    ConfidenceBand,
    ReasonCode,
    Money,
    Quantity,
    DecisionExplanation,
    DecisionInput,
    DecisionOutput,
    ConfidenceStr,
)

from src.contracts.v1.language import (
    FallbackStatus,
    LanguageInput,
    LanguageOutput,
)

__all__ = [
    # Events
    "ProcessingStatus",
    "InboundInput",
    "CanonicalInboundMessage",
    "EventEnvelope",
    # Intelligence
    "ExtractionIntent",
    "IntelligenceInput",
    "IntelligenceOutput",
    # Market
    "DataFreshnessState",
    "FreshnessStatus",
    "MarketObservation",
    "MarketAggregates",
    "MarketDataSnapshot",
    "MarketSnapshot",
    # Decision
    "ActionType",
    "DecisionAction",
    "RiskLevel",
    "ConfidenceBand",
    "ReasonCode",
    "Money",
    "Quantity",
    "DecisionExplanation",
    "DecisionInput",
    "DecisionOutput",
    "ConfidenceStr",
    # Language
    "FallbackStatus",
    "LanguageInput",
    "LanguageOutput",
]
