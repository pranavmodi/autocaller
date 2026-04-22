"""API routes for dashboard and WebSocket."""
from .dashboard import router as dashboard_router
from .websocket import router as websocket_router
from .settings import router as settings_router
from .dispatcher_api import router as dispatcher_router
from .scenarios import router as scenarios_router
from .carrier import router as carrier_router
from .cadence_api import router as cadence_router
from .consults import router as consults_router

__all__ = [
    "dashboard_router", "websocket_router", "settings_router",
    "dispatcher_router", "scenarios_router", "carrier_router",
    "cadence_router", "consults_router",
]
