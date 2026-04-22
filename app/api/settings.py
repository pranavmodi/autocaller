"""Settings API endpoints."""
import logging
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel

from app.models import BusinessHours, HolidayEntry, QueueThresholds, DispatcherSettings, SystemSettings
from app.providers import get_settings_provider
from app.providers.settings_provider import COMMON_TIMEZONES

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/settings", tags=["settings"])


# Pydantic models for request/response
class HolidayRequest(BaseModel):
    date: str  # YYYY-MM-DD
    name: str
    recurring: bool = True


class BusinessHoursRequest(BaseModel):
    start_time: str
    end_time: str
    enabled: bool
    timezone: str
    days_of_week: List[int] = [0, 1, 2, 3, 4]  # Mon-Fri (0=Mon, 6=Sun)
    holidays: List[HolidayRequest] = []


class QueueThresholdsRequest(BaseModel):
    calls_waiting_threshold: int
    holdtime_threshold_seconds: int
    stable_polls_required: int


class DispatcherSettingsRequest(BaseModel):
    poll_interval: int = 10
    dispatch_timeout: int = 30
    max_attempts: int = 3
    min_hours_between: int = 6
    cooldown_seconds: int = 0
    default_batch_size: int = 5
    verbose_logging: bool = False


class CooldownRequest(BaseModel):
    cooldown_seconds: int


class BatchSizeRequest(BaseModel):
    batch_size: int


class SourceRequest(BaseModel):
    source: str


class SystemSettingsRequest(BaseModel):
    system_enabled: bool
    business_hours: BusinessHoursRequest
    queue_thresholds: QueueThresholdsRequest
    allow_live_calls: bool = False
    allowed_phones: List[str] = []
    queue_source: str = "simulation"
    patient_source: str = "simulation"


class SystemEnabledRequest(BaseModel):
    enabled: bool


class AllowLiveCallsRequest(BaseModel):
    allowed: bool


class AllowedPhonesRequest(BaseModel):
    phones: List[str]


class DailyReportRequest(BaseModel):
    enabled: bool = False
    webhook_url: str = ""
    hour: int = 7
    timezone: str = "America/Los_Angeles"


class SystemSettingsResponse(BaseModel):
    system_enabled: bool
    business_hours: BusinessHoursRequest
    queue_thresholds: QueueThresholdsRequest
    dispatcher_settings: DispatcherSettingsRequest
    allow_live_calls: bool
    allowed_phones: List[str]
    queue_source: str
    patient_source: str
    active_scenario_id: str | None
    call_mode: str
    mock_mode: bool
    mock_phone: str
    daily_report: DailyReportRequest
    can_make_calls: bool
    is_within_business_hours: bool
    voice_provider: str = "openai"
    voice_model: str = ""
    voice_config: dict = {}
    ivr_navigate_enabled: bool = False


class VoiceProviderRequest(BaseModel):
    provider: str  # "openai" | "gemini"
    model: str = ""


class VoiceConfigRequest(BaseModel):
    """Merge-patch for per-provider voice knobs.

    `provider` is "openai" or "gemini". Any of the patch fields that
    aren't set are left as-is on the stored config. Keys unsupported by
    the selected provider (e.g. `affective_dialog` on OpenAI, `speed`
    on Gemini) return 400.
    """
    provider: str
    voice: str | None = None
    temperature: float | None = None
    affective_dialog: bool | None = None
    proactive_audio: bool | None = None
    speed: float | None = None       # OpenAI-only (0.25-4.0)
    top_p: float | None = None       # Gemini-only (0.0-1.0)


class IVRNavigateRequest(BaseModel):
    enabled: bool


class ActiveScenarioRequest(BaseModel):
    scenario_id: str


class CallModeRequest(BaseModel):
    call_mode: str  # "web" or "twilio"


class MockModeRequest(BaseModel):
    enabled: bool
    mock_phone: str = ""


