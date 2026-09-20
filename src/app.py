"""
===========================================================================
 ERMOZHI — FastAPI Server & Webhook Orchestrator
===========================================================================
 File    : src/app.py
 Purpose : Production-ready FastAPI server receiving WhatsApp webhooks from
           Meta WhatsApp Cloud API, serving media files (/audio/{filename}),
           orchestrating asynchronous processing via Azure Blob Storage inbox,
           and returning immediate HTTP 200 acknowledgements.

 Target Architecture & Endpoint Routes:
   1. GET/POST /api/v1/channels/meta-whatsapp/webhook - Meta WhatsApp Webhook
   2. POST /api/v1/channels/meta-whatsapp/status     - Meta Delivery Status
   3. GET  /api/v1/health/live                       - Liveness Probe
   4. GET  /api/v1/health/ready                      - Readiness Probe
   5. GET  /audio/{filename}                         - Static File Server (.mp3)
   6. GET  /health                                   - Legacy Health Probe
   7. GET  /                                         - Service Metadata
===========================================================================
"""

import os
import sys
import uuid
import logging
from typing import Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()  # Sourced from root .env before any config reads

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import FileResponse, Response

# Ensure src directory is in sys.path
src_path = os.path.dirname(os.path.abspath(__file__))
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from src.gateway.routes import health_router, meta_router, status_router


# ===========================================================================
# 1. CENTRALIZED CONFIGURATION
# ===========================================================================
class Config:
    """
    Runtime configuration sourced from environment variables.
    Supports Azure Container Apps, Docker, and local development.
    """
    ENV: str = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "production"))
    PORT: int = int(os.getenv("PORT", 8080))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    META_APP_SECRET: str = os.getenv("META_APP_SECRET", "").strip()
    META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "").strip()

    ALLOWED_AUDIO_MIME_TYPES = (
        "audio/ogg",
        "audio/opus",
        "audio/mp3",
        "audio/amr",
        "audio/m4a",
        "audio/mpeg",
    )

    # Audio output directory selection
    if os.name == 'posix':
        AUDIO_OUTPUT_DIR: str = os.getenv("AUDIO_OUTPUT_DIR", "/tmp/output_audio")
    else:
        AUDIO_OUTPUT_DIR: str = os.getenv("AUDIO_OUTPUT_DIR", "output_audio")


# Guarantee output directory exists
os.makedirs(Config.AUDIO_OUTPUT_DIR, exist_ok=True)


# ===========================================================================
# 2. LOGGING CONFIGURATION
# ===========================================================================
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] [ReqID: %(request_id)s] %(message)s"
)
logger = logging.getLogger("Ermozhi-Gateway")

class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "system"
        return True

logger.addFilter(RequestIdFilter())


# ===========================================================================
# 3. FASTAPI APPLICATION FACTORY
# ===========================================================================
app = FastAPI(
    title="Ermozhi API Gateway",
    description="High-throughput Meta WhatsApp Cloud API gateway and orchestrator",
    version="2.0.0",
)

# Register API v1 channel ingress and operational routes
app.include_router(health_router)
app.include_router(meta_router)
app.include_router(status_router)


# ===========================================================================
# 4. ROUTE DEFINITIONS & COMPATIBILITY ALIASES
# ===========================================================================

@app.get("/audio/{filename}")
async def get_audio_file(filename: str):
    """
    Media Static File Route.
    Serves synthesized male voice .mp3 notes for WhatsApp playback.
    """
    # Sanitize filename to prevent directory traversal attacks
    clean_filename = os.path.basename(filename)
    file_path = os.path.join(Config.AUDIO_OUTPUT_DIR, clean_filename)

    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio file '{clean_filename}' not found."
        )

    return FileResponse(
        path=file_path,
        media_type="audio/mpeg",
        filename=clean_filename
    )


@app.get("/")
@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check probe for Azure Container Apps and uptime monitors.
    """
    return {
        "status": "healthy",
        "service": "Ermozhi API Gateway",
        "framework": "FastAPI",
        "channel": "Meta WhatsApp Cloud API",
        "environment": Config.ENV,
    }


@app.get("/favicon.ico")
async def favicon():
    """Silently ignore browser icon requests."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# 5. MAIN EXECUTION
# ===========================================================================
if __name__ == "__main__":
    import uvicorn
    logger.info(
        f"Launch Ermozhi FastAPI Server on port {Config.PORT} (env={Config.ENV})",
        extra={"request_id": "startup"}
    )
    uvicorn.run("src.app:app", host="0.0.0.0", port=Config.PORT, reload=(Config.ENV == "development"))