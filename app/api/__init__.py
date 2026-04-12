"""API routes for dashboard and WebSocket."""
from .dashboard import router as dashboard_router
from .websocket import router as websocket_router
from .settings import router as settings_router
from .dispatcher_api import router as dispatcher_router
from .scenarios import router as scenarios_router

__all__ = ["dashboard_router", "websocket_router", "settings_router", "dispatcher_router", "scenarios_router"]