async def _broadcast_settings_change(response: "SystemSettingsResponse"):
    """Push a settings_updated event to all connected dashboard clients.

    This keeps other browser windows in sync when one window changes a setting.
    """
    try:
        from app.api.websocket import broadcast_to_dashboards
        await broadcast_to_dashboards({
            "type": "settings_updated",
            "settings": response.model_dump(),
        })
    except Exception:
        pass  # Don't fail the request if broadcast fails


async def settings_response_and_broadcast(provider) -> SystemSettingsResponse:
    """Build the settings response AND broadcast the change to all WebSocket clients."""
    resp = await settings_to_response(provider)
    await _broadcast_settings_change(resp)
    return resp


async def settings_to_response(provider) -> SystemSettingsResponse:
    """Convert settings to response model."""
    settings = await provider.get_settings()
    return SystemSettingsResponse(
        system_enabled=settings.system_enabled,
        business_hours=BusinessHoursRequest(
            start_time=settings.business_hours.start_time,
            end_time=settings.business_hours.end_time,
            enabled=settings.business_hours.enabled,
            timezone=settings.business_hours.timezone,
            days_of_week=settings.business_hours.days_of_week,
            holidays=[
                HolidayRequest(
                    date=h.date,
                    name=h.name,
                    recurring=h.recurring,
                )
                for h in settings.business_hours.holidays
            ],
        ),
        queue_thresholds=QueueThresholdsRequest(
            calls_waiting_threshold=settings.queue_thresholds.calls_waiting_threshold,
            holdtime_threshold_seconds=settings.queue_thresholds.holdtime_threshold_seconds,
            stable_polls_required=settings.queue_thresholds.stable_polls_required,
        ),
        dispatcher_settings=DispatcherSettingsRequest(
            poll_interval=settings.dispatcher_settings.poll_interval,
            dispatch_timeout=settings.dispatcher_settings.dispatch_timeout,
            max_attempts=settings.dispatcher_settings.max_attempts,
            min_hours_between=settings.dispatcher_settings.min_hours_between,
            cooldown_seconds=settings.dispatcher_settings.cooldown_seconds,
            default_batch_size=settings.dispatcher_settings.default_batch_size,
            verbose_logging=settings.dispatcher_settings.verbose_logging,
        ),
        allow_live_calls=settings.allow_live_calls,
        allowed_phones=settings.allowed_phones,
        queue_source=settings.queue_source,
        patient_source=settings.patient_source,
        active_scenario_id=settings.active_scenario_id,
        call_mode=settings.call_mode,
        mock_mode=settings.mock_mode,
        mock_phone=settings.mock_phone,
        daily_report=DailyReportRequest(
            enabled=settings.daily_report.enabled,
            webhook_url=settings.daily_report.webhook_url,
            hour=settings.daily_report.hour,
            timezone=settings.daily_report.timezone,
        ),
        can_make_calls=await provider.can_make_outbound_call(),
        is_within_business_hours=await provider.is_within_business_hours(),
        voice_provider=getattr(settings, "voice_provider", "openai") or "openai",
        voice_model=getattr(settings, "voice_model", "") or "",
        voice_config=dict(getattr(settings, "voice_config", None) or {}),
        ivr_navigate_enabled=bool(getattr(settings, "ivr_navigate_enabled", False)),
    )


