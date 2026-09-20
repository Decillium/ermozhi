import re
import datetime
from typing import Optional, Dict, Any, Tuple, List
from src.contracts.v1 import MarketObservation


class RecordNormalizationError(Exception):
    """Raised when an individual market record fails validation."""
    pass


class MarketRecordNormalizer:
    """
    Normalizes raw market observation records from external sources (AGMARKNET, data.gov.in).
    Applies variety synonym mapping (including Tamil transliterations), flexible date parsing,
    price coercion, and composite fingerprint deduplication.
    """

    VARIETY_SYNONYMS: Dict[str, str] = {
        # Finger variety aliases
        "finger": "Finger",
        "virali": "Finger",
        "விரலி": "Finger",
        "விரலி மஞ்சள்": "Finger",
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
        "round": "Bulb",
        "2nd sort": "Bulb",
    }

    @classmethod
    def normalize_variety(cls, raw_variety: Optional[str]) -> Optional[str]:
        """Maps Tamil, English, and local mandi variety aliases to canonical 'Finger' or 'Bulb'."""
        if not raw_variety:
            return None
        clean = raw_variety.strip().lower()
        if clean in cls.VARIETY_SYNONYMS:
            return cls.VARIETY_SYNONYMS[clean]

        for synonym, canonical in cls.VARIETY_SYNONYMS.items():
            if synonym in clean or clean in synonym:
                return canonical
        return raw_variety.strip().title()

    @classmethod
    def parse_arrival_date(cls, raw_date: Any) -> str:
        """
        Parses various date formats ('DD/MM/YYYY', 'YYYY-MM-DD', 'DD-MM-YYYY', 'YYYY/MM/DD')
        into canonical 'YYYY-MM-DD'.
        """
        if not raw_date:
            raise RecordNormalizationError("Arrival date is empty.")

        date_str = str(raw_date).strip().split("T")[0]

        # Standard YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            y, m, d = map(int, date_str.split("-"))
            cls._validate_calendar_date(y, m, d)
            return date_str

        # DD/MM/YYYY
        if re.match(r"^\d{1,2}/\d{1,2}/\d{4}$", date_str):
            d, m, y = map(int, date_str.split("/"))
            cls._validate_calendar_date(y, m, d)
            return f"{y:04d}-{m:02d}-{d:02d}"

        # DD-MM-YYYY
        if re.match(r"^\d{1,2}-\d{1,2}-\d{4}$", date_str):
            d, m, y = map(int, date_str.split("-"))
            cls._validate_calendar_date(y, m, d)
            return f"{y:04d}-{m:02d}-{d:02d}"

        # YYYY/MM/DD
        if re.match(r"^\d{4}/\d{1,2}/\d{1,2}$", date_str):
            y, m, d = map(int, date_str.split("/"))
            cls._validate_calendar_date(y, m, d)
            return f"{y:04d}-{m:02d}-{d:02d}"

        raise RecordNormalizationError(f"Unrecognized date format: '{raw_date}'")

    @staticmethod
    def _validate_calendar_date(y: int, m: int, d: int) -> None:
        try:
            datetime.date(y, m, d)
        except ValueError as e:
            raise RecordNormalizationError(f"Invalid calendar date ({y}-{m}-{d}): {e}")

    @classmethod
    def generate_fingerprint(cls, record: Dict[str, Any], source: str) -> str:
        """
        Generates a deterministic composite fingerprint for record deduplication:
        source + state + district + market + commodity + variety + grade + arrival_date
        """
        state = str(record.get("state") or record.get("State") or "Tamil Nadu").strip().lower()
        district = str(record.get("district") or record.get("District") or "Erode").strip().lower()
        market = str(record.get("market") or record.get("Market") or district).strip().lower()
        commodity = str(record.get("commodity") or record.get("Commodity") or "Turmeric").strip().lower()
        raw_var = str(record.get("variety") or record.get("Variety") or "Finger").strip()
        variety = (cls.normalize_variety(raw_var) or raw_var).lower()
        grade = str(record.get("grade") or record.get("Grade") or "FAQ").strip().lower()
        date_str = cls.parse_arrival_date(record.get("arrival_date") or record.get("Arrival_Date") or record.get("date"))

        return f"{source.lower()}:{state}:{district}:{market}:{commodity}:{variety}:{grade}:{date_str}"

    @classmethod
    def normalize_record(cls, raw: Dict[str, Any], source: str = "AGMARKNET") -> Tuple[Optional[MarketObservation], Optional[str]]:
        """
        Normalizes and validates a single raw market observation record into a canonical MarketObservation.
        Returns (observation, None) on success, or (None, failure_reason) on validation failure.
        """
        try:
            # 1. Price extraction and validation
            raw_modal = raw.get("modal_price") or raw.get("Modal_Price") or raw.get("modal")
            if raw_modal is None:
                return None, "Missing modal price"
            try:
                modal_price = float(raw_modal)
            except (ValueError, TypeError):
                return None, f"Non-numeric modal price: {raw_modal}"

            if modal_price <= 0:
                return None, f"Non-positive modal price: {modal_price}"

            # 2. Min / Max prices
            raw_min = raw.get("min_price") or raw.get("Min_Price")
            min_price = float(raw_min) if raw_min is not None and str(raw_min).strip() != "" else None
            if min_price is not None and min_price <= 0:
                min_price = None

            raw_max = raw.get("max_price") or raw.get("Max_Price")
            max_price = float(raw_max) if raw_max is not None and str(raw_max).strip() != "" else None
            if max_price is not None and max_price <= 0:
                max_price = None

            # 3. Date validation
            raw_date = raw.get("arrival_date") or raw.get("Arrival_Date") or raw.get("date")
            date_str = cls.parse_arrival_date(raw_date)

            # 4. Market / Mandi location
            market_name = str(raw.get("market") or raw.get("Market") or raw.get("district") or raw.get("District") or "Erode").strip()

            obs = MarketObservation(
                date=date_str,
                modal_price=modal_price,
                min_price=min_price,
                max_price=max_price,
                market=market_name,
                source=source,
            )
            return obs, None

        except RecordNormalizationError as e:
            return None, str(e)
        except Exception as e:
            return None, f"Unexpected error during normalization: {e}"
