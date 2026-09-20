import pytest
import datetime
from typing import List, Optional

from src.contracts.v1 import (
    ActionType,
    DataFreshnessState,
    RiskLevel,
    ConfidenceBand,
    ReasonCode,
    Money,
    Quantity,
    MarketObservation,
    MarketAggregates,
    MarketDataSnapshot,
    DecisionInput,
    DecisionOutput,
)
from src.decision_engine.engine import DecisionEngine, DecisionEngineError


def create_sample_snapshot(
    median: float = 16000.0,
    volatility: float = 2.5,
    distinct_dates: int = 7,
    freshness: DataFreshnessState = DataFreshnessState.FRESH,
    variety: str = "Finger",
    crop: str = "Turmeric",
    district: str = "Erode",
) -> MarketDataSnapshot:
    """Helper to generate a valid MarketDataSnapshot for testing."""
    observations = []
    base_date = datetime.date.today()
    for i in range(distinct_dates):
        d = (base_date - datetime.timedelta(days=i)).isoformat()
        observations.append(
            MarketObservation(
                date=d,
                modal_price=median,
                min_price=median - 200,
                max_price=median + 200,
                market=district,
                source="AGMARKNET",
            )
        )

    aggregates = MarketAggregates(
        median=median,
        mean=median,
        min=median - 200,
        max=median + 200,
        volatility=volatility,
    )

    return MarketDataSnapshot(
        snapshot_id="snap_test_001",
        crop=crop,
        variety=variety,
        district=district,
        observations=observations,
        aggregates=aggregates,
        observation_count=len(observations),
        distinct_date_count=distinct_dates,
        observed_at=base_date.isoformat(),
        retrieved_at="2026-09-20T12:00:00Z",
        freshness_status=freshness,
        quality_status="APPROVED",
    )


class TestDecisionEngineBoundaries:
    """Tests evaluating exact threshold boundaries for SELL (>= 0.90), NEGOTIATE (0.80-0.90), HOLD (< 0.80), and WAIT."""

    def setup_method(self):
        self.engine = DecisionEngine()

    def test_boundary_sell_0_900_vs_negotiate_0_899(self):
        """Offer at 0.900 is SELL; offer at 0.899 is NEGOTIATE."""
        snapshot = create_sample_snapshot(median=10000.0)

        # 1. Exactly 0.900 -> SELL
        input_900 = DecisionInput(
            request_id="req_900",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=9000.0),  # 9000 / 10000 = 0.900
            historical_data=snapshot,
            extraction_confidence=0.95,
        )
        out_900 = self.engine.evaluate(input_900)
        assert out_900.action == ActionType.SELL
        assert out_900.offer_ratio == 0.900
        assert out_900.decision == "Fair Price"
        assert ReasonCode.OFFER_AT_OR_ABOVE_REFERENCE in out_900.explanation.reason_codes

        # 2. Exactly 0.899 -> NEGOTIATE
        input_899 = DecisionInput(
            request_id="req_899",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=8990.0),  # 8990 / 10000 = 0.899
            historical_data=snapshot,
            extraction_confidence=0.95,
        )
        out_899 = self.engine.evaluate(input_899)
        assert out_899.action == ActionType.NEGOTIATE
        assert out_899.offer_ratio == 0.899
        assert out_899.decision == "Negotiate"
        assert ReasonCode.OFFER_BELOW_REFERENCE in out_899.explanation.reason_codes

    def test_boundary_negotiate_0_800_vs_hold_0_799(self):
        """Offer at 0.800 is NEGOTIATE; offer at 0.799 is HOLD."""
        snapshot = create_sample_snapshot(median=10000.0)

        # 1. Exactly 0.800 -> NEGOTIATE
        input_800 = DecisionInput(
            request_id="req_800",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=8000.0),  # 8000 / 10000 = 0.800
            historical_data=snapshot,
            extraction_confidence=0.95,
        )
        out_800 = self.engine.evaluate(input_800)
        assert out_800.action == ActionType.NEGOTIATE
        assert out_800.offer_ratio == 0.800
        assert out_800.decision == "Negotiate"
        assert ReasonCode.OFFER_BELOW_REFERENCE in out_800.explanation.reason_codes

        # 2. Exactly 0.799 -> HOLD
        input_799 = DecisionInput(
            request_id="req_799",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=7990.0),  # 7990 / 10000 = 0.799
            historical_data=snapshot,
            extraction_confidence=0.95,
        )
        out_799 = self.engine.evaluate(input_799)
        assert out_799.action == ActionType.HOLD
        assert out_799.offer_ratio == 0.799
        assert out_799.decision == "Too Low"
        assert ReasonCode.OFFER_BELOW_REFERENCE in out_799.explanation.reason_codes


