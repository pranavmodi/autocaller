import asyncio
import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from .api import dashboard_router, websocket_router, settings_router, dispatcher_router, scenarios_router
from .api.auth import router as auth_router, SESSION_COOKIE, verify_session_token, auth_configured
from .services.dispatcher import get_dispatcher
from .services.daily_report_service import daily_report_loop
from .services.judge import judge_loop
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
        cooldown_seconds=ds.cooldown_seconds,
        verbose_logging=verbose,
    )
    # If sources are "simulation" and active_scenario_id is set, activate the scenario
    if (settings.queue_source == "simulation" or settings.patient_source == "simulation") and settings.active_scenario_id:
        from .api.settings import activate_scenario
        try:
            await activate_scenario(settings.active_scenario_id)
        except ValueError:
            pass  # Scenario not found, skip activation
    # Intentionally do NOT auto-start the dispatcher on boot.
    # A daemon restart must never trigger outbound cold calls without
    # explicit operator action. Start via the Now-page toggle or
    # POST /api/dispatcher/toggle or /api/dispatcher/start-batch.
    logger.info("Dispatcher NOT auto-started on boot — operator must trigger explicitly")
    # Start the daily Slack report loop (no-op if disabled via env var)
    daily_report_task = asyncio.create_task(daily_report_loop())
    # Start the background judge — every 60s, score unjudged ended calls
    judge_task = asyncio.create_task(judge_loop(interval_seconds=60))
    yield
    # Shutdown: stop the dispatcher, cancel background tasks, dispose engine
    get_dispatcher().stop()
    for t in (daily_report_task, judge_task):
        t.cancel()
        try:
            await t
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


# Password auth middleware. Enforced only when AUTH_PASSWORD +
# AUTH_SESSION_SECRET are both set. Exempt paths: /api/auth/* (login),
# /api/twilio/* (Twilio webhooks — validated separately by signature),
# /ws/twilio/* (Twilio media stream — same reason), /health, /static,
# /audio, and loopback-origin traffic (the CLI hits 127.0.0.1 directly).
_AUTH_EXEMPT_PREFIXES = (
    "/api/auth/",
    "/api/twilio/",   # inbound Twilio webhooks
    "/ws/twilio/",    # Twilio media-stream websocket
    "/health",
    "/static/",
    "/audio/",
)

class _AuthMiddleware:
    """Cookie-gated access to /api/* and /ws/dashboard.

    ASGI middleware (rather than BaseHTTPMiddleware) so we can gate
    WebSocket upgrades — those don't go through the HTTP base class.
    """

    def __init__(self, app_):
        self._app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self._app(scope, receive, send)
        if not auth_configured():
            return await self._app(scope, receive, send)

        path = scope.get("path", "")
        # Allow the health probe, auth routes, Twilio webhooks, static.
        if any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
            return await self._app(scope, receive, send)
        # Only gate /api/* and /ws/* — everything else Next.js serves.
        if not (path.startswith("/api/") or path.startswith("/ws/")):
            return await self._app(scope, receive, send)

        # Loopback bypass for CLI and local tooling.
        client = scope.get("client") or ()
        client_host = client[0] if client else ""
        if client_host in ("127.0.0.1", "::1", "localhost", ""):
            return await self._app(scope, receive, send)

        # Extract cookie and verify the session token.
        cookies_header = ""
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                cookies_header = v.decode("latin-1", errors="replace")
                break
        session_value = ""
        for part in cookies_header.split(";"):
            part = part.strip()
            if part.startswith(f"{SESSION_COOKIE}="):
                session_value = part[len(SESSION_COOKIE) + 1:]
                break
        if verify_session_token(session_value):
            return await self._app(scope, receive, send)

        # Reject.
        if scope["type"] == "http":
            import json as _json
            body = _json.dumps({"detail": "Unauthorized"}).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
        else:
            # WebSocket — close with 1008 Policy Violation.
            await send({"type": "websocket.close", "code": 1008})


app.add_middleware(_AuthMiddleware)

# Include API routers
app.include_router(auth_router)
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

