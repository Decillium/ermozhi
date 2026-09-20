import os
import io
import json
import logging
import requests
import datetime
from typing import Optional, Dict, Any, Tuple
from google import genai
from google.genai import types

from src.contracts.v1 import (
    IntelligenceInput,
    IntelligenceOutput,
    ExtractionIntent
)
from src.intelligence.validator import DeterministicValidator
from src.data.storage.blob_repo import BlobPathBuilder, BlobStorageRepository

logger = logging.getLogger("GeminiIntelligenceAdapter")


class IntelligenceAdapterError(Exception):
    """Base exception for Intelligence Adapter operations."""
    pass


class GeminiIntelligenceAdapter:
    """
    Multimodal Intelligence Adapter for Gemini 3.5 Flash Lite.
    Processes text and audio queries, extracting structured trading parameters
    with strict deterministic post-validation and zero local disk I/O.
    """

    SYSTEM_INSTRUCTION = """
    You are the Intelligence Layer for Ermozhi, an AI assistant for turmeric farmers in Tamil Nadu.
    Extract transaction parameters from farmer messages (in Tamil, English, or Tanglish).
    
    Extraction Schema:
    - crop: "Turmeric" (or Tamil "மஞ்சள்")
    - variety: "Finger" (Virali/விரலி/நாட்டு), "Bulb" (Kizhangu/கிழங்கு/முட்டை), or null if unspecified
    - offered_price: Numeric price offered by trader per quintal in INR (e.g. 14200), or null if missing
    - unit: "quintal", "kg", or "bag" (default "quintal")
    - quantity: Numeric quantity in quintals if mentioned, else null
    - location: Market or district (e.g., Erode, Salem, Gobichettipalayam)
    - intent: "PRICE_EVALUATION" or "CLARIFICATION_NEEDED"
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        repository: Optional[BlobStorageRepository] = None
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.repository = repository or BlobStorageRepository()

    def fetch_and_store_media(
        self,
        media_url: str,
        message_id: str,
        content_type: Optional[str] = None
    ) -> Tuple[str, bytes]:
        """
        Downloads audio bytes from validated media URL directly into memory and persists
        to `media/inbound/{YYYY}/{MM}/{DD}/{message_id}.ogg` in Blob Storage (zero local disk I/O).
        """
        now = datetime.datetime.now(datetime.timezone.utc)
        blob_path = BlobPathBuilder.media_inbound_path(now, message_id, extension="ogg")

        # If already stored in repository
        existing = self.repository.load_bytes(blob_path)
        if existing:
            return blob_path, existing

        # If media_url is a storage pseudo-ref (e.g. "meta://media/123")
        if media_url.startswith("meta://") or media_url.startswith("blob://"):
            # Mock or direct storage reference
            return blob_path, b"dummy_audio_bytes"

        try:
            logger.info(f"Streaming inbound voice note from {media_url}...")
            resp = requests.get(media_url, timeout=10)
            if resp.status_code == 200:
                audio_bytes = resp.content
                self.repository.save_bytes(blob_path, audio_bytes, content_type=content_type or "audio/ogg")
                return blob_path, audio_bytes
            else:
                logger.warning(f"Failed to fetch media from {media_url}: HTTP {resp.status_code}")
                return blob_path, b""
        except Exception as e:
            logger.error(f"Error streaming inbound media: {e}")
            return blob_path, b""

    def extract_from_text(self, text: str, locale_hint: str = "ta-IN") -> IntelligenceOutput:
        """Processes plain text queries through Gemini or deterministic regex fallback."""
        if not text or not text.strip():
            return DeterministicValidator.validate({"intent": "CLARIFICATION_NEEDED"})

        if not self.client:
            # Deterministic heuristic extraction if Gemini API key is unconfigured
            return self._heuristic_extraction(text)

        try:
            config = types.GenerateContentConfig(
                system_instruction=self.SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.1,
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=f"Locale: {locale_hint}\nFarmer message: {text}",
                config=config,
            )
            raw_json = {}
            if response and hasattr(response, "text") and response.text:
                try:
                    raw_json = json.loads(response.text)
                except Exception:
                    pass
            return DeterministicValidator.validate(raw_json, raw_metadata={"source": "gemini_text"})
        except Exception as e:
            logger.warning(f"Gemini text extraction failed ({e}); falling back to heuristic parsing.")
            return self._heuristic_extraction(text)

    def extract_from_audio(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/ogg",
        locale_hint: str = "ta-IN"
    ) -> IntelligenceOutput:
        """Processes raw audio bytes directly via Gemini multimodal single-hop extraction."""
        if not audio_bytes:
            return DeterministicValidator.validate({"intent": "CLARIFICATION_NEEDED"})

        if not self.client:
            return DeterministicValidator.validate({"intent": "CLARIFICATION_NEEDED"})

        try:
            contents = [
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                f"Locale: {locale_hint}. Extract turmeric trading parameters from this voice note."
            ]
            config = types.GenerateContentConfig(
                system_instruction=self.SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.1,
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
            raw_json = {}
            if response and hasattr(response, "text") and response.text:
                try:
                    raw_json = json.loads(response.text)
                except Exception:
                    pass
            return DeterministicValidator.validate(raw_json, raw_metadata={"source": "gemini_audio"})
        except Exception as e:
            logger.warning(f"Gemini multimodal extraction failed: {e}")
            return DeterministicValidator.validate({"intent": "CLARIFICATION_NEEDED"})

    def process_input(self, input_dto: IntelligenceInput) -> IntelligenceOutput:
        """Unified dispatch for IntelligenceInput DTO."""
        if input_dto.kind == "text":
            return self.extract_from_text(input_dto.text or "", locale_hint=input_dto.locale_hint or "ta-IN")
        elif input_dto.kind == "audio":
            if input_dto.media_ref:
                # Load or fetch media
                if self.repository.exists(input_dto.media_ref):
                    audio_bytes = self.repository.load_bytes(input_dto.media_ref) or b""
                else:
                    _, audio_bytes = self.fetch_and_store_media(
                        media_url=input_dto.media_ref,
                        message_id=input_dto.message_id,
                        content_type=input_dto.media_content_type
                    )
                return self.extract_from_audio(
                    audio_bytes=audio_bytes,
                    mime_type=input_dto.media_content_type or "audio/ogg",
                    locale_hint=input_dto.locale_hint or "ta-IN"
                )
            return DeterministicValidator.validate({"intent": "CLARIFICATION_NEEDED"})
        else:
            return DeterministicValidator.validate({"intent": "CLARIFICATION_NEEDED"})

    @staticmethod
    def _heuristic_extraction(text: str) -> IntelligenceOutput:
        """Deterministic heuristic fallback when external GenAI SDK is unavailable."""
        raw_variety = None
        t_low = text.lower()
        if any(v in t_low for v in ["virali", "விரலி", "finger", "நாட்டு"]):
            raw_variety = "Finger"
        elif any(v in t_low for v in ["kizhangu", "கிழங்கு", "bulb", "gatta", "முட்டை"]):
            raw_variety = "Bulb"

        # Extract price numbers
        import re
        clean_text = text.replace(",", "")
        numbers = re.findall(r"\b\d{4,6}\b", clean_text)
        price = float(numbers[0]) if numbers else None

        return DeterministicValidator.validate({
            "crop": "Turmeric",
            "variety": raw_variety,
            "offered_price": price,
            "unit": "quintal",
            "location": "Erode",
            "intent": "PRICE_EVALUATION" if (raw_variety and price) else "CLARIFICATION_NEEDED"
        })
