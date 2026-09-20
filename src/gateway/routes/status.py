import json
import logging
import datetime
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Request, Response, status, Depends
from pydantic import BaseModel

from src.data.storage.blob_repo import BlobStorageRepository, BlobPathBuilder

logger = logging.getLogger("DeliveryStatusWebhook")

router = APIRouter(prefix="/api/v1/channels", tags=["Delivery Status"])


def get_repository() -> BlobStorageRepository:
    return BlobStorageRepository()


def _get_date_tuple() -> tuple[str, str, str]:
    now = datetime.datetime.now(datetime.timezone.utc)
    return f"{now.year:04d}", f"{now.month:02d}", f"{now.day:02d}"


def _append_status_transition(
    repo: BlobStorageRepository,
    identifier: str,
    provider: str,
    transition: Dict[str, Any]
) -> str:
    """
    Appends a delivery status transition to the durable status log in Blob Storage:
    events/{YYYY}/{MM}/{DD}/{identifier}_status.json
    """
    yyyy, mm, dd = _get_date_tuple()
    status_path = f"events/{yyyy}/{mm}/{dd}/{identifier}_status.json"
    
    existing = repo.load_json(status_path) or {
        "identifier": identifier,
        "provider": provider,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "transitions": []
    }
    
    existing.setdefault("transitions", []).append(transition)
    existing["last_updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    existing["current_status"] = transition.get("status", "unknown")
    
    repo.save_json(status_path, existing)
    return status_path


@router.post("/meta-whatsapp/status", status_code=status.HTTP_200_OK)
async def meta_delivery_status_callback(
    request: Request,
    repo: BlobStorageRepository = Depends(get_repository)
) -> Dict[str, Any]:
    """
    Ingests delivery status notifications from Meta WhatsApp Cloud API.
    Transitions: sent -> delivered -> read -> failed
    """
    try:
        body_bytes = await request.body()
        payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception as e:
        logger.warning(f"Malformed JSON in Meta status webhook: {e}")
        return {"status": "rejected", "detail": "Malformed JSON"}

    recorded = 0
    # Process standard Meta Graph API webhook format
    entries = payload.get("entry", [])
    if entries:
        for entry in entries:
            for change in entry.get("changes", []):
                val = change.get("value", {})
                statuses = val.get("statuses", [])
                for st in statuses:
                    wamid = st.get("id", "unknown_wamid")
                    status_name = st.get("status", "unknown")
                    ts = st.get("timestamp")
                    iso_time = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).isoformat() if ts else datetime.datetime.now(datetime.timezone.utc).isoformat()
                    
                    transition = {
                        "status": status_name,
                        "timestamp": iso_time,
                        "recipient_id": st.get("recipient_id"),
                        "errors": st.get("errors", []),
                        "raw": st
                    }
                    _append_status_transition(repo, wamid, "meta_whatsapp", transition)
                    recorded += 1
    else:
        # Fallback for direct test payload { "message_id": "...", "status": "delivered", ... }
        msg_id = payload.get("message_id") or payload.get("id") or "unknown_id"
        transition = {
            "status": payload.get("status", "unknown"),
            "timestamp": payload.get("timestamp", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            "details": payload
        }
        _append_status_transition(repo, msg_id, "meta_whatsapp", transition)
        recorded += 1

    logger.info(f"Meta delivery status callback processed: {recorded} transition(s) recorded.")
    return {"status": "acknowledged", "recorded_transitions": recorded}
