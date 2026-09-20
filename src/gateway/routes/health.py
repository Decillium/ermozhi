import datetime
from fastapi import APIRouter, Depends, status, Response
from pydantic import BaseModel
from typing import Dict, Any

from src.platform.storage.event_store import EventStore

router = APIRouter(prefix="/api/v1/health", tags=["Health"])


def get_event_store() -> EventStore:
    return EventStore()


@router.get("/live", status_code=status.HTTP_200_OK)
async def liveness_probe() -> Dict[str, Any]:
    """
    Liveness probe: verifies process is alive and event loop is responsive.
    Does not execute deep external dependency calls.
    """
    return {
        "status": "ALIVE",
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


@router.get("/ready")
async def readiness_probe(
    response: Response,
    event_store: EventStore = Depends(get_event_store)
) -> Dict[str, Any]:
    """
    Readiness probe: confirms storage repository connectivity and configuration validity.
    Returns 200 if safe to accept events, or 503 if storage is unavailable.
    """
    is_ready = event_store.is_healthy()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if is_ready:
        return {
            "status": "READY",
            "storage": "CONNECTED",
            "timestamp": now
        }
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "NOT_READY",
            "storage": "UNAVAILABLE",
            "timestamp": now
        }
