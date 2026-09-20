import os
import json
import uuid
import hashlib
import datetime
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Request, HTTPException, status, Header, Query, Depends
from fastapi.responses import PlainTextResponse, JSONResponse

from src.contracts.v1 import (
    CanonicalInboundMessage,
    InboundInput,
    ProcessingStatus
)
from src.gateway.security.signature import (
    verify_meta_signature,
    SignatureVerificationError,
    SecurityConfigurationError
)
from src.gateway.middleware.rate_limit import default_rate_limiter, check_rate_limit
from src.platform.storage.event_store import EventStore, EventStoreError

logger = logging.getLogger("MetaWhatsAppGateway")

router = APIRouter(prefix="/api/v1/channels/meta-whatsapp", tags=["Meta WhatsApp"])


def get_event_store() -> EventStore:
    return EventStore()


@router.get("/webhook")
async def verify_webhook_handshake(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge")
):
    """
    Handles Meta WhatsApp webhook token verification challenge.
    GET /api/v1/channels/meta-whatsapp/webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
    """
    expected_verify_token = os.getenv("META_VERIFY_TOKEN") or os.getenv("META_APP_SECRET", "default_verify_token")

    if hub_mode == "subscribe" and hub_verify_token == expected_verify_token:
        logger.info("Meta webhook verification handshake successful.")
        return PlainTextResponse(content=hub_challenge or "", status_code=status.HTTP_200_OK)

    logger.warning("Meta webhook verification handshake failed. Invalid verify token or mode.")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Verification token mismatch or invalid mode."
    )


@router.post("/webhook")
async def receive_meta_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None, alias="X-Hub-Signature-256"),
    event_store: EventStore = Depends(get_event_store)
):
    """
    Receives signed Meta WhatsApp Cloud API messages.
    1. Validates HMAC-SHA256 signature (X-Hub-Signature-256).
    2. Enforces sender rate limits.
    3. Normalizes payload into CanonicalInboundMessage.
    4. Persists durably into events/, inbox/, and provider index.
    5. Returns immediate HTTP 200 OK (< 500ms) without running AI/TTS inline.
    """
    raw_body = await request.body()
    app_secret = os.getenv("META_APP_SECRET", "test_meta_app_secret")

    # 1. Signature Verification
    try:
        verify_meta_signature(
            raw_body=raw_body,
            signature_header=x_hub_signature_256,
            app_secret=app_secret,
            raise_on_failure=True
        )
    except (SignatureVerificationError, SecurityConfigurationError) as e:
        logger.warning(f"Meta signature verification rejected: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Invalid or missing webhook signature."
        )

    # 2. Parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to parse Meta JSON payload: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload.")

    # 3. Extract Message Content from Meta Cloud API structure
    # Meta format: entry[0].changes[0].value.messages[0]
    entries = payload.get("entry", [])
    if not entries:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "NO_ENTRY"})

    changes = entries[0].get("changes", [])
    if not changes:
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "NO_CHANGES"})

    value = changes[0].get("value", {})
    messages = value.get("messages", [])
    if not messages:
        # Delivery status / read receipts
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "STATUS_UPDATE_IGNORED"})

    msg = messages[0]
    sender_phone = str(msg.get("from", "unknown")).strip()
    provider_msg_id = str(msg.get("id", f"meta_{uuid.uuid4().hex[:12]}")).strip()
    msg_type = msg.get("type", "text")

    # 4. Rate Limiting on Sender
    client_ip = request.client.host if request.client else "127.0.0.1"
    rate_limit_key = f"meta:{sender_phone or client_ip}"
    await check_rate_limit(rate_limit_key, limiter=default_rate_limiter)

    # 5. Build Canonical Input
    participant_ref = hashlib.sha256(sender_phone.encode("utf-8")).hexdigest()[:16]
    conversation_ref = f"conv_{participant_ref}"
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if msg_type == "text":
        text_body = msg.get("text", {}).get("body", "")
        inbound_input = InboundInput(kind="text", text=text_body)
    elif msg_type == "audio":
        audio_info = msg.get("audio", {})
        media_id = audio_info.get("id", "")
        mime_type = audio_info.get("mime_type", "audio/ogg")
        inbound_input = InboundInput(
            kind="audio",
            media_ref=f"meta://media/{media_id}",
            media_content_type=mime_type
        )
    else:
        inbound_input = InboundInput(kind=msg_type, text=f"Unsupported message type: {msg_type}")

    canonical_msg = CanonicalInboundMessage(
        message_id=f"msg_{uuid.uuid4().hex[:12]}",
        channel="whatsapp",
        provider="meta_whatsapp",
        provider_message_id=provider_msg_id,
        participant_ref=participant_ref,
        conversation_ref=conversation_ref,
        input=inbound_input,
        received_at=now_iso,
        locale_hint="ta-IN",
        correlation_id=f"corr_{uuid.uuid4().hex[:8]}",
        schema_version="1.0.0"
    )

    # 6. Durable Storage Persistence
    try:
        envelope, is_duplicate = event_store.persist_inbound_message(canonical_msg)
    except EventStoreError as e:
        logger.error(f"Event store durability write failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage persistence failed. Please retry."
        )

    # 7. Fast Acknowledgement (< 500ms)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ACCEPTED" if not is_duplicate else "DUPLICATE_ACCEPTED",
            "message_id": envelope.message_id,
            "event_id": envelope.event_id,
            "correlation_id": envelope.correlation_id,
            "is_duplicate": is_duplicate
        }
    )
