import re
from typing import Dict, Any, Optional, List, Tuple

from src.contracts.v1 import IntelligenceOutput, ExtractionIntent
from src.data.ingestion.normalizer import MarketRecordNormalizer


class DeterministicValidator:
    """
    Deterministic post-validation for raw model extractions.
    Enforces canonical variety mapping (including Tamil/dialect aliases), positive prices,
    unit consistency, and fail-closed clarification triggers when essential trading parameters are missing.
    """

    VARIETY_MAP: Dict[str, str] = {
        # Finger variety aliases
        "finger": "Finger",
        "virali": "Finger",
        "விரலி": "Finger",
        "விரலி மஞ்சள்": "Finger",
        "நாட்டு": "Finger",
        "நாட்டு மஞ்சள்": "Finger",
        "nattu": "Finger",
        "salem": "Finger",
        "erode local": "Finger",
        "local": "Finger",
        "1st sort": "Finger",
        # Bulb variety aliases
        "bulb": "Bulb",
        "gatta": "Bulb",
        "kizhangu": "Bulb",
        "கிழங்கு": "Bulb",
        "கிழங்கு மஞ்சள்": "Bulb",
        "முட்டை": "Bulb",
        "round": "Bulb",
        "2nd sort": "Bulb",
    }

    @classmethod
    def normalize_variety(cls, raw_variety: Optional[str]) -> Optional[str]:
        if not raw_variety or not str(raw_variety).strip():
            return None
        clean = str(raw_variety).strip().lower()
        if clean in cls.VARIETY_MAP:
            return cls.VARIETY_MAP[clean]
        for alias, canonical in cls.VARIETY_MAP.items():
            if alias in clean or clean in alias:
                return canonical
        return None

    @classmethod
    def normalize_price(cls, raw_price: Any) -> Optional[float]:
        if raw_price is None:
            return None
        try:
            # Handle string prices like "14,500" or "₹14500"
            clean_str = re.sub(r"[^\d.]", "", str(raw_price))
            if not clean_str:
                return None
            price_val = float(clean_str)
            if price_val <= 0:
                return None
            return round(price_val, 2)
        except (ValueError, TypeError):
            return None

    @classmethod
    def validate(
        cls,
        raw_data: Dict[str, Any],
        raw_metadata: Optional[Dict[str, Any]] = None
    ) -> IntelligenceOutput:
        """
        Validates and converts raw entity extraction dictionary into canonical IntelligenceOutput.
        """
        raw_crop = str(raw_data.get("crop") or "Turmeric").strip()
        raw_variety = raw_data.get("variety")
        canonical_variety = cls.normalize_variety(raw_variety)

        raw_price = raw_data.get("offered_price") or raw_data.get("offered_price_per_quintal") or raw_data.get("price")
        price = cls.normalize_price(raw_price)

        raw_qty = raw_data.get("quantity") or raw_data.get("quantity_quintals")
        quantity = None
        if raw_qty is not None:
            try:
                q_val = float(raw_qty)
                if q_val > 0:
                    quantity = round(q_val, 2)
            except (ValueError, TypeError):
                pass

        unit = str(raw_data.get("unit") or "quintal").strip().lower()
        if unit not in ["quintal", "kg", "kilogram", "tonne", "ton", "bag"]:
            unit = "quintal"

        location = str(raw_data.get("location") or "Erode").strip()

        # Assess missing fields
        missing: List[str] = []
        if not canonical_variety:
            missing.append("variety")
        if price is None:
            missing.append("offered_price")

        # Intent classification & confidence calculation
        if missing:
            intent = ExtractionIntent.CLARIFICATION_NEEDED
            # Base confidence penalized for missing parameters
            confidence = 0.50 if len(missing) == 1 else 0.30
        else:
            raw_intent = str(raw_data.get("intent", "PRICE_EVALUATION")).upper()
            if raw_intent == "GENERAL_INQUIRY":
                intent = ExtractionIntent.PRICE_EVALUATION
            else:
                intent = ExtractionIntent.PRICE_EVALUATION
            confidence = float(raw_data.get("confidence", 0.95))
            if confidence > 1.0:
                confidence = 1.0
            elif confidence < 0.0:
                confidence = 0.0

        return IntelligenceOutput(
            crop="Turmeric" if "turmeric" in raw_crop.lower() or "மஞ்சள்" in raw_crop else raw_crop.title(),
            variety=canonical_variety,
            offered_price=price,
            unit=unit,
            quantity=quantity,
            location=location,
            confidence=confidence,
            intent=intent,
            missing_fields=missing,
            raw_extraction=raw_metadata or raw_data
        )
