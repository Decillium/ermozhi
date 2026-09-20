import os
import re
import uuid
import time
import asyncio
import logging
import datetime
from typing import Optional, Dict, Any, List, Union
import httpx

logger = logging.getLogger("MetaWhatsAppClient")


class MetaDeliveryError(Exception):
    """Exception raised for unrecoverable Meta Graph API delivery errors."""
    def __init__(self, message: str, status_code: Optional[int] = None, retryable: bool = False, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}


class MetaWhatsAppClient:
    """
    Outbound client for Meta WhatsApp Cloud API (Graph API).
    - Dispatches dual messages: structured text recommendation + audio voice note (SAS URL).
    - Enforces 24-hour customer service window management (free-form vs. Meta Message Templates).
    - Supports outbound idempotency tracking, Retry-After header parsing, and exponential backoff with jitter.
    """

    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        graph_version: str = "v19.0",
        base_url: str = "https://graph.facebook.com",
        max_retries: int = 3,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.phone_number_id = phone_number_id or os.environ.get("META_WHATSAPP_PHONE_ID", "mock_phone_number_id")
        self.access_token = access_token or os.environ.get("META_ACCESS_TOKEN") or os.environ.get("META_WHATSAPP_TOKEN")
        self.graph_version = graph_version
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._http_client = http_client

    @property
    def messages_endpoint(self) -> str:
        return f"{self.base_url}/{self.graph_version}/{self.phone_number_id}/messages"

    @staticmethod
    def format_whatsapp_text(raw_text: str) -> str:
        """
        Converts basic markdown formatting into WhatsApp-compatible markup.
        e.g., **bold** -> *bold*, *italic* -> _italic_
        """
        if not raw_text:
            return ""
        # Convert markdown **bold** or __bold__ to WhatsApp *bold*
        text = re.sub(r"\*\*(.*?)\*\*", r"*\1*", raw_text)
        text = re.sub(r"__(.*?)__", r"*\1*", text)
        return text.strip()

    @staticmethod
    def is_within_24h_window(inbound_timestamp: Optional[Union[str, datetime.datetime]]) -> bool:
        """
        Checks if the farmer's inbound message was received within the 24-hour service window.
        """
        if not inbound_timestamp:
            return True
        try:
            if isinstance(inbound_timestamp, str):
                dt = datetime.datetime.fromisoformat(inbound_timestamp.replace("Z", "+00:00"))
            else:
                dt = inbound_timestamp
            
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            
            now = datetime.datetime.now(datetime.timezone.utc)
            diff_seconds = (now - dt).total_seconds()
            return diff_seconds <= 86400  # 24 hours
        except Exception as e:
            logger.warning(f"Error parsing inbound timestamp '{inbound_timestamp}': {e}. Defaulting to free-form window.")
            return True

    async def _post_with_retry(
        self,
        payload: Dict[str, Any],
        idempotency_key: str,
        client: httpx.AsyncClient
    ) -> Dict[str, Any]:
        """
        Executes an HTTP POST to Graph API with idempotency and retry logic.
        """
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Idempotency-Key": idempotency_key
        }

        url = self.messages_endpoint
        attempt = 0
        backoff_delay = 0.5

        while attempt < self.max_retries:
            attempt += 1
            try:
                response = await client.post(url, json=payload, headers=headers, timeout=10.0)
                
                # Check for rate limiting
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    sleep_time = float(retry_after) if retry_after else (backoff_delay * (2 ** (attempt - 1)))
                    logger.warning(f"Meta Graph API 429 Rate Limit on attempt {attempt}/{self.max_retries}. Backing off for {sleep_time:.2f}s...")
                    if attempt >= self.max_retries:
                        raise MetaDeliveryError("Meta Graph API Rate Limit exceeded after retries", status_code=429, retryable=True)
                    await asyncio.sleep(sleep_time)
                    continue

                # Check for transient server errors (5xx)
                if response.status_code >= 500:
                    sleep_time = backoff_delay * (2 ** (attempt - 1))
                    logger.warning(f"Meta Graph API 5xx error ({response.status_code}) on attempt {attempt}/{self.max_retries}. Retrying in {sleep_time:.2f}s...")
                    if attempt >= self.max_retries:
                        raise MetaDeliveryError(f"Meta Graph API 5xx server error: {response.text}", status_code=response.status_code, retryable=True)
                    await asyncio.sleep(sleep_time)
                    continue

                # Check for permanent client errors (4xx)
                if response.status_code >= 400:
                    err_json = {}
                    try:
                        err_json = response.json()
                    except Exception:
                        pass
                    raise MetaDeliveryError(
                        f"Meta Graph API client error: {response.status_code} - {response.text}",
                        status_code=response.status_code,
                        retryable=False,
                        details=err_json
                    )

                return response.json()

            except httpx.RequestError as exc:
                sleep_time = backoff_delay * (2 ** (attempt - 1))
                logger.warning(f"Network error communicating with Meta Graph API: {exc}. Retrying in {sleep_time:.2f}s...")
                if attempt >= self.max_retries:
                    raise MetaDeliveryError(f"Network error contacting Meta Graph API: {exc}", retryable=True)
                await asyncio.sleep(sleep_time)

        raise MetaDeliveryError("Maximum retry attempts reached without response", retryable=True)

    async def send_message(
        self,
        to_phone: str,
        text: Optional[str] = None,
        media_url: Optional[str] = None,
        media_type: str = "audio",
        inbound_timestamp: Optional[Union[str, datetime.datetime]] = None,
        template_name: Optional[str] = None,
        template_params: Optional[List[Dict[str, Any]]] = None,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends outbound text and/or audio message(s) to a recipient.
        Enforces customer service window rules:
        - Within 24 hours: sends free-form text message, followed by audio message if media_url is present.
        - Outside 24 hours: dispatches approved Meta template message.
        """
        to_clean = to_phone.strip().replace("whatsapp:", "").replace("+", "").replace(" ", "")
        idempotency_key = idempotency_key or f"idem_{uuid.uuid4().hex}"
        within_window = self.is_within_24h_window(inbound_timestamp)

        # Mock / Simulation mode if access token is missing
        if not self.access_token:
            logger.info(f"[SIMULATION] MetaWhatsAppClient dispatching to '{to_clean}' (within_window={within_window}, audio={bool(media_url)})")
            msg_ids = [f"wamid.sim_{uuid.uuid4().hex[:16]}"]
            if within_window and media_url:
                msg_ids.append(f"wamid.sim_audio_{uuid.uuid4().hex[:16]}")
            return {
                "status": "ACCEPTED",
                "mode": "simulation",
                "recipient": to_clean,
                "within_24h_window": within_window,
                "provider_message_ids": msg_ids,
                "idempotency_key": idempotency_key,
                "dispatched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
            }

        client_to_use = self._http_client or httpx.AsyncClient()
        dispatched_message_ids = []

        try:
            if within_window:
                # 1. Dispatch Free-form Text Message
                if text:
                    formatted_text = self.format_whatsapp_text(text)
                    text_payload = {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": to_clean,
                        "type": "text",
                        "text": {"preview_url": False, "body": formatted_text}
                    }
                    resp = await self._post_with_retry(text_payload, f"{idempotency_key}_text", client_to_use)
                    messages = resp.get("messages", [])
                    if messages:
                        dispatched_message_ids.append(messages[0].get("id"))

                # 2. Dispatch Free-form Audio Message if media_url present
                if media_url:
                    audio_payload = {
                        "messaging_product": "whatsapp",
                        "recipient_type": "individual",
                        "to": to_clean,
                        "type": "audio",
                        "audio": {"link": media_url}
                    }
                    resp = await self._post_with_retry(audio_payload, f"{idempotency_key}_audio", client_to_use)
                    messages = resp.get("messages", [])
                    if messages:
                        dispatched_message_ids.append(messages[0].get("id"))

            else:
                # Outside 24-hour service window: Use Meta Message Template
                t_name = template_name or "price_result_ta"
                params = template_params or [{"type": "text", "text": (text or "உழவன் விலை தகவல்")[:100]}]
                
                template_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": to_clean,
                    "type": "template",
                    "template": {
                        "name": t_name,
                        "language": {"code": "ta"},
                        "components": [
                            {
                                "type": "body",
                                "parameters": params
                            }
                        ]
                    }
                }
                resp = await self._post_with_retry(template_payload, f"{idempotency_key}_tpl", client_to_use)
                messages = resp.get("messages", [])
                if messages:
                    dispatched_message_ids.append(messages[0].get("id"))

        finally:
            if self._http_client is None:
                await client_to_use.aclose()

        return {
            "status": "ACCEPTED",
            "recipient": to_clean,
            "within_24h_window": within_window,
            "provider_message_ids": dispatched_message_ids,
            "idempotency_key": idempotency_key,
            "dispatched_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
