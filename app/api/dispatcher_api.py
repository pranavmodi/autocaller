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

    Body: {"enabled": true/false, "target_calls": N | null}

    If target_calls is set (int > 0) when starting, the dispatcher auto-
    stops after that many calls are placed in this run.
    """
    dispatcher = get_dispatcher()
    enabled = body.get("enabled", True)
    target = body.get("target_calls")

    if enabled:
        dispatcher.start(target_calls=target if target else None)
    else:
        dispatcher.stop()

    return get_dispatcher().get_status()


@router.post("/start-batch")
def dispatcher_start_batch(body: dict):
    """Start the dispatcher with a hard stop after N calls.

    Body: {"count": N}
    """
    count = int(body.get("count", 0))
    if count <= 0:
        return {"error": "count must be a positive integer"}
    get_dispatcher().start(target_calls=count)
    return get_dispatcher().get_status()


@router.get("/decisions")
def dispatcher_decisions():
    """Get full decision log for debugging."""
    return {"decisions": get_dispatcher().get_decision_log()}
