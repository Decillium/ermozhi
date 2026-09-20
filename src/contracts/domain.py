"""
Backward compatibility module for src.contracts.domain.
Re-exports canonical models from src.contracts.v1.
"""

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
    FreshnessStatus,
    MarketObservation,
    MarketAggregates,
    MarketDataSnapshot,
    MarketSnapshot,
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

__all__ = [
    "ProcessingStatus",
    "InboundInput",
    "CanonicalInboundMessage",
    "EventEnvelope",
    "ExtractionIntent",
    "IntelligenceInput",
    "IntelligenceOutput",
    "DataFreshnessState",
    "FreshnessStatus",
    "MarketObservation",
    "MarketAggregates",
    "MarketDataSnapshot",
    "MarketSnapshot",
    "ActionType",
    "RiskLevel",
    "ConfidenceBand",
    "ReasonCode",
    "Money",
    "Quantity",
    "DecisionExplanation",
    "DecisionInput",
    "DecisionOutput",
    "ConfidenceStr",
    "FallbackStatus",
    "LanguageInput",
    "LanguageOutput",
]
