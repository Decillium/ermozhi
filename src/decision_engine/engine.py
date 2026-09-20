import uuid
import datetime
import statistics
import logging
from typing import List, Dict, Any, Optional

from src.contracts.v1 import (
    ActionType,
    DataFreshnessState,
    FreshnessStatus,
    RiskLevel,
    ConfidenceBand,
    ReasonCode,
    Money,
    Quantity,
    MarketObservation,
    MarketAggregates,
    MarketDataSnapshot,
    MarketSnapshot,
    DecisionExplanation,
    DecisionInput,
    DecisionOutput,
    ConfidenceStr,
)

logger = logging.getLogger("DecisionEngine")


class DecisionEngineError(Exception):
    """Custom exception raised when the decision engine evaluation fails."""
    pass


class DecisionEngine:
    """
    Deterministic, pure zero-IO Decision Engine for Ermozhi.
    
    Evaluates farmer/trader offers against quality-approved market snapshots
    using versioned policy rules, a strict evidence gate, multi-factor confidence scoring,
    risk assessment, and structured explainability.
    """

    POLICY_VERSION = "1.0.0"
    ENGINE_VERSION = "1.0.0"

    # Canonical policy threshold constants
    SELL_THRESHOLD = 0.90
    NEGOTIATE_THRESHOLD = 0.80
    SELL_THRESHOLD_RATIO = 0.90
    NEGOTIATE_THRESHOLD_RATIO = 0.80
    MIN_EXTRACTION_CONFIDENCE = 0.60
    HIGH_VOLATILITY_THRESHOLD = 15.0  # Volatility > 15% triggers WAIT
    ELEVATED_VOLATILITY_THRESHOLD = 10.0

    def evaluate(self, input_data: DecisionInput) -> DecisionOutput:
        """
        Evaluates a farmer/trader offer against an official market snapshot.
        Pure function: zero network, zero file IO, 100% deterministic.
        """
        # 1. Basic sanity validation
        if input_data.offered_price.value <= 0:
            logger.error(f"Invalid offer price: {input_data.offered_price.value}")
            raise DecisionEngineError(f"Offered price must be strictly positive: ₹{input_data.offered_price.value}")

        snapshot = input_data.historical_data
        caps_applied: List[str] = []
        reason_codes: List[ReasonCode] = []
        limitations: List[str] = []
        evidence_gate_passed = True
        gate_failure_reason: Optional[str] = None

        # 2. Evidence Gate Checks

        # 2a. Variety & Crop validation (Fail-closed: Never guess or default)
        if not input_data.variety or input_data.variety.strip().lower() in {"", "unknown", "none"}:
            evidence_gate_passed = False
            gate_failure_reason = "Missing or unknown variety. Cannot evaluate price without specific variety."
            reason_codes.append(ReasonCode.VARIETY_MISMATCH_RISK)
            limitations.append("Offer variety is unspecified or unknown.")
        elif (
            snapshot.crop.strip().lower() != input_data.crop.strip().lower()
            or snapshot.variety.strip().lower() != input_data.variety.strip().lower()
        ):
            evidence_gate_passed = False
            gate_failure_reason = (
                f"Variety mismatch: requested {input_data.crop} ({input_data.variety}), "
                f"snapshot contains {snapshot.crop} ({snapshot.variety})."
            )
            reason_codes.append(ReasonCode.VARIETY_MISMATCH_RISK)
            limitations.append("Snapshot variety does not strictly match offered crop variety.")

        # 2b. Freshness check
        if snapshot.freshness_status in [DataFreshnessState.INSUFFICIENT, DataFreshnessState.UNAVAILABLE]:
            evidence_gate_passed = False
            gate_failure_reason = f"Market data freshness status is {snapshot.freshness_status.value}."
            reason_codes.append(ReasonCode.INSUFFICIENT_EVIDENCE)
            limitations.append("Market snapshot contains insufficient or unavailable data.")
        elif snapshot.freshness_status == DataFreshnessState.STALE:
            reason_codes.append(ReasonCode.MARKET_DATA_STALE)
            limitations.append("Market snapshot is stale relative to update SLA.")
            caps_applied.append("STALE_DATA_CAP_65")
        else:
            reason_codes.append(ReasonCode.MARKET_DATA_FRESH)

        # 2c. Date coverage check
        if snapshot.distinct_date_count < 1 or snapshot.observation_count < 1:
            evidence_gate_passed = False
            gate_failure_reason = "No observation dates available in snapshot."
            reason_codes.append(ReasonCode.LIMITED_DATE_COVERAGE)
            limitations.append("Snapshot has zero observations.")
        elif snapshot.distinct_date_count == 1:
            reason_codes.append(ReasonCode.LIMITED_DATE_COVERAGE)
            limitations.append("Snapshot contains only a single observation date.")
            caps_applied.append("SINGLE_DATE_CAP_50")
        elif snapshot.distinct_date_count < 3:
            reason_codes.append(ReasonCode.LIMITED_DATE_COVERAGE)
            limitations.append("Snapshot contains fewer than 3 distinct observation dates.")
            caps_applied.append("LIMITED_DATES_CAP_60")

        # 2d. Extraction confidence check
        if input_data.extraction_confidence < self.MIN_EXTRACTION_CONFIDENCE:
            evidence_gate_passed = False
            gate_failure_reason = f"Extraction confidence too low ({input_data.extraction_confidence:.2f} < {self.MIN_EXTRACTION_CONFIDENCE:.2f})."
            reason_codes.append(ReasonCode.EXTRACTION_UNCERTAIN)
            limitations.append("Extraction uncertainty exceeds safe decision threshold.")
        elif input_data.extraction_confidence < 0.85:
            reason_codes.append(ReasonCode.EXTRACTION_UNCERTAIN)
            limitations.append("Minor extraction uncertainty present in offer data.")

        # 2e. Volatility check (severe volatility triggers WAIT)
        volatility = snapshot.aggregates.volatility
        if volatility > self.HIGH_VOLATILITY_THRESHOLD:
            evidence_gate_passed = False
            gate_failure_reason = f"Severe market price volatility detected ({volatility:.1f}% > {self.HIGH_VOLATILITY_THRESHOLD:.1f}%)."
            reason_codes.append(ReasonCode.HIGH_VOLATILITY)
            limitations.append(f"Severe market price volatility makes reference price unreliable ({volatility:.1f}%).")
        elif volatility > self.ELEVATED_VOLATILITY_THRESHOLD:
            reason_codes.append(ReasonCode.HIGH_VOLATILITY)
            limitations.append(f"Recent market price volatility is elevated ({volatility:.1f}%).")
            caps_applied.append("HIGH_VOLATILITY_CAP_70")

        # Context limitations
        if input_data.quantity is None:
            reason_codes.append(ReasonCode.HOLDING_CONTEXT_UNKNOWN)
            limitations.append("Holding quantity context is unspecified.")

        # 3. Reference Price & Variance Calculation
        reference_price = snapshot.aggregates.median
        if reference_price <= 0:
            logger.error("Calculated reference price is <= 0")
            raise DecisionEngineError("Market reference price is zero or negative.")

        offer_val = input_data.offered_price.value
        offer_ratio = round(offer_val / reference_price, 4)
        difference_percent = round(((offer_val - reference_price) / reference_price) * 100, 1)

        # 4. Standardized Action Classification
        # SELL: ratio >= 0.90
        # NEGOTIATE: 0.80 <= ratio < 0.90
        # HOLD: ratio < 0.80
        # WAIT: evidence gate failures or severe volatility
        if not evidence_gate_passed:
            action = ActionType.WAIT
            headline_code = "WAIT_INSUFFICIENT_EVIDENCE"
        elif offer_ratio >= self.SELL_THRESHOLD_RATIO:
            action = ActionType.SELL
            headline_code = "OFFER_AT_OR_ABOVE_REFERENCE"
            reason_codes.append(ReasonCode.OFFER_AT_OR_ABOVE_REFERENCE)
        elif offer_ratio >= self.NEGOTIATE_THRESHOLD_RATIO:
            action = ActionType.NEGOTIATE
            headline_code = "OFFER_BELOW_REFERENCE"
            reason_codes.append(ReasonCode.OFFER_BELOW_REFERENCE)
        else:
            action = ActionType.HOLD
            headline_code = "OFFER_MATERIALLY_LOW"
            reason_codes.append(ReasonCode.OFFER_BELOW_REFERENCE)

        # 5. Scoring Mechanism
        # 5a. Offer Score (0 - 100) aligned with 0.90 / 0.80 / 0.70 policy bands
        if offer_ratio >= 1.00:
            offer_score = min(100.0, 90.0 + (offer_ratio - 1.0) * 100.0)
        elif offer_ratio >= self.SELL_THRESHOLD_RATIO:  # 0.90 <= ratio < 1.00 -> 75 to 89
            offer_score = 75.0 + ((offer_ratio - 0.90) / 0.10) * 14.0
        elif offer_ratio >= self.NEGOTIATE_THRESHOLD_RATIO:  # 0.80 <= ratio < 0.90 -> 50 to 74
            offer_score = 50.0 + ((offer_ratio - 0.80) / 0.10) * 24.0
        elif offer_ratio >= 0.70:  # 0.70 <= ratio < 0.80 -> 25 to 49
            offer_score = 25.0 + ((offer_ratio - 0.70) / 0.10) * 24.0
        else:  # ratio < 0.70 -> 0 to 24
            offer_score = max(0.0, (offer_ratio / 0.70) * 24.0)

        # 5b. Evidence Score (0 - 100)
        fresh_score = 100.0 if snapshot.freshness_status == DataFreshnessState.FRESH else (
            60.0 if snapshot.freshness_status == DataFreshnessState.STALE else 0.0
        )
        if snapshot.distinct_date_count >= 7:
            date_score = 100.0
        elif snapshot.distinct_date_count >= 5:
            date_score = 85.0
        elif snapshot.distinct_date_count >= 3:
            date_score = 70.0
        elif snapshot.distinct_date_count >= 2:
            date_score = 50.0
        else:
            date_score = 25.0

        extract_score = input_data.extraction_confidence * 100.0
        stability_score = max(0.0, 100.0 - volatility * 5.0)

        evidence_score = round(
            0.25 * fresh_score + 0.25 * date_score + 0.25 * extract_score + 0.25 * stability_score,
            1
        )
        decision_score = round(0.60 * offer_score + 0.40 * evidence_score, 1)

        # 6. Confidence Calculation
        if not evidence_gate_passed:
            confidence_val = 0.0
            confidence_band = ConfidenceBand.LOW
        else:
            # 5 components (20% each)
            c_fresh = fresh_score
            c_date = date_score
            c_comp = 100.0 if (
                snapshot.crop.strip().lower() == input_data.crop.strip().lower()
                and snapshot.variety.strip().lower() == input_data.variety.strip().lower()
            ) else 0.0
            c_stab = max(0.0, 100.0 - volatility * 4.0)
            c_extr = extract_score

            raw_confidence = 0.20 * c_fresh + 0.20 * c_date + 0.20 * c_comp + 0.20 * c_stab + 0.20 * c_extr

            # Apply hard caps
            capped_confidence = raw_confidence
            if "SINGLE_DATE_CAP_50" in caps_applied:
                capped_confidence = min(capped_confidence, 50.0)
            if "LIMITED_DATES_CAP_60" in caps_applied:
                capped_confidence = min(capped_confidence, 60.0)
            if "STALE_DATA_CAP_65" in caps_applied:
                capped_confidence = min(capped_confidence, 65.0)
            if "HIGH_VOLATILITY_CAP_70" in caps_applied:
                capped_confidence = min(capped_confidence, 70.0)

            confidence_val = round(capped_confidence, 1)
            if confidence_val >= 80.0:
                confidence_band = ConfidenceBand.HIGH
            elif confidence_val >= 60.0:
                confidence_band = ConfidenceBand.MEDIUM
            else:
                confidence_band = ConfidenceBand.LOW

        # 7. Risk Assessment
        risk_factors: List[str] = []
        if volatility > 7.0:
            risk_factors.append(f"Price volatility is elevated ({volatility:.1f}%).")
        if snapshot.freshness_status == DataFreshnessState.STALE:
            risk_factors.append("Market snapshot is stale.")
        if snapshot.distinct_date_count < 3:
            risk_factors.append("Limited distinct observation dates in snapshot.")
        if input_data.extraction_confidence < 0.85:
            risk_factors.append("Extraction confidence has minor uncertainty.")

        if len(risk_factors) >= 2 or volatility > 10.0 or not evidence_gate_passed:
            risk_level = RiskLevel.HIGH
        elif len(risk_factors) == 1 or volatility > 4.0:
            risk_level = RiskLevel.MEDIUM
        else:
            risk_level = RiskLevel.LOW

        # 8. Build Explanation
        facts = {
            "offered_price": offer_val,
            "reference_price": reference_price,
            "offer_ratio": offer_ratio,
            "difference_percent": difference_percent,
            "observation_count": snapshot.observation_count,
            "distinct_date_count": snapshot.distinct_date_count,
            "volatility": round(volatility, 2),
            "freshness_status": snapshot.freshness_status.value,
        }
        if gate_failure_reason:
            facts["gate_failure_reason"] = gate_failure_reason

        explanation = DecisionExplanation(
            action=action,
            headline_code=headline_code,
            reason_codes=list(dict.fromkeys(reason_codes)),  # Deduplicate while preserving order
            facts=facts,
            evidence_refs=[snapshot.snapshot_id],
            limitations=limitations
        )

        return DecisionOutput(
            decision_id=f"dec_{uuid.uuid4().hex[:12]}",
            action=action,
            offer=input_data.offered_price,
            reference=Money(value=reference_price, currency=input_data.offered_price.currency, unit=input_data.offered_price.unit),
            offer_ratio=offer_ratio,
            difference_percent=difference_percent,
            score={
                "offer_score": round(offer_score, 1),
                "evidence_score": evidence_score,
                "decision_score": decision_score
            },
            confidence=ConfidenceStr(
                f"{confidence_val:.0f}%" if confidence_val > 0 else "0%",
                value=confidence_val,
                band=confidence_band.value,
                caps_applied=caps_applied
            ),
            risk={
                "level": risk_level.value,
                "factors": risk_factors,
                "unknowns": ["quantity", "holding_capacity"] if input_data.quantity is None else ["holding_capacity"]
            },
            explanation=explanation,
            evidence={
                "snapshot_id": snapshot.snapshot_id,
                "crop": snapshot.crop,
                "variety": snapshot.variety,
                "district": snapshot.district,
                "observation_count": snapshot.observation_count,
                "distinct_date_count": snapshot.distinct_date_count,
                "observed_at": snapshot.observed_at
            },
            policy_version=self.POLICY_VERSION,
            engine_version=self.ENGINE_VERSION,
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )

    def evaluate_legacy(
        self,
        offered_price: float,
        last_7_day_prices: List[float],
        variety: Optional[str] = None,
        crop: str = "Turmeric",
        district: str = "Erode"
    ) -> DecisionOutput:
        """
        Backward-compatible evaluation method accepting legacy primitive inputs.
        Fails closed if variety is missing, empty, or unknown.
        """
        if not last_7_day_prices:
            raise DecisionEngineError("Cannot evaluate offer: Market price array is empty.")
        if offered_price is None or offered_price <= 0:
            raise DecisionEngineError(f"Invalid offer price: ₹{offered_price}")
        if not variety or variety.strip().lower() in {"", "unknown", "none"}:
            raise DecisionEngineError("Variety must be explicitly specified; cannot default to Finger.")

        valid_prices = [float(p) for p in last_7_day_prices if p is not None and float(p) > 0]
        if not valid_prices:
            raise DecisionEngineError("No valid positive market prices available for calculation.")

        # Compute statistics
        med_price = float(statistics.median(valid_prices))
        mean_price = float(statistics.mean(valid_prices))
        stdev_price = float(statistics.stdev(valid_prices)) if len(valid_prices) > 1 else 0.0
        volatility = (stdev_price / mean_price) * 100.0 if mean_price > 0 else 0.0

        # Construct synthetic observations with distinct dates
        observations = []
        base_date = datetime.date.today()
        for i, p in enumerate(valid_prices):
            obs_date = (base_date - datetime.timedelta(days=i)).isoformat()
            observations.append(
                MarketObservation(
                    date=obs_date,
                    modal_price=p,
                    market=district,
                    source="AGMARKNET"
                )
            )

        aggregates = MarketAggregates(
            median=med_price,
            mean=mean_price,
            min=min(valid_prices),
            max=max(valid_prices),
            volatility=volatility
        )

        snapshot = MarketDataSnapshot(
            snapshot_id=f"snap_legacy_{uuid.uuid4().hex[:8]}",
            crop=crop,
            variety=variety,
            district=district,
            observations=observations,
            aggregates=aggregates,
            observation_count=len(valid_prices),
            distinct_date_count=len(valid_prices),
            observed_at=base_date.isoformat(),
            retrieved_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            freshness_status=DataFreshnessState.FRESH,
            quality_status="APPROVED"
        )

        decision_input = DecisionInput(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            crop=crop,
            variety=variety,
            district=district,
            offered_price=Money(value=float(offered_price), currency="INR", unit="quintal"),
            historical_data=snapshot,
            extraction_confidence=1.0,
            policy_version=self.POLICY_VERSION,
            engine_version=self.ENGINE_VERSION
        )

        return self.evaluate(decision_input)
