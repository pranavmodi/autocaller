from fastapi import APIRouter, HTTPException
from datetime import datetime
from pydantic import BaseModel, Field

from app.services import review_alerts

router = APIRouter(prefix="/api/review-alerts", tags=["review-alerts"])


class Config(BaseModel):
    enabled: bool | None = None
    auto_send: bool | None = None
    daily_limit: int | None = Field(default=None, ge=1, le=100)
    postal_address: str | None = Field(default=None, max_length=1000)
    sender: str | None = Field(default=None, max_length=320)
    auto_schedule: bool | None = None
    auto_schedule_time: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    auto_schedule_limit: int | None = Field(default=None, ge=1, le=20)


class SubscriptionUpdate(BaseModel):
    status: str


class Schedule(BaseModel):
    limit: int = Field(default=20, ge=1, le=20)
    start_at: datetime
    dry_run: bool = False
    actor: str = "operator"


@router.post("/schedule")
async def schedule(body: Schedule):
    from app.services.review_alert_lead_gen import schedule as schedule_wave
    try:
        return await schedule_wave(limit=body.limit, start_at=body.start_at, dry_run=body.dry_run, actor=body.actor)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("")
async def status():
    return await review_alerts.status()


@router.post("/config")
async def configure(body: Config):
    changes = body.model_dump(exclude_none=True)
    if changes.get("auto_schedule"):
        changes.update(delivery_mode="lead_gen", auto_send=False)
    candidate = {**await review_alerts.settings(), **changes}
    if candidate["auto_send"] and (blockers := review_alerts.readiness(candidate)):
        raise HTTPException(400, detail=blockers)
    return await review_alerts.configure(changes)


@router.post("/enroll")
async def enroll(dry_run: bool = True):
    if not dry_run:
        await review_alerts.configure({"enrollment_requested": True, "run_requested": True})
        return {"status": "requested", "message": "The worker will classify leader titles and enroll qualified firms in bounded batches"}
    return await review_alerts.enroll(dry_run=dry_run)


@router.post("/run")
async def run():
    await review_alerts.configure({"run_requested": True})
    return {"status": "requested", "message": "The server worker will run within five minutes"}


@router.post("/subscriptions/{pif_id}")
async def subscription(pif_id: str, body: SubscriptionUpdate):
    try:
        await review_alerts.set_subscription(pif_id, body.status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"pif_id": pif_id, "status": body.status}