async def activate_scenario(scenario_id: str) -> None:
    """Load scenario data into mock providers and restart the dispatcher.

    Only prepares the mock data — does NOT change which source (live vs
    simulation) is active.  The caller or the individual source-switch
    endpoints are responsible for setting the in-memory source.

    Note: call logs are NOT cleared — they are historical records that
    should persist across scenario switches and server restarts.
    Use DELETE /api/calls to clear them explicitly.
    """
    from sqlalchemy import select
    from app.db import AsyncSessionLocal
    from app.db.models import SimulationScenarioRow
    from app.providers import get_mock_queue_provider, get_simulation_patient_provider
    from app.services.dispatcher import get_dispatcher

    print(f"[ACTIVATE_SCENARIO] Activating scenario: {scenario_id}")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SimulationScenarioRow).where(SimulationScenarioRow.id == scenario_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            print(f"[ACTIVATE_SCENARIO] Scenario not found: {scenario_id}")
            raise ValueError(f"Scenario not found: {scenario_id}")

        patient_count = len(row.patients or [])
        queue_count = len(row.queues or [])
        print(f"[ACTIVATE_SCENARIO] Loading scenario '{row.label}': {patient_count} patients, {queue_count} queues")

        for p in (row.patients or []):
            print(f"[ACTIVATE_SCENARIO] - Patient from DB: {p.get('name')}, {p.get('phone')}")

        # 1. Reset mock queue provider with scenario data
        queue_provider = get_mock_queue_provider()
        queue_provider.reset_with_config(
            queues_config=row.queues or [],
            ami_connected=row.ami_connected,
        )

        # 2. Reset simulation patient provider with scenario data
        patient_provider = get_simulation_patient_provider()
        await patient_provider.reset_with_patients(
            patient_dicts=row.patients or []
        )

        # 3. Restart dispatcher
        get_dispatcher().restart()

        print(f"[ACTIVATE_SCENARIO] Scenario '{row.label}' activated successfully")


@router.get("", response_model=SystemSettingsResponse)
async def get_settings():
    """Get current system settings."""
    provider = get_settings_provider()
    return await settings_to_response(provider)


@router.put("", response_model=SystemSettingsResponse)
async def update_settings(request: SystemSettingsRequest):
    """Update all system settings."""
    provider = get_settings_provider()

    settings = SystemSettings(
        system_enabled=request.system_enabled,
        business_hours=BusinessHours(
            start_time=request.business_hours.start_time,
            end_time=request.business_hours.end_time,
            enabled=request.business_hours.enabled,
            timezone=request.business_hours.timezone,
            days_of_week=request.business_hours.days_of_week,
            holidays=[
                HolidayEntry(
                    date=h.date,
                    name=h.name,
                    recurring=h.recurring,
                )
                for h in request.business_hours.holidays
            ],
        ),
        queue_thresholds=QueueThresholds(
            calls_waiting_threshold=request.queue_thresholds.calls_waiting_threshold,
            holdtime_threshold_seconds=request.queue_thresholds.holdtime_threshold_seconds,
            stable_polls_required=request.queue_thresholds.stable_polls_required,
        ),
        allow_live_calls=request.allow_live_calls,
        allowed_phones=request.allowed_phones,
        queue_source=request.queue_source,
        patient_source=request.patient_source,
    )

    await provider.update_settings(settings)
    return await settings_response_and_broadcast(provider)


@router.put("/system-enabled", response_model=SystemSettingsResponse)
async def set_system_enabled(request: SystemEnabledRequest):
    """Toggle system on/off."""
    from app.services.dispatcher import get_dispatcher
    from app.api.websocket import broadcast_to_dashboards

    provider = get_settings_provider()
    await provider.set_system_enabled(request.enabled)
    print(f"[SETTINGS] system_enabled → {request.enabled}")

    # Log to dispatcher events so the dashboard shows the state change in real time
    dispatcher = get_dispatcher()
    if request.enabled:
        decision_entry = dispatcher._log_decision("system_enabled", "System enabled — outbound calls will resume")
    else:
        decision_entry = dispatcher._log_decision("system_disabled", "System disabled — no new outbound calls will be placed")

    # Broadcast immediately so the UI event card updates without waiting for next tick
    await broadcast_to_dashboards({"type": "dispatcher_event", "decision": decision_entry})

    return await settings_response_and_broadcast(provider)


@router.put("/business-hours", response_model=SystemSettingsResponse)
async def update_business_hours(request: BusinessHoursRequest):
    """Update business hours settings."""
    provider = get_settings_provider()

    business_hours = BusinessHours(
        start_time=request.start_time,
        end_time=request.end_time,
        enabled=request.enabled,
        timezone=request.timezone,
        days_of_week=request.days_of_week,
        holidays=[
            HolidayEntry(
                date=h.date,
                name=h.name,
                recurring=h.recurring,
            )
            for h in request.holidays
        ],
    )

    await provider.update_business_hours(business_hours)
    return await settings_response_and_broadcast(provider)


@router.put("/queue-thresholds", response_model=SystemSettingsResponse)
async def update_queue_thresholds(request: QueueThresholdsRequest):
    """Update queue thresholds."""
    provider = get_settings_provider()

    thresholds = QueueThresholds(
        calls_waiting_threshold=request.calls_waiting_threshold,
        holdtime_threshold_seconds=request.holdtime_threshold_seconds,
        stable_polls_required=request.stable_polls_required,
    )

    await provider.update_queue_thresholds(thresholds)
    return await settings_response_and_broadcast(provider)


@router.put("/dispatcher", response_model=SystemSettingsResponse)
async def update_dispatcher_settings(request: DispatcherSettingsRequest):
    """Update dispatcher settings and apply immediately."""
    from app.services.dispatcher import get_dispatcher

    provider = get_settings_provider()

    dispatcher_settings = DispatcherSettings(
        poll_interval=request.poll_interval,
        dispatch_timeout=request.dispatch_timeout,
        max_attempts=request.max_attempts,
        min_hours_between=request.min_hours_between,
        cooldown_seconds=request.cooldown_seconds,
        verbose_logging=request.verbose_logging,
    )

    await provider.update_dispatcher_settings(dispatcher_settings)

    # Apply to running dispatcher immediately
    get_dispatcher().update_config(
        poll_interval=request.poll_interval,
        dispatch_timeout=request.dispatch_timeout,
        max_attempts=request.max_attempts,
        min_hours_between=request.min_hours_between,
        cooldown_seconds=request.cooldown_seconds,
        verbose_logging=request.verbose_logging,
    )

    return await settings_response_and_broadcast(provider)


@router.put("/dispatcher/cooldown", response_model=SystemSettingsResponse)
async def set_cooldown(request: CooldownRequest):
    """Set just the inter-call cooldown (seconds). Shortcut over
    /dispatcher which requires the full payload."""
    from app.services.dispatcher import get_dispatcher
    if request.cooldown_seconds < 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="cooldown_seconds must be >= 0")
    provider = get_settings_provider()
    current = await provider.get_settings()
    ds = current.dispatcher_settings
    merged = DispatcherSettings(
        poll_interval=ds.poll_interval,
        dispatch_timeout=ds.dispatch_timeout,
        max_attempts=ds.max_attempts,
        min_hours_between=ds.min_hours_between,
        cooldown_seconds=request.cooldown_seconds,
        verbose_logging=ds.verbose_logging,
    )
    await provider.update_dispatcher_settings(merged)
    get_dispatcher().update_config(
        poll_interval=merged.poll_interval,
        dispatch_timeout=merged.dispatch_timeout,
        max_attempts=merged.max_attempts,
        min_hours_between=merged.min_hours_between,
        cooldown_seconds=merged.cooldown_seconds,
        verbose_logging=merged.verbose_logging,
    )
    print(f"[SETTINGS] dispatcher cooldown_seconds → {request.cooldown_seconds}")
    return await settings_response_and_broadcast(provider)


