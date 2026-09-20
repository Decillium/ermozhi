from src.gateway.routes.health import router as health_router
from src.gateway.routes.meta import router as meta_router
from src.gateway.routes.status import router as status_router

__all__ = [
    "health_router",
    "meta_router",
    "status_router",
]
