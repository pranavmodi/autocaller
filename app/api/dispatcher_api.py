"""REST API endpoints for dispatcher control and monitoring."""
from fastapi import APIRouter

from app.services.dispatcher import get_dispatcher

router = APIRouter(prefix="/api/dispatcher", tags=["dispatcher"])


@router.get("/status")
def dispatcher_status():
    """Get current dispatcher state and recent decisions."""
    return get_dispatcher().get_status()


@router.post("/toggle")
def dispatcher_toggle(body: dict):
    """Start or stop the dispatcher.

    Body: {"enabled": true/false}
    """
    dispatcher = get_dispatcher()
    enabled = body.get("enabled", True)

    if enabled:
        dispatcher.start()
    else:
        dispatcher.stop()

    return get_dispatcher().get_status()


@router.get("/decisions")
def dispatcher_decisions():
    """Get full decision log for debugging."""
    return {"decisions": get_dispatcher().get_decision_log()}