@router.put("/dispatcher/batch-size", response_model=SystemSettingsResponse)
async def set_batch_size(request: BatchSizeRequest):
    """Set the default batch size for dispatcher batches."""
    from app.services.dispatcher import get_dispatcher
    if request.batch_size < 1:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="batch_size must be >= 1")
    provider = get_settings_provider()
    current = await provider.get_settings()
    ds = current.dispatcher_settings
    merged = DispatcherSettings(
        poll_interval=ds.poll_interval,
        dispatch_timeout=ds.dispatch_timeout,
        max_attempts=ds.max_attempts,
        min_hours_between=ds.min_hours_between,
        cooldown_seconds=ds.cooldown_seconds,
        default_batch_size=request.batch_size,
        verbose_logging=ds.verbose_logging,
    )
    await provider.update_dispatcher_settings(merged)
    print(f"[SETTINGS] dispatcher default_batch_size → {request.batch_size}")
    return await settings_response_and_broadcast(provider)


@router.put("/allow-live-calls", response_model=SystemSettingsResponse)
async def set_allow_live_calls(request: AllowLiveCallsRequest):
    """Toggle live Twilio calls on/off."""
    provider = get_settings_provider()
    await provider.set_allow_live_calls(request.allowed)
    return await settings_response_and_broadcast(provider)


