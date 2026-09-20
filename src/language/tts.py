import io
import os
import uuid
import asyncio
import logging
import datetime
from typing import Optional, Tuple

from src.contracts.v1 import FallbackStatus
from src.data.storage.blob_repo import BlobPathBuilder, BlobStorageRepository

logger = logging.getLogger("TTSAdapter")


class TTSAdapter:
    """
    Synthesizes localized audio using Edge TTS directly into in-memory byte buffers
    and streams to Azure Blob Storage (zero local disk I/O).
    Provides graceful degradation to TEXT_ONLY on simulated or live synthesis failures.
    """

    VOICE_MAP = {
        "ta-IN": "ta-IN-ValluvarNeural",
        "ta": "ta-IN-ValluvarNeural",
        "en-IN": "en-IN-PrabhatNeural",
        "en": "en-IN-PrabhatNeural",
    }

    def __init__(
        self,
        repository: Optional[BlobStorageRepository] = None,
        timeout_seconds: float = 8.0,
        enable_tts: bool = True
    ):
        self.repository = repository or BlobStorageRepository()
        self.timeout = timeout_seconds
        self.enable_tts = enable_tts

    async def synthesize_to_storage(
        self,
        text: str,
        response_id: str,
        locale: str = "ta-IN"
    ) -> Tuple[Optional[str], Optional[float], FallbackStatus]:
        """
        Synthesizes text to MP3 bytes and uploads directly to
        `media/outbound/{YYYY}/{MM}/{DD}/{response_id}.mp3`.
        
        Returns:
            Tuple[media_sas_url, duration_seconds, fallback_status]
        """
        if not self.enable_tts or not text or not text.strip():
            return None, None, FallbackStatus.TEXT_ONLY

        now = datetime.datetime.now(datetime.timezone.utc)
        blob_path = BlobPathBuilder.media_outbound_path(now, response_id, extension="mp3")
        voice = self.VOICE_MAP.get(locale, "ta-IN-ValluvarNeural")

        try:
            import edge_tts
            communicate = edge_tts.Communicate(text=text, voice=voice)
            audio_buffer = io.BytesIO()

            async def _stream_audio():
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_buffer.write(chunk["data"])

            # Run synthesis with timeout guardrail
            await asyncio.wait_for(_stream_audio(), timeout=self.timeout)
            mp3_bytes = audio_buffer.getvalue()

            if not mp3_bytes:
                logger.warning("Edge TTS returned empty audio bytes. Falling back to TEXT_ONLY.")
                return None, None, FallbackStatus.TEXT_ONLY

            # Save MP3 bytes directly into Blob Storage
            self.repository.save_bytes(blob_path, mp3_bytes, content_type="audio/mpeg")
            sas_url = self.repository.generate_sas_url(blob_path, ttl_hours=1)
            
            # Rough duration calculation: ~16KB per second for 128kbps MP3
            est_duration = round(len(mp3_bytes) / 16000.0, 1)

            logger.info(f"Synthesized voice note ({len(mp3_bytes)} bytes) to '{blob_path}'.")
            return sas_url, est_duration, FallbackStatus.NONE

        except asyncio.TimeoutError:
            logger.warning(f"TTS synthesis timed out after {self.timeout}s. Degrading to TEXT_ONLY.")
            return None, None, FallbackStatus.TEXT_ONLY
        except Exception as e:
            logger.warning(f"TTS synthesis failed ({e}). Degrading gracefully to TEXT_ONLY.")
            return None, None, FallbackStatus.TEXT_ONLY
