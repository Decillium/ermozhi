from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class DataFreshnessState(str, Enum):
    """Data freshness states for official market evidence."""
    FRESH = "FRESH"
    STALE = "STALE"
    INSUFFICIENT = "INSUFFICIENT"
    UNAVAILABLE = "UNAVAILABLE"


# Alias for backward compatibility with existing domain code
FreshnessStatus = DataFreshnessState


class MarketObservation(BaseModel):
    """A single market observation from official mandi sources (e.g. AGMARKNET)."""
    date: str = Field(..., description="Observation / arrival date in YYYY-MM-DD format")
    modal_price: float = Field(..., gt=0.0, description="Reported modal price per quintal")
    min_price: Optional[float] = Field(default=None, gt=0.0, description="Reported minimum price")
    max_price: Optional[float] = Field(default=None, gt=0.0, description="Reported maximum price")
    market: Optional[str] = Field(default=None, description="Market / APMC mandi name")
    source: str = Field(default="AGMARKNET", description="Data source identifier (e.g. AGMARKNET, data.gov.in)")

    @field_validator("date")
    @classmethod
    def validate_date_format(cls, v: str) -> str:
        parts = v.split("-")
        if len(parts) != 3 or len(parts[0]) != 4:
            raise ValueError(f"Date must follow YYYY-MM-DD format, got '{v}'")
        return v


class MarketAggregates(BaseModel):
    """Precomputed statistical aggregates for a market snapshot window."""
    median: float = Field(..., ge=0.0, description="Median modal price")
    mean: float = Field(..., ge=0.0, description="Mean modal price")
    min: float = Field(..., ge=0.0, description="Minimum modal price in window")
    max: float = Field(..., ge=0.0, description="Maximum modal price in window")
    volatility: float = Field(..., ge=0.0, description="Coefficient of variation: (stdev / mean) * 100")
    trend: Optional[str] = Field(default=None, description="Price trend direction (e.g. RISING, FALLING, STABLE)")


class MarketDataSnapshot(BaseModel):
    """
    Canonical market snapshot provided by the Data Layer for the Decision Engine.
    Represents an immutable, quality-approved window of official mandi evidence.
    """
    snapshot_id: str = Field(..., description="Unique snapshot identifier")
    crop: str = Field(default="Turmeric", description="Canonical crop name")
    variety: str = Field(default="Finger", description="Canonical variety name")
    district: str = Field(default="Erode", description="Canonical district")
    market: Optional[str] = Field(default=None, description="Optional specific market name")
    observations: List[MarketObservation] = Field(default_factory=list, description="Constituent market observations")
    aggregates: MarketAggregates = Field(..., description="Statistical aggregates across observations")
    observation_count: int = Field(..., ge=0, description="Total number of observations in snapshot")
    distinct_date_count: int = Field(..., ge=0, description="Number of distinct observation dates")
    observed_at: str = Field(..., description="Timestamp of latest observation in snapshot (ISO 8601 or YYYY-MM-DD)")
    retrieved_at: str = Field(..., description="Timestamp snapshot was computed / retrieved (ISO 8601)")
    freshness_status: DataFreshnessState = Field(default=DataFreshnessState.FRESH, description="Freshness status")
    quality_status: str = Field(default="APPROVED", description="Quality gate status (e.g. APPROVED, QUARANTINED)")


# Alias for backward compatibility with existing tests and imports
MarketSnapshot = MarketDataSnapshot