@router.put("/allowed-phones", response_model=SystemSettingsResponse)
async def update_allowed_phones(request: AllowedPhonesRequest):
    """Update the phone number allowlist for live calls."""
    provider = get_settings_provider()
    await provider.update_allowed_phones(request.phones)
    return await settings_response_and_broadcast(provider)


@router.put("/queue-source", response_model=SystemSettingsResponse)
async def set_queue_source(request: SourceRequest):
    """Switch queue data source between simulation and live FreePBX.

    When switching TO 'simulation', auto-loads the active scenario.
    """
    from app.providers import set_queue_source as _set_queue_source
    from fastapi import HTTPException

    if request.source not in ("simulation", "live"):
        raise HTTPException(status_code=400, detail="source must be 'simulation' or 'live'")

    provider = get_settings_provider()
    current_settings = await provider.get_settings()
    was_simulation = current_settings.queue_source == "simulation"

    await provider.set_queue_source(request.source)
    _set_queue_source(request.source)
    print(f"[SETTINGS] queue_source: {current_settings.queue_source} → {request.source}")

    # When switching TO simulation, activate the scenario
    if request.source == "simulation" and not was_simulation:
        active_id = current_settings.active_scenario_id
        if active_id:
            try:
                await activate_scenario(active_id)
            except ValueError:
                pass  # Scenario not found, skip activation

    return await settings_response_and_broadcast(provider)


@router.put("/patient-source", response_model=SystemSettingsResponse)
async def set_patient_source(request: SourceRequest):
    """Switch patient data source between simulation and live RadFlow.

    When switching TO 'simulation', auto-loads the active scenario.
    """
    from app.providers import set_patient_source as _set_patient_source
    from fastapi import HTTPException

    if request.source not in ("simulation", "live"):
        raise HTTPException(status_code=400, detail="source must be 'simulation' or 'live'")

    provider = get_settings_provider()
    current_settings = await provider.get_settings()
    was_simulation = current_settings.patient_source == "simulation"

    await provider.set_patient_source(request.source)
    _set_patient_source(request.source)
    print(f"[SETTINGS] patient_source: {current_settings.patient_source} → {request.source}")

    # When switching TO simulation, activate the scenario
    if request.source == "simulation" and not was_simulation:
        active_id = current_settings.active_scenario_id
        if active_id:
            try:
                await activate_scenario(active_id)
            except ValueError:
                pass  # Scenario not found, skip activation

    return await settings_response_and_broadcast(provider)