class TestEvidenceGateAndSafety:
    """Tests strict evidence gates and fail-closed safety."""

    def setup_method(self):
        self.engine = DecisionEngine()

    def test_evidence_gate_unavailable_or_insufficient_freshness(self):
        """INSUFFICIENT or UNAVAILABLE freshness must trigger WAIT."""
        for state in [DataFreshnessState.INSUFFICIENT, DataFreshnessState.UNAVAILABLE]:
            snapshot = create_sample_snapshot(freshness=state)
            inp = DecisionInput(
                request_id="req_freshness",
                crop="Turmeric",
                variety="Finger",
                district="Erode",
                offered_price=Money(value=16000.0),
                historical_data=snapshot,
            )
            out = self.engine.evaluate(inp)
            assert out.action == ActionType.WAIT
            assert ReasonCode.INSUFFICIENT_EVIDENCE in out.explanation.reason_codes
            assert out.confidence["value"] == 0.0

    def test_evidence_gate_variety_mismatch(self):
        """Variety mismatch (e.g. requested Bulb, snapshot has Finger) triggers WAIT."""
        snapshot = create_sample_snapshot(variety="Finger")
        inp = DecisionInput(
            request_id="req_mismatch",
            crop="Turmeric",
            variety="Bulb",  # Mismatch!
            district="Erode",
            offered_price=Money(value=16000.0),
            historical_data=snapshot,
        )
        out = self.engine.evaluate(inp)
        assert out.action == ActionType.WAIT
        assert ReasonCode.VARIETY_MISMATCH_RISK in out.explanation.reason_codes

    def test_fail_closed_missing_or_unknown_variety(self):
        """Missing or unknown variety must trigger WAIT; never default to Finger."""
        snapshot = create_sample_snapshot(variety="Finger")
        for bad_variety in ["", "unknown", "None"]:
            inp = DecisionInput(
                request_id="req_bad_var",
                crop="Turmeric",
                variety=bad_variety,
                district="Erode",
                offered_price=Money(value=16000.0),
                historical_data=snapshot,
            )
            out = self.engine.evaluate(inp)
            assert out.action == ActionType.WAIT
            assert ReasonCode.VARIETY_MISMATCH_RISK in out.explanation.reason_codes

    def test_evidence_gate_severe_volatility(self):
        """Severe volatility (> 15%) triggers WAIT."""
        snapshot = create_sample_snapshot(volatility=18.5)
        inp = DecisionInput(
            request_id="req_vol",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=16000.0),
            historical_data=snapshot,
        )
        out = self.engine.evaluate(inp)
        assert out.action == ActionType.WAIT
        assert ReasonCode.HIGH_VOLATILITY in out.explanation.reason_codes

    def test_evidence_gate_low_extraction_confidence(self):
        """Extraction confidence < 0.60 triggers WAIT."""
        snapshot = create_sample_snapshot()
        inp = DecisionInput(
            request_id="req_low_conf",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=16000.0),
            historical_data=snapshot,
            extraction_confidence=0.55,  # Below 0.60!
        )
        out = self.engine.evaluate(inp)
        assert out.action == ActionType.WAIT
        assert ReasonCode.EXTRACTION_UNCERTAIN in out.explanation.reason_codes

    def test_legacy_evaluate_fails_closed_without_variety(self):
        """evaluate_legacy must fail closed if variety is missing or None."""
        with pytest.raises(DecisionEngineError, match="Variety must be explicitly specified"):
            self.engine.evaluate_legacy(
                offered_price=15000.0,
                last_7_day_prices=[15800, 16000, 15950],
                variety=None,  # No default!
            )

        with pytest.raises(DecisionEngineError, match="Variety must be explicitly specified"):
            self.engine.evaluate_legacy(
                offered_price=15000.0,
                last_7_day_prices=[15800, 16000, 15950],
                variety="",  # Empty!
            )


class TestDeterminismAndPurity:
    """Verifies that the Decision Engine is 100% deterministic with zero IO."""

    def test_100_runs_identical_output(self):
        engine = DecisionEngine()
        snapshot = create_sample_snapshot(median=16000.0, volatility=3.0)
        inp = DecisionInput(
            request_id="req_det",
            crop="Turmeric",
            variety="Finger",
            district="Erode",
            offered_price=Money(value=15500.0),
            historical_data=snapshot,
            extraction_confidence=0.95,
        )

        first_out = engine.evaluate(inp)
        for _ in range(100):
            subsequent_out = engine.evaluate(inp)
            assert subsequent_out.action == first_out.action
            assert subsequent_out.offer_ratio == first_out.offer_ratio
            assert subsequent_out.difference_percent == first_out.difference_percent
            assert subsequent_out.score == first_out.score
            assert subsequent_out.confidence["value"] == first_out.confidence["value"]
            assert subsequent_out.risk["level"] == first_out.risk["level"]
            assert subsequent_out.explanation.headline_code == first_out.explanation.headline_code
            assert subsequent_out.explanation.reason_codes == first_out.explanation.reason_codes
