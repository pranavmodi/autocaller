import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from .api import dashboard_router, websocket_router, settings_router, dispatcher_router, scenarios_router
from .services.dispatcher import get_dispatcher
from .services.daily_report_service import daily_report_loop
from .providers import set_queue_source, set_patient_source
from .providers.settings_provider import get_settings_provider
from .db import AsyncSessionLocal, async_engine
from .db.seed import seed_default_settings, seed_builtin_scenarios, seed_sample_patients


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: seed DB defaults, then start the dispatcher
    async with AsyncSessionLocal() as session:
        await seed_default_settings(session)
        await seed_builtin_scenarios(session)
        await seed_sample_patients(session)
        await session.commit()
    # Apply persisted source settings
    settings = await get_settings_provider().get_settings()
    set_queue_source(settings.queue_source)
    set_patient_source(settings.patient_source)
    print(f"[STARTUP] patient_source={settings.patient_source}, queue_source={settings.queue_source}, call_mode={settings.call_mode}")
    # Apply persisted dispatcher settings before starting.
    # CLI flag (VERBOSE_LOGGING env var) overrides the DB setting.
    ds = settings.dispatcher_settings
    verbose_override = os.getenv("VERBOSE_LOGGING", "").lower() in ("1", "true", "yes")
    verbose = verbose_override or ds.verbose_logging
    get_dispatcher().update_config(
        poll_interval=ds.poll_interval,
        dispatch_timeout=ds.dispatch_timeout,
        max_attempts=ds.max_attempts,
        min_hours_between=ds.min_hours_between,
        verbose_logging=verbose,
    )
    # If sources are "simulation" and active_scenario_id is set, activate the scenario
    if (settings.queue_source == "simulation" or settings.patient_source == "simulation") and settings.active_scenario_id:
        from .api.settings import activate_scenario
        try:
            await activate_scenario(settings.active_scenario_id)
        except ValueError:
            pass  # Scenario not found, skip activation
    get_dispatcher().start()
    # Start the daily Slack report loop (no-op if disabled via env var)
    daily_report_task = asyncio.create_task(daily_report_loop())
    yield
    # Shutdown: stop the dispatcher, cancel background tasks, dispose engine
    get_dispatcher().stop()
    daily_report_task.cancel()
    try:
        await daily_report_task
    except (asyncio.CancelledError, Exception):
        pass
    await async_engine.dispose()


app = FastAPI(title="AI Outbound Voice Orchestrator", version="0.2.0", lifespan=lifespan)

# CORS middleware for frontend
# - Configure CORS_ORIGINS env var (comma-separated) to specify explicit origins
# - Optionally configure CORS_ORIGIN_REGEX to allow a regex (e.g., local LAN IPs)
_default_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors_origins = os.getenv("CORS_ORIGINS")
_origin_regex_env = os.getenv("CORS_ORIGIN_REGEX")
if _cors_origins:
    _allowed_origins = [o.strip() for o in _cors_origins.split(",") if o.strip()]
else:
    _allowed_origins = _default_origins
_default_origin_regex = r"https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?$"
_allow_origin_regex = _origin_regex_env.strip() if _origin_regex_env else _default_origin_regex

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_origin_regex=_allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(dashboard_router)
app.include_router(websocket_router)
app.include_router(settings_router)
app.include_router(dispatcher_router)
app.include_router(scenarios_router)

# Legacy static (kept for compatibility)
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Audio directory under app/
AUDIO_DIR = Path(__file__).resolve().parent / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"