@router.put("/active-scenario", response_model=SystemSettingsResponse)
async def set_active_scenario(request: ActiveScenarioRequest):
    """Set the active simulation scenario and apply it.

    This updates the active_scenario_id in settings and immediately
    activates the scenario (resets mock providers, restarts dispatcher).
    Call logs are preserved.
    """
    from fastapi import HTTPException

    provider = get_settings_provider()

    # Update the active scenario ID in settings
    await provider.set_active_scenario_id(request.scenario_id)

    # Activate the scenario (load into mock providers)
    try:
        await activate_scenario(request.scenario_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return await settings_response_and_broadcast(provider)


@router.put("/call-mode", response_model=SystemSettingsResponse)
async def set_call_mode(request: CallModeRequest):
    """Set the call mode (web or twilio)."""
    from fastapi import HTTPException

    if request.call_mode not in ("web", "twilio"):
        raise HTTPException(status_code=400, detail="call_mode must be 'web' or 'twilio'")

    provider = get_settings_provider()
    current_settings = await provider.get_settings()
    await provider.set_call_mode(request.call_mode)
    print(f"[SETTINGS] call_mode: {current_settings.call_mode} → {request.call_mode}")
    return await settings_response_and_broadcast(provider)


@router.put("/mock-mode", response_model=SystemSettingsResponse)
async def set_mock_mode(request: MockModeRequest):
    """Toggle mock mode and set the redirect phone number for Twilio calls/SMS."""
    provider = get_settings_provider()
    await provider.set_mock_mode(request.enabled, request.mock_phone)
    label = f"ON (redirect to {request.mock_phone})" if request.enabled else "OFF"
    print(f"[SETTINGS] mock_mode → {label}")
    return await settings_response_and_broadcast(provider)


@router.put("/ivr-navigate", response_model=SystemSettingsResponse)
async def set_ivr_navigate(request: IVRNavigateRequest):
    """Toggle automatic phone-tree navigation.

    When ON, the orchestrator hands control to the IVR navigator on IVR
    detection (LLM-driven DTMF presses to reach a human). When OFF, we
    keep the legacy 'hang up on first menu prompt' behavior.
    """
    provider = get_settings_provider()
    await provider.set_ivr_navigate_enabled(request.enabled)
    print(f"[SETTINGS] ivr_navigate_enabled → {request.enabled}")
    return await settings_response_and_broadcast(provider)


@router.put("/voice", response_model=SystemSettingsResponse)
async def set_voice_provider(request: VoiceProviderRequest):
    """Select the default realtime voice backend for subsequent calls.

    Overridden per-call by `CallOrchestrator.start_call(voice_provider=...)`
    (CLI --voice flag or API body). Body:
        {"provider": "openai"|"gemini", "model": "<model id or empty>"}
    """
    from fastapi import HTTPException
    provider = get_settings_provider()
    try:
        await provider.set_voice_provider(request.provider, request.model)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    print(f"[SETTINGS] voice_provider → {request.provider} model={request.model or '<default>'}")
    return await settings_response_and_broadcast(provider)


@router.put("/voice-config", response_model=SystemSettingsResponse)
async def set_voice_config(request: VoiceConfigRequest):
    """Merge-update per-provider voice knobs.

    Body (example for Gemini):
        {"provider":"gemini", "voice":"Aoede", "temperature":1.0,
         "affective_dialog":true, "proactive_audio":false}

    Only the fields you pass get changed. Omit a field to leave it as-is.
    `affective_dialog` and `proactive_audio` are Gemini-only.

    Which provider is actually USED per call is determined by
    `PUT /api/settings/voice` + any per-call override; this endpoint
    configures the knobs for each provider independently.
    """
    from fastapi import HTTPException
    patch = {}
    if request.voice is not None:
        patch["voice"] = request.voice
    if request.temperature is not None:
        patch["temperature"] = request.temperature
    if request.affective_dialog is not None:
        patch["affective_dialog"] = request.affective_dialog
    if request.proactive_audio is not None:
        patch["proactive_audio"] = request.proactive_audio
    if request.speed is not None:
        patch["speed"] = request.speed
    if request.top_p is not None:
        patch["top_p"] = request.top_p

    provider = get_settings_provider()
    try:
        await provider.update_voice_config(request.provider, patch)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    print(f"[SETTINGS] voice_config[{request.provider}] ← {patch}")
    return await settings_response_and_broadcast(provider)


@router.put("/daily-report", response_model=SystemSettingsResponse)
async def update_daily_report(request: DailyReportRequest):
    """Update the daily Slack report configuration."""
    from app.models import DailyReportConfig
    provider = get_settings_provider()
    config = DailyReportConfig(
        enabled=request.enabled,
        webhook_url=request.webhook_url.strip(),
        hour=request.hour,
        timezone=request.timezone,
    )
    await provider.update_daily_report(config)
    label = "ON" if request.enabled else "OFF"
    print(f"[SETTINGS] daily_report → {label} (hour={request.hour} tz={request.timezone})")
    return await settings_response_and_broadcast(provider)


@router.get("/timezones", response_model=List[str])
async def get_timezones():
    """Get list of available timezones."""
    return COMMON_TIMEZONES
