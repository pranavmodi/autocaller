"""Auto-call dispatcher service.

Runs a 10-second polling loop on the backend, evaluates all gating conditions,
and initiates calls directly (backend-driven). The frontend/dashboard is used
only for visibility and audio transport in web-call mode.
"""
import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.providers import (
    get_queue_provider,
    get_patient_provider,
    get_call_log_provider,
    get_settings_provider,
)

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL_SECONDS = 10
DEFAULT_DISPATCH_TIMEOUT_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MIN_HOURS_BETWEEN = 168  # 1 week — don't re-call the same firm within 7 days
DEFAULT_COOLDOWN_SECONDS = 120  # wait between consecutive calls to different patients
DECISION_LOG_MAX = 100


class DispatcherState(str, Enum):
    STOPPED = "stopped"
    IDLE = "idle"
    DISPATCHED = "dispatched"
    CALL_ACTIVE = "call_active"


class AutoCallDispatcher:
    """Backend dispatcher that decides WHEN and WHO to call,
    then sends dispatch_call commands to connected frontends."""

    def __init__(self):
        self._state: DispatcherState = DispatcherState.STOPPED
        self._task: Optional[asyncio.Task] = None
        self._dispatched_at: Optional[float] = None
        self._dispatched_patient_id: Optional[str] = None
        self._decision_log: deque = deque(maxlen=DECISION_LOG_MAX)
        self._last_call_ended_at: Optional[float] = None
        # Batch tracking — stop after N calls placed in a single run
        self._batch_target: Optional[int] = None
        self._batch_placed: int = 0
        self._batch_started_at: Optional[datetime] = None
        # Configurable parameters
        self.poll_interval: int = DEFAULT_POLL_INTERVAL_SECONDS
        self.dispatch_timeout: int = DEFAULT_DISPATCH_TIMEOUT_SECONDS
        self.max_attempts: int = DEFAULT_MAX_ATTEMPTS
        self.min_hours_between: int = DEFAULT_MIN_HOURS_BETWEEN
        self.cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
        self.verbose: bool = False

    @property
    def state(self) -> DispatcherState:
        return self._state

    def start(self, target_calls: Optional[int] = None):
        """Start the dispatcher polling loop.

        If `target_calls` is set, the dispatcher auto-stops after that many
        calls have been placed in this run (useful for batch-testing).
        Pass None for unlimited (default behavior).
        """
        if self._task and not self._task.done():
            return
        # Reset batch counter on every start so each run is a fresh batch.
        self._batch_target = int(target_calls) if target_calls else None
        self._batch_placed = 0
        self._batch_started_at = datetime.now(timezone.utc)
        self._state = DispatcherState.IDLE
        self._task = asyncio.create_task(self._run_loop())
        label = f"batch of {self._batch_target}" if self._batch_target else "unlimited"
        logger.info("Dispatcher started (%s)", label)
        self._log_decision("started", f"Dispatcher started ({label})")

    def stop(self):
        """Stop the dispatcher polling loop."""
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._state = DispatcherState.STOPPED
        self._dispatched_at = None
        self._dispatched_patient_id = None
        logger.info("Dispatcher stopped")
        self._log_decision(
            "stopped",
            f"Dispatcher stopped ({self._batch_placed}/{self._batch_target} placed)"
            if self._batch_target
            else "Dispatcher stopped",
        )

    def update_config(self, poll_interval: int, dispatch_timeout: int,
                       max_attempts: int, min_hours_between: int,
                       verbose_logging: bool = False,
                       cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS):
        """Update dispatcher configuration."""
        self.poll_interval = poll_interval
        self.dispatch_timeout = dispatch_timeout
        self.max_attempts = max_attempts
        self.min_hours_between = min_hours_between
        self.cooldown_seconds = cooldown_seconds
        self.verbose = verbose_logging
        self._log_decision("config_updated",
                           f"Config updated: poll={poll_interval}s, timeout={dispatch_timeout}s, "
                           f"max_attempts={max_attempts}, min_hours={min_hours_between}, "
                           f"cooldown={cooldown_seconds}s, verbose={verbose_logging}")

    def restart(self):
        """Restart the dispatcher (stop + start)."""
        self.stop()
        self.start()

    def _verbose_log(self, msg: str):
        """Print a message only when verbose logging is enabled."""
        if self.verbose:
            print(f"[Dispatcher] {msg}")

    async def _run_loop(self):
        """Main polling loop — runs every poll_interval seconds."""
        try:
            while True:
                self._verbose_log(f"Tick start — state={self._state.value}")
                await self._tick()
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            logger.info("Dispatcher loop cancelled")
        except Exception as e:
            logger.exception(f"Dispatcher loop error: {e}")
            self._state = DispatcherState.STOPPED

    async def _tick(self):
        """Single poll cycle: update queue, broadcast state, evaluate conditions."""
        from app.api.websocket import dashboard_clients, voice_clients, broadcast_to_dashboards
        from app.services.call_orchestrator import get_orchestrator

        # 1. Poll queue state
        queue_provider = get_queue_provider()
        queue_state = await queue_provider.poll()

        self._verbose_log(f"Queue poll: ami={queue_state.ami_connected}, outbound_ok={queue_state.outbound_allowed}, agents={queue_state.global_agents_available}")

        # Track the decision made this tick (broadcast at end)
        tick_decision = None

        # 3. If DISPATCHED, either start call when prerequisites are met, or check timeout
        if self._state == DispatcherState.DISPATCHED:
            if self._dispatched_at is not None:
                elapsed = asyncio.get_event_loop().time() - self._dispatched_at
                if elapsed > self.dispatch_timeout:
                    tick_decision = self._log_decision(
                        "dispatch_timeout",
                        f"Dispatch timed out after {self.dispatch_timeout}s "
                        f"for patient {self._dispatched_patient_id}")
                    self._state = DispatcherState.IDLE
                    self._dispatched_at = None
                    self._dispatched_patient_id = None
                else:
                    # If we're in web mode and a voice client has connected, start the call now
                    settings_provider = get_settings_provider()
                    settings = await settings_provider.get_settings()
                    call_mode = settings.call_mode or "web"
                    self._verbose_log(f"DISPATCHED tick: call_mode={call_mode}, voice_clients={len(voice_clients)}, patient={self._dispatched_patient_id}")
                    if call_mode == "web" and voice_clients and self._dispatched_patient_id:
                        orchestrator = get_orchestrator()
                        call = await orchestrator.start_call(self._dispatched_patient_id, call_mode=call_mode)
                        if call:
                            self.notify_call_started(self._dispatched_patient_id)
                            await broadcast_to_dashboards({
                                "type": "call_started",
                                "call": call.to_dict(),
                            })
                            tick_decision = self._log_decision(
                                "call_starting",
                                f"Voice client connected; starting call for patient {self._dispatched_patient_id}")
                        else:
                            # Failed to start; reset state
                            self._state = DispatcherState.IDLE
                            self._dispatched_at = None
                            self._dispatched_patient_id = None
                            tick_decision = self._log_decision(
                                "start_failed",
                                "Failed to start call after voice client connected")
                    else:
                        tick_decision = {"decision": "waiting", "detail": "Waiting for voice client or prerequisites", "state": self._state.value}

        # 4. If CALL_ACTIVE, verify the call is still running
        elif self._state == DispatcherState.CALL_ACTIVE:
            call_log_provider = get_call_log_provider()
            if not call_log_provider.has_active_call():
                # Call ended but notify_call_ended was missed — self-heal
                print("[Dispatcher] Self-heal: no active call found while in CALL_ACTIVE, resetting to IDLE")
                self._state = DispatcherState.IDLE
                self._dispatched_at = None
                self._dispatched_patient_id = None
                tick_decision = self._log_decision("self_healed", "Call ended (missed notification), returning to idle")
                # Broadcast so the frontend refreshes call history
                await broadcast_to_dashboards({"type": "call_ended", "call": {}})
            else:
                tick_decision = {"decision": "call_active", "detail": "Call in progress, skipping", "state": self._state.value}

        # 5. If not IDLE, skip
        elif self._state != DispatcherState.IDLE:
            pass

        else:
            # 6. Evaluate all gating conditions.
            # Batch target: if hit, stop the dispatcher cleanly before doing anything else.
            if self._batch_exhausted():
                tick_decision = self._log_decision(
                    "batch_complete",
                    f"Target reached ({self._batch_placed}/{self._batch_target}), stopping dispatcher",
                )
                # Defer the stop so we finish broadcasting this tick first.
                asyncio.get_event_loop().call_soon(self.stop)
                # Broadcast queue_update + decision, then return.
                await broadcast_to_dashboards({
                    "type": "queue_update",
                    "queue_state": queue_state.to_dict(),
                    "decision": tick_decision,
                })
                return

            settings_provider = get_settings_provider()
            settings = await settings_provider.get_settings()
            call_log_provider = get_call_log_provider()

            self._verbose_log(
                f"Sources: queue={settings.queue_source}, patients={settings.patient_source}, "
                f"call_mode={settings.call_mode}, scenario={settings.active_scenario_id or 'none'}"
            )

            # system_enabled
            if not settings.system_enabled:
                tick_decision = self._log_decision("blocked", "System is disabled")

            # is_within_business_hours (operator-wide window)
            elif (business_hours_reason := await settings_provider.get_business_hours_block_reason()):
                tick_decision = self._log_decision("blocked", business_hours_reason)

            # has_active_call
            elif call_log_provider.has_active_call():
                tick_decision = self._log_decision("blocked", "Call already in progress")

            # cooldown between consecutive calls
            elif self._last_call_ended_at is not None:
                elapsed = asyncio.get_event_loop().time() - self._last_call_ended_at
                remaining = self.cooldown_seconds - elapsed
                if remaining > 0:
                    tick_decision = self._log_decision(
                        "blocked", f"Cooldown between calls ({int(remaining)}s remaining)")
                else:
                    self._last_call_ended_at = None  # cooldown expired, clear it

            if tick_decision is None:
                # All gating conditions passed
                self._verbose_log("All gates passed — looking for candidate patient")

                # 7. Get next candidate patient
                patient_provider = get_patient_provider()
                settings_provider = get_settings_provider()
                settings = await settings_provider.get_settings()

                # Autocaller: skip the language-queue filter. Pick the
                # highest-priority eligible lead whose local state-level
                # calling window is open right now.
                from app.prompts.attorney_cold_call import _default_timezone_for_state
                from datetime import datetime
                try:
                    from zoneinfo import ZoneInfo
                except ImportError:  # Python <3.9 fallback — not expected here
                    ZoneInfo = None  # type: ignore

                psh = getattr(settings, "per_state_hours", None)
                start_hhmm = getattr(psh, "start", "09:00") if psh else "09:00"
                end_hhmm = getattr(psh, "end", "17:00") if psh else "17:00"
                allowed_days = set(getattr(psh, "days", [0, 1, 2, 3, 4]) if psh else [0, 1, 2, 3, 4])

                def _within_state_window(prospect) -> bool:
                    state = prospect.state
                    tz_name = _default_timezone_for_state(state)
                    if ZoneInfo is None or not tz_name:
                        return True  # best-effort: don't block on TZ errors
                    try:
                        local_now = datetime.now(ZoneInfo(tz_name))
                    except Exception:
                        return True
                    if local_now.weekday() not in allowed_days:
                        return False
                    try:
                        sh, sm = [int(x) for x in start_hhmm.split(":")]
                        eh, em = [int(x) for x in end_hhmm.split(":")]
                    except ValueError:
                        return True
                    minutes_now = local_now.hour * 60 + local_now.minute
                    return sh * 60 + sm <= minutes_now < eh * 60 + em

                candidate = None
                queue = await patient_provider.get_outbound_queue(
                    max_attempts=self.max_attempts,
                    min_hours_between=self.min_hours_between)
                for prospect in queue:
                    if _within_state_window(prospect):
                        candidate = prospect
                        break
                    self._verbose_log(
                        f"Skipping {prospect.name} — outside calling window "
                        f"for state {prospect.state or '?'}"
                    )

                if candidate is None:
                    self._verbose_log("No eligible candidate found")
                    tick_decision = self._log_decision("no_candidate", "No eligible patients in queue")

                else:
                    call_mode = settings.call_mode or "web"
                    print(f"[Dispatcher] Candidate found: {candidate.name} ({candidate.phone}), mode={call_mode}")

                    # In web mode, if no voice client is connected, pre-dispatch to trigger the frontend to connect voice
                    if call_mode == "web" and not voice_clients:
                        print(f"[Dispatcher] State transition: IDLE → DISPATCHED (waiting for voice client)")
                        self._state = DispatcherState.DISPATCHED
                        self._dispatched_at = asyncio.get_event_loop().time()
                        self._dispatched_patient_id = candidate.patient_id
                        tick_decision = self._log_decision(
                            "waiting_for_voice_client",
                            f"Ready to call {candidate.name}; requesting voice client to connect")
                        await broadcast_to_dashboards({
                            "type": "dispatch_call",
                            "patient_id": candidate.patient_id,
                            "patient_name": candidate.name,
                        })
                    else:
                        # 9. Start call directly (backend-driven)
                        print(f"[Dispatcher] State transition: IDLE → DISPATCHED (starting call)")
                        self._state = DispatcherState.DISPATCHED
                        self._dispatched_at = asyncio.get_event_loop().time()
                        self._dispatched_patient_id = candidate.patient_id

                        tick_decision = self._log_decision(
                            "starting_call",
                            f"Starting call to {candidate.name} ({candidate.phone}, mode={call_mode})")

                        orchestrator = get_orchestrator()

                        # Wire up orchestrator callbacks so call_ended and
                        # status updates reach dashboards even without a
                        # voice-WS client (i.e. Twilio-driven calls).
                        if not orchestrator.on_call_ended:
                            async def _dispatcher_on_call_ended(call):
                                self.notify_call_ended()
                                await broadcast_to_dashboards({
                                    "type": "call_ended",
                                    "call": call.to_dict(),
                                })

                            orchestrator.on_call_ended = _dispatcher_on_call_ended

                        if not orchestrator.on_status_update:
                            async def _dispatcher_on_status(status):
                                await broadcast_to_dashboards({
                                    "type": "status_update",
                                    "status": status,
                                })

                            orchestrator.on_status_update = _dispatcher_on_status

                        if not orchestrator.on_transcript_update:
                            async def _dispatcher_on_transcript(speaker, text):
                                if speaker in ("ai", "patient"):
                                    await broadcast_to_dashboards({
                                        "type": "transcript",
                                        "speaker": speaker,
                                        "text": text,
                                    })

                            orchestrator.on_transcript_update = _dispatcher_on_transcript

                        call = await orchestrator.start_call(candidate.patient_id, call_mode=call_mode)

                        if call is None:
                            # Failed to start; reset state and start cooldown so we
                            # don't hammer the same patient on the next tick.
                            self._state = DispatcherState.IDLE
                            self._dispatched_at = None
                            self._dispatched_patient_id = None
                            self._last_call_ended_at = asyncio.get_event_loop().time()
                            error_reason = getattr(orchestrator, "_last_start_error", None) or "unknown reason"
                            tick_decision = self._log_decision(
                                "start_failed",
                                f"Failed to start call to {candidate.name}: {error_reason} (cooldown {self.cooldown_seconds}s)")
                        else:
                            # Mark active immediately; voice/ws callbacks will also keep state in sync
                            self.notify_call_started(candidate.patient_id)
                            await broadcast_to_dashboards({
                                "type": "call_started",
                                "call": call.to_dict(),
                            })

        # 2. Broadcast queue_update + decision to all dashboards
        await broadcast_to_dashboards({
            "type": "queue_update",
            "queue_state": queue_state.to_dict(),
            "decision": tick_decision,
        })

    def _batch_exhausted(self) -> bool:
        """True iff we've placed the configured number of calls in this run."""
        return self._batch_target is not None and self._batch_placed >= self._batch_target

    def notify_call_started(self, patient_id: str):
        """Transition DISPATCHED → CALL_ACTIVE when the frontend starts the call."""
        # Count every placed call against the batch target, regardless of
        # whether it was dispatched or manually fired.
        self._batch_placed += 1
        if self._state == DispatcherState.DISPATCHED:
            print(f"[Dispatcher] State transition: DISPATCHED → CALL_ACTIVE (patient={patient_id}) [{self._batch_placed}/{self._batch_target or '∞'}]")
            self._state = DispatcherState.CALL_ACTIVE
            self._dispatched_at = None
            self._log_decision("call_started",
                               f"Call started for patient {patient_id}")
        elif self._state == DispatcherState.IDLE:
            # Manual call started outside dispatcher
            print(f"[Dispatcher] State transition: IDLE → CALL_ACTIVE (manual call, patient={patient_id})")
            self._state = DispatcherState.CALL_ACTIVE
            self._log_decision("call_started",
                               f"Manual call started for patient {patient_id}")

    def notify_call_ended(self):
        """Transition CALL_ACTIVE → IDLE when the call ends."""
        if self._state in (DispatcherState.CALL_ACTIVE, DispatcherState.DISPATCHED):
            print(f"[Dispatcher] State transition: {self._state.value} → IDLE (call ended)")
            self._state = DispatcherState.IDLE
            self._dispatched_at = None
            self._dispatched_patient_id = None
            self._last_call_ended_at = asyncio.get_event_loop().time()
            self._log_decision("call_ended", f"Call ended, cooldown {self.cooldown_seconds}s before next call")

    def _log_decision(self, decision: str, detail: str) -> dict:
        """Append to the circular decision buffer, persist to DB, and return the entry."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "detail": detail,
            "state": self._state.value,
        }
        self._decision_log.append(entry)
        print(f"[Dispatcher] {decision}: {detail}")

        # Fire-and-forget DB persistence
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                from app.services import safe_create_task
                safe_create_task(
                    self._persist_event(decision, detail),
                    logger,
                    f"dispatcher_persist_event decision={decision}",
                )
        except RuntimeError:
            pass

        return entry

    async def _persist_event(self, decision: str, detail: str):
        """Persist a dispatcher event to the database."""
        try:
            from app.db import AsyncSessionLocal
            from app.db.models import DispatcherEventRow

            async with AsyncSessionLocal() as session:
                row = DispatcherEventRow(
                    decision=decision,
                    detail=detail,
                    state=self._state.value,
                )
                session.add(row)
                await session.commit()
        except Exception as e:
            logger.warning("Failed to persist dispatcher event: %s", e)

    def get_status(self) -> dict:
        """Return current dispatcher status for API."""
        return {
            "state": self._state.value,
            "dispatched_patient_id": self._dispatched_patient_id,
            "running": self._task is not None and not self._task.done(),
            "recent_decisions": list(self._decision_log)[-5:],
            "batch": {
                "target": self._batch_target,
                "placed": self._batch_placed,
                "started_at": self._batch_started_at.isoformat() if self._batch_started_at else None,
                "remaining": (self._batch_target - self._batch_placed) if self._batch_target is not None else None,
            },
            "config": {
                "poll_interval": self.poll_interval,
                "dispatch_timeout": self.dispatch_timeout,
                "max_attempts": self.max_attempts,
                "min_hours_between": self.min_hours_between,
                "cooldown_seconds": self.cooldown_seconds,
            },
        }

    def get_decision_log(self) -> list:
        """Return full decision log for debugging."""
        return list(self._decision_log)


# Singleton
_dispatcher: Optional[AutoCallDispatcher] = None


def get_dispatcher() -> AutoCallDispatcher:
    """Get the global dispatcher instance."""
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = AutoCallDispatcher()
    return _dispatcher
