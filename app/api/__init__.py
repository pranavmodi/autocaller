"""API routes for dashboard and WebSocket."""
from .dashboard import router as dashboard_router
from .websocket import router as websocket_router
from .settings import router as settings_router
from .dispatcher_api import router as dispatcher_router
from .scenarios import router as scenarios_router
from .carrier import router as carrier_router
from .cadence_api import router as cadence_router
from .consults import router as consults_router
from .call_lists import router as call_lists_router
from .voice_preview import router as voice_preview_router
from .firm_reviews import router as firm_reviews_router
from .comms import router as comms_router
from .sequences import router as sequences_router
from .outreach import router as outreach_router
from .lead_gen import router as lead_gen_router
from .resend_webhooks import router as resend_webhooks_router
from .inbound_email import router as inbound_email_router
from .operator_notifications import router as operator_notifications_router
from .seo import router as seo_router
from .product_traces import router as product_traces_router
from .learning import router as learning_router
from .todos import router as todos_router

__all__ = [
    "dashboard_router", "websocket_router", "settings_router",
    "dispatcher_router", "scenarios_router", "carrier_router",
    "cadence_router", "consults_router", "call_lists_router",
    "voice_preview_router", "firm_reviews_router", "comms_router",
    "sequences_router", "outreach_router", "lead_gen_router",
    "resend_webhooks_router", "inbound_email_router",
    "operator_notifications_router", "seo_router", "product_traces_router",
    "learning_router", "todos_router",
]
