"""Call orchestrator service managing the call lifecycle."""
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional, Callable, Any

from app.models import CallLog, CallOutcome, Patient
from app.providers import get_queue_provider, get_patient_provider, get_call_log_provider, get_settings_provider
from app.services.voice import (
    RealtimeVoiceBackend,
    get_voice_backend,
    BACKEND_OPENAI,
    BACKEND_GEMINI,
)
from app.services.voice.factory import resolve_default_provider
from app.services.notification_service import CallNotificationService
from app.services.carrier_failure_service import CarrierFailureHandler
from app.services.transfer_service import (
    TransferService,
    normalize_language_code,
    looks_like_voicemail_signal,
)
from app.services.twilio_sms_service import get_callback_number

logger = logging.getLogger(__name__)


class CallOrchestrator:
    """Orchestrates outbound calls with OpenAI Realtime voice."""

    def __init__(self):
        self._voice_service: Optional[RealtimeVoiceBackend] = None
        self._current_call: Optional[CallLog] = None
        self._current_patient: Optional[Patient] = None
        self._twilio_bridge = None  # TwilioMediaBridge when in twilio mode
        self._call_mode: str = "web"  # "web" or "twilio"
        self._mock_mode: bool = False
        self._mock_phone: str = ""
        self._twilio_call_sid: Optional[str] = None
        self._voicemail_handled: bool = False
        self._web_voicemail_simulated: bool = False
        self._ending_call: bool = False  # prevents re-entrant end_call from race conditions
        self._transfer_in_progress: bool = False  # set during SIP transfer to prevent DISCONNECTED override
        self._last_start_error: Optional[str] = None  # last error from failed start_call, for dispatcher visibility
        self._verbose: bool = False
        # IVR navigation state for the current call.
        self._ivr_navigate_enabled: bool = False
        self._ivr_navigating: bool = False
        self._ivr_handled: bool = False
        # Wall-clock of the first caller-side transcript entry. Used to gate
        # IVR-detection actions to an early window that is measured from
        # when the caller actually SPEAKS — not from Twilio dial time, which
        # also counts ringing (15-25s) before anyone picks up.
        self._first_caller_audio_at: Optional[float] = None
        # Hold-state tracking. When the AI says "I'll hold" / "I'm holding",
        # we mute outbound audio to Twilio until the caller speaks again.
        # Gemini's server-VAD treats long silences as "your turn" and
        # auto-generates filler ("Thanks. Bye. Thanks.") that the receptionist
        # hears when she comes back. Heard on the Aaron Boudaie call
        # (43fdb418) — whisper transcript of the real audio caught the loop.
        self._on_hold: bool = False
        # Silence timeout: if no caller transcript arrives within N seconds
        # of the conversation starting, auto-end the call. Catches voicemails
        # and hold-music that Gemini doesn't transcribe.
        self._silence_timeout_task: Optional[asyncio.Task] = None
        self._caller_has_spoken: bool = False
        self._caller_turn_count: int = 0
        # Web-call recording: accumulate both directions as raw PCM16 chunks,
        # then save as WAV on end_call. Only active when call_mode="web".
        self._web_recording_chunks: list[bytes] = []
        self._web_recording_active: bool = False

        # Callbacks for UI updates
        self.on_call_started: Optional[Callable[[CallLog], Any]] = None
        self.on_call_ended: Optional[Callable[[CallLog], Any]] = None
        self.on_transcript_update: Optional[Callable[[str, str], Any]] = None
        self.on_audio_output: Optional[Callable[[bytes], Any]] = None
        self.on_status_update: Optional[Callable[[str], Any]] = None
        self.on_error: Optional[Callable[[str], Any]] = None

        # Delegate services
        self._notifications = CallNotificationService()
        self._transfer = TransferService()
        self._carrier_failure = CarrierFailureHandler(
            get_current_call=lambda: self._current_call,
            get_current_patient=lambda: self._current_patient,
            get_twilio_call_sid=lambda: self._twilio_call_sid,
            end_call_fn=self.end_call,
        )

    def _sync_status_callback(self):
        """Propagate on_status_update to delegate services."""
        self._notifications.on_status_update = self.on_status_update
        self._transfer.on_status_update = self.on_status_update
        self._carrier_failure.on_status_update = self.on_status_update
        self._carrier_failure.verbose = self._verbose

    async def handle_twilio_amd_status(self, call_sid: str, answered_by: str):
        """Handle Twilio AMD callback values (machine/human)."""
        if not self._current_call or not call_sid or call_sid != self._twilio_call_sid:
            return
        if self._voicemail_handled:
            return

        normalized = (answered_by or "").strip().lower()
        if not normalized:
            return

        if normalized.startswith("human"):
            if self.on_status_update:
                await self.on_status_update("Twilio AMD: human detected")
            return

        if normalized.startswith("machine"):
            self._voicemail_handled = True
            call = self._current_call
            call_log_provider = get_call_log_provider()
            await call_log_provider.update_call(call.call_id, voicemail_left=True)
            call.voicemail_left = True
            if self.on_status_update:
                await self.on_status_update(f"Twilio AMD: voicemail detected ({answered_by})")

            callback_number = get_callback_number().strip()
            rep_name = os.getenv("SALES_REP_NAME", "").strip() or "our team"
            rep_company = os.getenv("SALES_REP_COMPANY", "").strip() or "our team"
            contact = f" Give us a call back at {callback_number}." if callback_number else ""
            message = (
                f"Hi, this is {rep_name} from {rep_company}. We help personal injury firms with "
                f"custom software and AI tooling. I was hoping to catch you for a quick chat.{contact} "
                "Thanks, and have a good day."
            )

            try:
                from app.services.twilio_voice_service import play_voicemail_and_hangup
                await asyncio.to_thread(play_voicemail_and_hangup, call_sid, message)
            except Exception as e:
                logger.warning("Failed to play voicemail for call %s: %s", call.call_id, e)
                if self.on_status_update:
                    await self.on_status_update(f"Voicemail playback failed: {str(e)}")

            await self.end_call(CallOutcome.VOICEMAIL)

    async def handle_twilio_call_status(
        self,
        call_sid: str,
        call_status: str,
        error_code_raw: str = "",
        sip_response_code_raw: str = "",
    ):
        """Delegate to CarrierFailureHandler."""
        self._sync_status_callback()
        await self._carrier_failure.handle_twilio_call_status(
            call_sid, call_status, error_code_raw, sip_response_code_raw,
        )

    async def start_call(
        self,
        patient_id: str,
        call_mode: str = "web",
        voice_provider: Optional[str] = None,
        carrier: Optional[str] = None,
    ) -> Optional[CallLog]:
        """Start an outbound call to a patient.

        `voice_provider` overrides the default realtime backend for this
        call only (highest precedence). If None, we fall back to the DB
        setting, then the `VOICE_PROVIDER` env var, then 'openai'.

        `carrier` overrides the default telephony carrier ("twilio" or
        "telnyx") for this call only. If None, we fall back to the DB
        `default_carrier` setting, then `DEFAULT_CARRIER` env, then "twilio".
        """
        self._last_start_error = None
        call_log_provider = get_call_log_provider()
        if call_log_provider.has_active_call():
            self._last_start_error = "A call is already in progress"
            if self.on_error:
                await self.on_error(self._last_start_error)
            return None

        patient_provider = get_patient_provider()
        patient = await patient_provider.get_patient(patient_id)

        if not patient:
            if self.on_error:
                await self.on_error(f"Patient {patient_id} not found")
            return None

        queue_provider = get_queue_provider()
        queue_state = queue_provider.get_state()

        # Read settings upfront so we can stamp mock_mode on the call log entry
        settings_provider = get_settings_provider()
        settings = await settings_provider.get_settings()

        # Render the system prompt + resolve tools BEFORE creating the call
        # log so we can store both on the row for post-hoc debugging.
        from app.prompts.attorney_cold_call import (
            render_system_prompt,
            prompt_language_for,
            TOOLS as AUTOCALLER_TOOLS,
            PROMPT_VERSION,
        )
        sales = getattr(settings, "sales_context", None)

        def _sales_or_env(attr: str, env: str, default: str = "") -> str:
            val = getattr(sales, attr, "") if sales is not None else ""
            return val or os.getenv(env, default)

        prompt_lang = prompt_language_for(patient)
        system_prompt = render_system_prompt(
            lead=patient,
            rep_name=_sales_or_env("rep_name", "SALES_REP_NAME", "Alex"),
            rep_company=_sales_or_env("rep_company", "SALES_REP_COMPANY", "our team"),
            product_context=_sales_or_env("product_context", "PRODUCT_CONTEXT", ""),
            language=prompt_lang,
        )
        prompt_version_tagged = f"{PROMPT_VERSION}-{prompt_lang}"

        # Resolve which voice backend this call will use.
        # precedence: per-call arg > DB setting > env > 'openai'.
        resolved_provider = (
            (voice_provider or "").strip().lower()
            or (getattr(settings, "voice_provider", "") or "").strip().lower()
            or resolve_default_provider()
        )
        if resolved_provider not in (BACKEND_OPENAI, BACKEND_GEMINI):
            self._last_start_error = f"Unknown voice_provider: {resolved_provider!r}"
            if self.on_error:
                await self.on_error(self._last_start_error)
            return None
        # If the DB setting is set explicitly, honor its custom model; else
        # let the backend pick its own default from its env var.
        resolved_model = (getattr(settings, "voice_model", "") or "").strip() or None

        # Resolve telephony carrier (same precedence as voice backend).
        from app.services.carrier import get_carrier, resolve_carrier_name
        resolved_carrier_name = resolve_carrier_name(
            per_call=carrier,
            db_default=getattr(settings, "default_carrier", None),
            env_default=os.getenv("DEFAULT_CARRIER", ""),
        )
        carrier_adapter = get_carrier(resolved_carrier_name)

        call = await call_log_provider.create_call(
            patient_id=patient.patient_id,
            patient_name=patient.name,
            phone=patient.phone,
            order_id=patient.order_id,
            priority_bucket=patient.priority_bucket,
            queue_snapshot=queue_state.to_dict(),
            mock_mode=bool(settings.mock_mode),
            firm_name=getattr(patient, "firm_name", None),
            lead_state=getattr(patient, "state", None),
            prompt_text=system_prompt,
            prompt_version=prompt_version_tagged,
            tools_snapshot=list(AUTOCALLER_TOOLS),
            voice_provider=resolved_provider,
            voice_model=resolved_model or "",
            carrier=resolved_carrier_name if call_mode == "twilio" else None,
            call_mode=call_mode,
        )

        self._current_call = call
        self._current_patient = patient
        self._call_mode = call_mode
        self._web_voicemail_simulated = False
        self._verbose = settings.dispatcher_settings.verbose_logging
        # Decide whether this call is allowed to navigate phone trees.
        self._ivr_navigate_enabled = bool(getattr(settings, "ivr_navigate_enabled", False))
        self._ivr_navigating = False
        self._ivr_handled = False
        self._first_caller_audio_at = None
        self._on_hold = False

        mode_label = "Twilio" if call_mode == "twilio" else "Web"
        print(f"[CallOrchestrator] Starting call to {patient.name} ({patient.phone}) in {mode_label} mode")

        if self.on_status_update:
            await self.on_status_update(f"Connecting ({mode_label})...")

        audio_format = "g711_ulaw" if call_mode == "twilio" else "pcm16"

        self._voice_service = get_voice_backend(
            resolved_provider,
            audio_format=audio_format,
            verbose=self._verbose,
            model=resolved_model,
        )
        self._voice_service.on_transcript = self._handle_transcript
        self._voice_service.on_audio = self._handle_audio
        self._voice_service.on_function_call = self._handle_function_call
        self._voice_service.on_error = self._handle_voice_error
        self._voice_service.on_session_ended = self._handle_session_ended

        # Persist the actual model the backend chose (may differ from the
        # DB setting when that was empty — e.g. backend default from env).
        try:
            await call_log_provider.update_call(
                call.call_id,
                voice_model=self._voice_service.model,
            )
        except Exception:
            pass

        if self._verbose:
            print(f"[CallOrchestrator] Connecting voice backend "
                  f"provider={resolved_provider} model={self._voice_service.model} "
                  f"for call {call.call_id}...")

        # system_prompt + AUTOCALLER_TOOLS were rendered above (before
        # create_call) so they could be persisted on the call_log row.
        success = await self._voice_service.connect(
            call.call_id,
            patient.name,
            normalize_language_code(patient.language),
            system_prompt=system_prompt,
            tools=AUTOCALLER_TOOLS,
        )
        if not success:
            print(
                f"[CallOrchestrator] {resolved_provider} voice connection FAILED "
                f"for call {call.call_id}"
            )
            self._last_start_error = f"Failed to connect to {resolved_provider} voice backend"
            await call_log_provider.update_call(
                call.call_id,
                error_code=f"{resolved_provider}_connect_failed",
                error_message=self._last_start_error,
            )
            await call_log_provider.end_call(call.call_id, CallOutcome.FAILED)
            # Pre-dial failure — the lead's phone never rang. Do NOT burn the
            # retry window; let the dispatcher pick this lead up again.
            self._voice_service = None
            self._current_call = None
            self._current_patient = None
            return None
        if self._verbose:
            print(f"[CallOrchestrator] voice backend {resolved_provider} connected for call {call.call_id}")

        if call_mode == "twilio":
            self._mock_mode = settings.mock_mode
            self._mock_phone = settings.mock_phone if settings.mock_mode else ""

            # In mock mode, redirect the call to the mock phone number.
            # If mock_mode is on but no mock_phone is set, REFUSE to dial —
            # never fall through to the real number.
            dial_number = patient.phone
            if settings.mock_mode:
                if not settings.mock_phone:
                    self._last_start_error = "Mock mode is ON but no mock phone number is set. Set one with: autocaller mock on <phone>"
                    if self.on_error:
                        await self.on_error(self._last_start_error)
                    await call_log_provider.end_call(call.call_id, CallOutcome.FAILED)
                    self._voice_service = None
                    self._current_call = None
                    self._current_patient = None
                    if voice_service:
                        await voice_service.disconnect()
                    return None
                dial_number = settings.mock_phone
                print(f"[CallOrchestrator] MOCK MODE — redirecting call from {patient.phone} to mock_phone={dial_number}")

            try:
                stream_id = carrier_adapter.generate_stream_id()
                bridge = carrier_adapter.MediaBridge(self._voice_service, verbose=self._verbose)
                carrier_adapter.register_bridge(stream_id, bridge)
                self._twilio_bridge = bridge  # name kept for back-compat; holds whichever carrier's bridge

                backend_host = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
                if not backend_host:
                    backend_host = os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
                twiml_url = f"{backend_host}{carrier_adapter.twiml_path}/{stream_id}"

                mock_label = " [MOCK]" if settings.mock_mode else ""
                if self._verbose:
                    print(f"[CallOrchestrator] Placing {resolved_carrier_name} call{mock_label} for {call.call_id} to {dial_number}, twiml_url={twiml_url}")
                if self.on_status_update:
                    status_msg = (
                        f"Mock mode — calling {dial_number} (instead of {patient.phone})"
                        if settings.mock_mode
                        else f"Calling {patient.phone} via {resolved_carrier_name.title()}..."
                    )
                    await self.on_status_update(status_msg)

                status_callback_url = f"{backend_host}{carrier_adapter.status_path}"
                recording_callback_url = f"{backend_host}{carrier_adapter.recording_path}/{call.call_id}"
                # AMD is DISABLED for both carriers. Twilio's "DetectMessageEnd"
                # runs BEFORE fetching TwiML; on PI firms with IVR + hold +
                # human transfer, AMD misclassifies the IVR as a machine and
                # aborts the call before our bot can connect. We detect IVR
                # via transcript phrases in the first 20s of audio instead.
                call_sid = carrier_adapter.place_call(
                    to_number=dial_number,
                    twiml_url=twiml_url,
                    status_callback_url=status_callback_url,
                    recording_status_callback_url=recording_callback_url,
                    enable_amd=False,
                )
                self._twilio_call_sid = call_sid  # name kept for back-compat
                self._current_carrier = resolved_carrier_name
                self._voicemail_handled = False
                if self._verbose:
                    print(f"[CallOrchestrator] {resolved_carrier_name} call placed: SID={call_sid}, call_id={call.call_id}, to={dial_number}")

            except Exception as e:
                print(f"[CallOrchestrator] {resolved_carrier_name} call FAILED for {call.call_id} to {dial_number}: {e}")
                self._last_start_error = f"{resolved_carrier_name.title()} call placement failed: {type(e).__name__}: {str(e)}"
                if self.on_error:
                    await self.on_error(f"{resolved_carrier_name.title()} call failed: {str(e)}")
                await call_log_provider.update_call(
                    call.call_id,
                    error_code=f"{resolved_carrier_name}_place_failed",
                    error_message=self._last_start_error,
                )
                await call_log_provider.end_call(call.call_id, CallOutcome.FAILED)
                # Pre-dial failure (carrier rejected placement — fraud block,
                # trial-unverified, auth, etc.). The lead's phone never rang,
                # so don't consume an attempt or set the retry cooldown —
                # the dispatcher should re-pick this lead on its next tick
                # once the carrier issue is resolved.
                voice = self._voice_service
                self._voice_service = None
                self._current_call = None
                self._current_patient = None
                self._twilio_bridge = None
                if voice:
                    await voice.disconnect()
                return None
        else:
            if self._verbose:
                print(f"[CallOrchestrator] Web mode — no Twilio phone call placed. call_id={call.call_id}, phone={patient.phone}")
            if self.on_status_update:
                await self.on_status_update("Connected - AI Speaking")
            self._web_recording_chunks = []
            self._web_recording_active = True

        if self.on_call_started:
            await self.on_call_started(call)

        # In Twilio mode, wait for the media stream to connect before
        # starting the conversation so the greeting audio isn't lost.
        if call_mode == "twilio" and self._twilio_bridge:
            if self.on_status_update:
                await self.on_status_update("Waiting for call to connect...")
            if self._verbose:
                print(f"[CallOrchestrator] Waiting for Twilio media stream to connect for call {call.call_id}...")
            connected = await self._twilio_bridge.wait_for_connection(timeout=90)
            if not connected:
                print(f"[CallOrchestrator] Twilio media stream timed out for call {call.call_id}")
                self._last_start_error = "Twilio media stream did not connect within 30 seconds (call may not have been answered)"
                if self.on_error:
                    await self.on_error("Twilio media stream connection timed out")
                await call_log_provider.update_call(
                    call.call_id,
                    error_code="media_stream_timeout",
                    error_message=self._last_start_error,
                )
                # No auto-SMS on media-stream timeout. Real cold calls that
                # no-answer should NOT trigger an outbound SMS — avoids
                # spam when the dialed number was actually an IVR / main
                # line rather than the target's direct cell.
                print(f"[CallOrchestrator] Media-stream timeout for call {call.call_id} — no SMS (auto-suppressed)")
                await call_log_provider.end_call(call.call_id, CallOutcome.FAILED)
                await self._mark_patient_attempt(patient, "failed")
                voice = self._voice_service
                self._voice_service = None
                self._current_call = None
                self._current_patient = None
                self._twilio_bridge = None
                if voice:
                    await voice.disconnect()
                return None
            if self._verbose:
                print(f"[CallOrchestrator] Twilio media stream connected for call {call.call_id}")
            if self.on_status_update:
                await self.on_status_update("Connected - AI Speaking")

        await self._voice_service.start_conversation(language=prompt_lang)
        if self._verbose:
            print(f"[CallOrchestrator] Conversation started for call {call.call_id} (language={prompt_lang})")

        self._caller_has_spoken = False
        self._silence_timeout_task = asyncio.create_task(
            self._silence_watchdog(call.call_id, timeout_seconds=45)
        )

        return call

    async def _hold_watchdog(self, call_id: str, timeout_seconds: int = 60):
        """End the call if we stay on hold for too long."""
        try:
            await asyncio.sleep(timeout_seconds)
            if self._on_hold and self._current_call and self._current_call.call_id == call_id:
                print(
                    f"[CallOrchestrator] Hold timeout ({timeout_seconds}s) — "
                    f"ending {call_id}."
                )
                await self._add_system_note(
                    f"Hold watchdog: on hold for {timeout_seconds}s with no response. Auto-ending."
                )
                await self.end_call(CallOutcome.FAILED)
        except asyncio.CancelledError:
            pass

    async def _silence_watchdog(self, call_id: str, timeout_seconds: int = 45):
        """End the call if no caller transcript arrives within timeout.

        Catches: voicemails Gemini doesn't transcribe, hold-music,
        media-stream-connected-but-nobody-home scenarios. The timer
        resets each time the caller speaks (see _handle_transcript).
        """
        try:
            await asyncio.sleep(timeout_seconds)
            if not self._caller_has_spoken and self._current_call and self._current_call.call_id == call_id:
                print(
                    f"[CallOrchestrator] Silence timeout ({timeout_seconds}s) — "
                    f"no caller audio for {call_id}. Ending as no_answer."
                )
                await self._add_system_note(
                    f"Silence watchdog: no caller transcript in {timeout_seconds}s. Auto-ending."
                )
                await self.end_call(CallOutcome.FAILED)
        except asyncio.CancelledError:
            pass

    async def end_call(self, outcome: CallOutcome = CallOutcome.COMPLETED):
        """End the current call."""
        if not self._current_call or self._ending_call:
            return
        # During a SIP transfer, Twilio closes the media stream which triggers
        # end_call(DISCONNECTED).  Ignore it — the transfer code will call
        # end_call(TRANSFERRED) momentarily.
        if self._transfer_in_progress and outcome == CallOutcome.DISCONNECTED:
            print(f"[CallOrchestrator] Ignoring DISCONNECTED during transfer — waiting for transfer outcome")
            return
        self._ending_call = True

        if self._silence_timeout_task and not self._silence_timeout_task.done():
            self._silence_timeout_task.cancel()

        call = self._current_call
        patient = self._current_patient
        voice_service = self._voice_service
        call_mode = self._call_mode
        twilio_call_sid = self._twilio_call_sid

        print(f"[CallOrchestrator] Ending call {call.call_id} with outcome={outcome.value} (mode={call_mode})")

        self._sync_status_callback()

        try:
            await self._notifications.maybe_send_issue_email(call, outcome)

            # Whitelist: auto-SMS ONLY when the lead explicitly asked for a
            # callback. No spam after no_answer / failed / voicemail / wrong
            # number / IVR / technical error. For demo_scheduled, Cal.com
            # already emails the confirmation — we don't double-send.
            sms_send_outcomes = (CallOutcome.CALLBACK_REQUESTED,)
            if outcome in sms_send_outcomes:
                print(f"[CallOrchestrator] Sending SMS (callback_info) for call {call.call_id} to {patient.phone if patient else 'unknown'}")
                await self._notifications.send_sms_for_call(
                    call=call,
                    patient=patient,
                    message_type="callback_info",
                    reason=f"outcome={outcome.value}",
                    call_mode=call_mode,
                    mock_mode=self._mock_mode,
                    mock_phone=self._mock_phone,
                )
            else:
                print(f"[CallOrchestrator] Skipping SMS for call {call.call_id} — outcome={outcome.value}")

            # Hang up the Twilio phone call (skip for transfers/voicemail which handle it themselves)
            # Always hang up Twilio on call end EXCEPT for TRANSFERRED (the
            # transfer logic manages the SIP transition itself). VOICEMAIL
            # used to be excluded because AMD+play-voicemail needed Twilio
            # to keep the line open; we now detect IVRs via transcript
            # BEFORE any message plays, so we should immediately hang up.
            # Keeping the line open would waste billing + delay recording
            # finalization for 30+ seconds.
            if call_mode == "twilio" and twilio_call_sid and outcome != CallOutcome.TRANSFERRED:
                try:
                    carrier_name = getattr(self, "_current_carrier", "twilio") or "twilio"
                    from app.services.carrier import get_carrier as _get_carrier
                    _adapter = _get_carrier(carrier_name)
                    if self._verbose:
                        print(f"[CallOrchestrator] Hanging up {carrier_name} call SID={twilio_call_sid}")
                    await asyncio.to_thread(_adapter.hangup, twilio_call_sid)
                except Exception as e:
                    logger.warning("Failed to hang up %s call %s: %s",
                                   getattr(self, "_current_carrier", "twilio"), twilio_call_sid, e)

            # Save web-call recording if we have audio chunks
            if self._web_recording_active and self._web_recording_chunks:
                try:
                    await self._save_web_recording(call.call_id)
                except Exception as e:
                    logger.warning("Failed to save web recording for %s: %s", call.call_id, e)
            self._web_recording_active = False
            self._web_recording_chunks = []

            self._current_call = None
            self._current_patient = None
            self._voice_service = None
            self._twilio_bridge = None

            call_log_provider = get_call_log_provider()
            await call_log_provider.end_call(call.call_id, outcome)

            # Only update the lead's attempt count + outcome for REAL calls.
            # Mock (phone redirect) and web (browser test) calls are practice
            # runs — they shouldn't burn the lead's retry window or remove
            # it from the dispatch queue.
            is_test_call = bool(
                getattr(call, "mock_mode", False)
                or call_mode == "web"
            )
            if patient and not is_test_call:
                patient_provider = get_patient_provider()
                await patient_provider.update_patient_after_call(
                    patient.patient_id,
                    outcome.value,
                )

            if voice_service:
                await voice_service.disconnect()

            if self.on_call_ended:
                await self.on_call_ended(call)

            if self.on_status_update:
                await self.on_status_update("Call Ended")
        finally:
            self._notifications.cleanup_call(call.call_id)
            self._twilio_call_sid = None
            self._voicemail_handled = False
            self._web_voicemail_simulated = False
            self._ending_call = False
            self._transfer_in_progress = False
            self._call_mode = "web"
            self._mock_mode = False
            self._mock_phone = ""

    async def _mark_patient_attempt(self, patient: Optional[Patient], outcome: str):
        """Record a failed call attempt on the patient so the cooldown/retry filter works.

        Used by early-failure paths in start_call() that don't go through end_call().
        """
        if patient is None:
            return
        try:
            patient_provider = get_patient_provider()
            await patient_provider.update_patient_after_call(patient.patient_id, outcome)
            print(f"[CallOrchestrator] Marked attempt for patient {patient.patient_id} (outcome={outcome})")
        except Exception as e:
            logger.warning("Failed to mark patient attempt for %s: %s", patient.patient_id, e)

    async def _check_transfer_availability(self) -> bool:
        """Check whether a scheduler queue has capacity for a transfer right now."""
        if not self._current_patient:
            return False
        patient_language = self._current_patient.language
        target_queue = self._transfer.resolve_queue(patient_language)
        queue_provider = get_queue_provider()
        queue_state = queue_provider.get_state()
        _, has_capacity = self._transfer.check_capacity(queue_state, target_queue)
        status = "available" if has_capacity else "unavailable"
        if self._current_call:
            call_log_provider = get_call_log_provider()
            await call_log_provider.add_transcript(
                self._current_call.call_id, "system",
                f"Transfer availability check: {status} (queue={target_queue})",
            )
        return has_capacity

    async def send_audio(self, audio_data: bytes):
        """Send audio from the patient (browser) to the voice service."""
        if self._web_recording_active:
            self._web_recording_chunks.append(audio_data)
        if self._voice_service and self._voice_service.is_connected:
            await self._voice_service.send_audio(audio_data)

    async def _handle_transcript(self, speaker: str, text: str):
        """Handle transcript updates from voice service."""
        if not self._current_call:
            return

        call_log_provider = get_call_log_provider()

        if speaker == "ai_complete":
            await call_log_provider.add_transcript(self._current_call.call_id, "ai", text)
            if self.on_transcript_update:
                await self.on_transcript_update("ai", text)

            # Did the AI just enter a hold state? Check the latest AI
            # utterance (may be split across multiple ai_complete events,
            # so combine the last few fragments).
            recent_ai = text
            if self._current_call:
                ai_entries = [
                    e.text for e in (self._current_call.transcript or [])
                    if e.speaker == "ai"
                ]
                recent_ai = "".join(ai_entries[-5:]) if ai_entries else text
            if self._should_enter_hold_state(recent_ai):
                if not self._on_hold:
                    self._on_hold = True
                    if self._twilio_bridge is not None:
                        try:
                            self._twilio_bridge.mute_ai_audio()
                        except Exception as e:
                            logger.debug("mute_ai_audio on hold entry failed: %s", e)
                    await self._add_system_note(
                        "Entered hold state — muting AI output "
                        "until caller speaks again (prevents filler-loop)."
                    )
                    if self._current_call:
                        cid = self._current_call.call_id
                        asyncio.create_task(self._hold_watchdog(cid, timeout_seconds=60))
        elif speaker == "patient":
            import time
            await call_log_provider.add_transcript(self._current_call.call_id, "patient", text)
            if self.on_transcript_update:
                await self.on_transcript_update("patient", text)

            # Caller spoke — cancel the silence watchdog and mark as spoken.
            # Also: if the AI hasn't produced audio in a while, nudge it.
            import time as _time
            last_out = getattr(self, "_last_audio_out_at", None)
            if last_out and (_time.monotonic() - last_out) > 5.0:
                try:
                    if self._voice_service is not None:
                        await self._voice_service.start_response()
                        print(f"[CallOrchestrator] Nudged AI — no output for {_time.monotonic() - last_out:.1f}s after caller spoke")
                except Exception:
                    pass
            self._caller_turn_count += 1
            if not self._caller_has_spoken:
                self._caller_has_spoken = True
                if self._silence_timeout_task and not self._silence_timeout_task.done():
                    self._silence_timeout_task.cancel()

            # Caller spoke — if we were on hold, exit hold state and
            # unmute. Cancel any Gemini-queued filler so the AI's next
            # turn is a fresh response to the caller's actual words.
            if self._on_hold and text.strip():
                self._on_hold = False
                if self._twilio_bridge is not None:
                    try:
                        self._twilio_bridge.unmute_ai_audio()
                    except Exception as e:
                        logger.debug("unmute_ai_audio on hold exit failed: %s", e)
                try:
                    if self._voice_service is not None:
                        await self._voice_service.cancel_response()
                        await self._voice_service.start_response()
                except Exception as e:
                    logger.debug("cancel+start_response on hold exit failed: %s", e)
                await self._add_system_note(
                    "Caller returned from hold — unmuting AI + restarting "
                    "response so AI re-engages."
                )

            # Track when the caller first spoke. The IVR-action window is
            # measured from HERE, not from Twilio dial — because ringing
            # eats 15-25s before any caller audio arrives, and the old
            # 20-seconds-from-dial cap was excluding real IVR greetings.
            if self._first_caller_audio_at is None:
                self._first_caller_audio_at = time.monotonic()

            # IVR / voicemail detection — only on the first 2 caller turns.
            # After 2+ back-and-forth exchanges, we're clearly talking to a
            # human. Phrases like "voicemail" or "leave a message" appearing
            # later are part of normal conversation (e.g. "want me to transfer
            # you to her voicemail?"), not IVR signals.
            if (
                self._caller_turn_count <= 2
                and not self._web_voicemail_simulated
                and not self._ivr_navigating
                and not self._ivr_handled
                and looks_like_voicemail_signal(text)
            ):
                elapsed_caller = time.monotonic() - (self._first_caller_audio_at or time.monotonic())
                # Always STAMP the signal — even outside the action window,
                # it's useful for post-hoc routing ("this firm's main line
                # is a gatekeeper tree; find a direct dial").
                if not self._current_call.ivr_detected:
                    await call_log_provider.update_call(
                        self._current_call.call_id, ivr_detected=True
                    )
                    self._current_call.ivr_detected = True

                # Only ACT if we're early in the caller-audio window. After
                # 45s of caller audio, any "press N" or "leave a message"
                # phrase is almost certainly legitimate speech in a human
                # conversation, and hanging up mid-call would be a false
                # positive.
                IVR_ACTION_WINDOW_SECS = 45.0
                if elapsed_caller <= IVR_ACTION_WINDOW_SECS:
                    # Two branches:
                    #   (a) IVR nav enabled + Twilio bridge ready → navigator
                    #   (b) otherwise → legacy hang-up
                    if (
                        self._ivr_navigate_enabled
                        and self._call_mode == "twilio"
                        and self._twilio_bridge is not None
                    ):
                        self._ivr_handled = True
                        # Claim navigation SYNCHRONOUSLY so any AI tool_call
                        # that arrives in the same event-loop slice (most
                        # commonly end_call(voicemail) per the v1.11 prompt's
                        # IVR rule) is suppressed by _handle_function_call
                        # before it can tear the call down.
                        self._ivr_navigating = True
                        # Also mute AI audio right now so the bridge drops
                        # any queued audio while navigator spins up.
                        if self._twilio_bridge is not None:
                            try:
                                self._twilio_bridge.mute_ai_audio()
                            except Exception:
                                pass
                        # And cancel whatever response the AI is currently
                        # generating (may be mid-token on end_call).
                        if self._voice_service is not None:
                            try:
                                await self._voice_service.cancel_response()
                            except Exception:
                                pass
                        print(f"[CallOrchestrator] IVR detected at {elapsed_caller:.1f}s (caller-audio) — handing to IVRNavigator (phrase: {text[:100]!r})")
                        await self._add_system_note(
                            f"IVR detected at {elapsed_caller:.1f}s of caller audio — "
                            f"handing to navigator. Heard: {text[:160]!r}"
                        )
                        if self.on_status_update:
                            await self.on_status_update("IVR detected — navigating phone tree")
                        asyncio.create_task(self._run_ivr_navigation(initial_snippet=text))
                    else:
                        self._web_voicemail_simulated = True
                        await call_log_provider.update_call(
                            self._current_call.call_id,
                            voicemail_left=True,
                            ivr_outcome="skipped",
                        )
                        self._current_call.voicemail_left = True
                        self._current_call.ivr_outcome = "skipped"
                        print(f"[CallOrchestrator] IVR/voicemail detected at {elapsed_caller:.1f}s (caller-audio) — hanging up (navigation disabled) (phrase: {text[:100]!r})")
                        await self._add_system_note(
                            f"IVR/voicemail detected at {elapsed_caller:.1f}s of caller audio — "
                            f"hanging up (navigation disabled). Heard: {text[:160]!r}"
                        )
                        if self.on_status_update:
                            await self.on_status_update("IVR/voicemail detected — hanging up")
                        await self.end_call(CallOutcome.VOICEMAIL)
        elif speaker == "ai":
            if self.on_transcript_update:
                await self.on_transcript_update("ai_delta", text)

    async def _handle_audio(self, audio_data: bytes):
        """Handle audio output from voice service."""
        import time
        self._last_audio_out_at = time.monotonic()
        if self._web_recording_active:
            self._web_recording_chunks.append(audio_data)
        if self.on_audio_output:
            await self.on_audio_output(audio_data)

    @staticmethod
    def _should_enter_hold_state(ai_utterance: str) -> bool:
        """Detect whether the AI just acknowledged being put on hold.

        Covers English + Spanish variants of the "Thanks, I'll hold" /
        "Perfect, I'll hold" / "Aquí espero" patterns. We're generous in
        matching because the cost of a false positive (brief unintended
        mute) is low — the mute lifts as soon as the caller speaks. The
        cost of a miss (Gemini filler-loop hits the phone line) is high.
        """
        if not ai_utterance:
            return False
        low = ai_utterance.lower()
        phrases = (
            "i'll hold",
            "i will hold",
            "i'm holding",
            "i am holding",
            "happy to hold",
            "aquí espero",
            "aqui espero",
            "perfecto, espero",
            "perfecto espero",
            "claro, espero",
            "sí, espero",
            "si espero",
        )
        return any(p in low for p in phrases)

    async def _save_web_recording(self, call_id: str) -> None:
        """Save accumulated web-call audio chunks as a WAV file."""
        import wave
        from pathlib import Path
        from datetime import datetime, timezone

        chunks = self._web_recording_chunks
        if not chunks:
            return

        pcm = b"".join(chunks)
        if len(pcm) < 1000:
            return

        now = datetime.now(timezone.utc)
        audio_dir = Path(__file__).resolve().parent.parent / "audio" / "recordings"
        dest_dir = audio_dir / str(now.year) / f"{now.month:02d}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        wav_path = dest_dir / f"{call_id}.wav"

        # Web-call audio is PCM16 @ 24kHz (Gemini output) interleaved with
        # PCM16 @ 16kHz (browser input). Since both directions are mixed in
        # the chunks list, use 24kHz as the sample rate (close enough for
        # playback + Whisper transcription).
        sample_rate = 24000
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm)

        size = wav_path.stat().st_size
        duration = len(pcm) // (2 * sample_rate)
        rel_path = f"recordings/{now.year}/{now.month:02d}/{call_id}.wav"

        call_log_provider = get_call_log_provider()
        await call_log_provider.set_recording(
            call_id=call_id,
            recording_sid=f"web-{call_id[:8]}",
            recording_path=rel_path,
            recording_size_bytes=size,
            recording_duration_seconds=duration,
            recording_format="wav",
        )
        print(f"[CallOrchestrator] Web recording saved: {rel_path} ({size} bytes, {duration}s)")

    async def _add_system_note(self, text: str) -> None:
        """Append an annotated event into the call's transcript stream.

        Used for IVR navigation steps, voicemail hangups, tool short-circuits
        — anything that's not a direct AI or caller utterance but that a
        reviewer will want to see inline to understand what happened.
        speaker="system" keeps these distinct from AI/patient turns so the
        UI can style them differently.
        """
        if not self._current_call or not text:
            return
        try:
            await get_call_log_provider().add_transcript(
                self._current_call.call_id, "system", text
            )
        except Exception as e:
            logger.warning("add system note failed: %s", e)
        if self.on_transcript_update:
            try:
                await self.on_transcript_update("system", text)
            except Exception:
                pass

    def _recent_caller_transcript(self, max_entries: int = 6) -> str:
        """Return the most recent caller-side transcript entries joined.

        IVRNavigator uses this to see what the phone tree just said after a
        digit press. We only pull patient-side text — the AI is muted
        during navigation so AI deltas are irrelevant.
        """
        if not self._current_call or not self._current_call.transcript:
            return ""
        caller = [
            (t.text or "").strip()
            for t in self._current_call.transcript
            if getattr(t, "speaker", "") == "patient" and (t.text or "").strip()
        ]
        return " ".join(caller[-max_entries:])

    async def _run_ivr_navigation(self, *, initial_snippet: str) -> None:
        """Run the IVR navigator end-to-end, then decide what to do next.

        On reached_human: unmute the AI and seed a fresh "Hello?" so the
        conversation can begin with the human who just picked up.
        On dead_end/timed_out: stamp ivr_outcome + end the call as voicemail.
        """
        from app.services.ivr_navigator import (
            get_ivr_navigator,
            OUTCOME_REACHED_HUMAN,
            OUTCOME_DEAD_END,
            OUTCOME_TIMED_OUT,
            OUTCOME_NOT_IVR,
            OUTCOME_QUEUE_WAIT,
        )

        # _ivr_navigating is set synchronously by _handle_transcript BEFORE
        # this task is scheduled, so we skip the usual "already navigating"
        # guard here. Just bail if the call has already torn down.
        if not self._current_call or not self._twilio_bridge:
            self._ivr_navigating = False
            return
        try:
            bridge = self._twilio_bridge
            navigator = get_ivr_navigator()

            async def _dtmf(digit: str) -> None:
                await bridge.send_dtmf(digit)

            def _recent() -> str:
                # Combine whatever just landed with the most-recent patient
                # transcript so the LLM has context from BEFORE the DTMF too.
                return self._recent_caller_transcript()

            async def _note(msg: str) -> None:
                await self._add_system_note(msg)

            result = await navigator.navigate(
                get_recent_transcript=_recent,
                send_dtmf=_dtmf,
                mute_ai_audio=bridge.mute_ai_audio,
                unmute_ai_audio=bridge.unmute_ai_audio,
                initial_transcript=initial_snippet or _recent(),
                on_note=_note,
            )

            call_log_provider = get_call_log_provider()
            menu_log = result.to_log()
            if self._current_call is None:
                print(f"[CallOrchestrator] IVR nav finished but call already ended (outcome={result.outcome})")
                self._ivr_navigating = False
                return
            await call_log_provider.update_call(
                self._current_call.call_id,
                ivr_outcome=result.outcome,
                ivr_menu_log=menu_log,
            )
            self._current_call.ivr_outcome = result.outcome
            self._current_call.ivr_menu_log = menu_log
            print(f"[CallOrchestrator] IVR nav done: outcome={result.outcome} steps={len(menu_log)}")

            if result.outcome == OUTCOME_REACHED_HUMAN:
                # Human on the line — unmute + prompt the voice backend to
                # open a fresh greeting so our pitch starts cleanly.
                await self._add_system_note(
                    "Reached a human via IVR navigation — resuming cold-call greeting."
                )
                if self.on_status_update:
                    await self.on_status_update("Reached a human via IVR navigation")
                try:
                    if self._voice_service is not None:
                        from app.prompts.attorney_cold_call import prompt_language_for
                        lang = prompt_language_for(self._current_patient) if self._current_patient else "en"
                        await self._voice_service.start_conversation(language=lang)
                except Exception as e:
                    logger.warning("Could not seed post-IVR greeting: %s", e)
                return  # leave conversation to the normal flow

            if result.outcome == OUTCOME_QUEUE_WAIT:
                # Classic "please hold / next available agent" queue. A human
                # is about to be patched through — stay on the line, keep
                # audio unmuted (the navigator already unmuted), and let the
                # existing VAD flow kick in when they speak. Cancel any
                # queued AI audio that may have been generated while muted.
                await self._add_system_note(
                    "Queue detected — staying on the line silently. "
                    "AI will greet whoever picks up."
                )
                try:
                    if self._voice_service is not None:
                        await self._voice_service.cancel_response()
                except Exception as e:
                    logger.debug("cancel_response during queue-wait failed: %s", e)
                if self.on_status_update:
                    await self.on_status_update("On hold for a live agent — staying on the line")
                return  # conversation continues; no hang-up, no reseed

            # NOT_IVR false-positive: navigator's first classification was
            # "human" — the pre-filter triggered on a phrase that turned out
            # to be a human talking ("take a message", "please hold, this is
            # Taylor"), not a voicemail or menu. Don't hang up — resume the
            # conversation. Distinguishable from the "first classification
            # was voicemail" case by inspecting the first step's result.
            first_step_result = (
                result.steps[0].result if result.steps else ""
            )
            if result.outcome == OUTCOME_NOT_IVR and first_step_result == "reached_human":
                await self._add_system_note(
                    "Navigator classified as human (no navigation needed) — "
                    "resuming conversation without reseeding."
                )
                try:
                    if self._voice_service is not None:
                        # Cancel any queued AI audio from the muted period,
                        # then trigger a new response based on the existing
                        # conversation state. The AI's next turn will
                        # naturally pick up the opener since it still has
                        # the caller's first utterance in its history.
                        await self._voice_service.cancel_response()
                        await self._voice_service.start_response()
                except Exception as e:
                    logger.warning("Could not resume after false-positive IVR: %s", e)
                if self.on_status_update:
                    await self.on_status_update("False IVR alarm — resuming conversation")
                return  # no hang-up, no reseed greeting

            # Dead-end / timed-out / not_ivr(voicemail) → hang up with voicemail outcome.
            # The derive_* helper will turn this into IVR_UNREACHED now that
            # ivr_detected=True + ivr_outcome is stamped.
            self._web_voicemail_simulated = True
            await call_log_provider.update_call(
                self._current_call.call_id, voicemail_left=True,
            )
            self._current_call.voicemail_left = True
            await self._add_system_note(
                f"IVR navigation ended: {result.outcome} after {len(menu_log)} hop(s) — hanging up."
            )
            if self.on_status_update:
                await self.on_status_update(f"IVR navigation {result.outcome} — hanging up")
            await self.end_call(CallOutcome.VOICEMAIL)
        finally:
            self._ivr_navigating = False

    async def _wait_for_audio_drain(
        self,
        *,
        silence_needed: float = 1.2,
        max_wait: float = 5.0,
    ) -> None:
        """Block until the AI's speech has stopped for `silence_needed` seconds,
        up to `max_wait`. Called before tearing down a call so we don't clip
        the model's sign-off.

        Models frequently call `end_call` mid-goodbye; without this wait, the
        Twilio hangup fires while "…have a great day!" is still streaming.
        """
        import time
        deadline = time.monotonic() + max_wait
        last_seen = getattr(self, "_last_audio_out_at", 0.0) or 0.0
        # If the model hasn't emitted any audio at all since connect, don't wait.
        if last_seen == 0.0:
            return
        while True:
            now = time.monotonic()
            if now - last_seen >= silence_needed:
                return
            if now >= deadline:
                return
            await asyncio.sleep(0.1)
            last_seen = getattr(self, "_last_audio_out_at", last_seen)

    async def _handle_function_call(self, name: str, args: dict, fn_call_id: str = ""):
        """Handle function calls from AI."""
        if not self._current_call:
            return

        self._sync_status_callback()

        # Suppress AI tool calls while the IVR navigator has the wheel.
        # The v1.11 prompt tells the model to silently end_call on IVR
        # detection — but we've already handed that decision to
        # IVRNavigator. If both race, the AI's end_call wins and the
        # navigator never gets to classify/press. Block until nav
        # returns (at which point _ivr_navigating flips false).
        if self._ivr_navigating and name != "send_function_result":
            await self._add_system_note(
                f"Suppressed AI tool call `{name}` — IVR navigator is active."
            )
            if self._voice_service and fn_call_id:
                # Return an empty success so the model's turn completes
                # without further action.
                await self._voice_service.send_function_result(
                    fn_call_id, {"status": "deferred_to_navigator"}
                )
            return

        if name == "check_transfer_availability":
            available = await self._check_transfer_availability()
            if self._voice_service and fn_call_id:
                await self._voice_service.send_function_result(
                    fn_call_id, {"available": available}
                )
            return

        if name == "transfer_to_scheduler":
            if args.get("confirmed"):
                self._transfer_in_progress = True
                outcome = await self._transfer.execute_transfer(
                    call=self._current_call,
                    patient=self._current_patient,
                    call_mode=self._call_mode,
                    twilio_call_sid=self._twilio_call_sid,
                    notification_service=self._notifications,
                    mock_mode=self._mock_mode,
                    mock_phone=self._mock_phone,
                )
                await self.end_call(outcome)

        elif name == "end_call":
            # Supports BOTH arg schemas: legacy {reason} and autocaller {outcome}.
            callback = args.get("callback_requested", False)
            preferred_callback_time = str(
                args.get("preferred_callback_time")
                or args.get("callback_requested_at", "")
                or ""
            ).strip()

            outcome_map = {
                # legacy
                "patient_busy": CallOutcome.CALLBACK_REQUESTED,
                "patient_request": CallOutcome.COMPLETED,
                # shared
                "wrong_number": CallOutcome.WRONG_NUMBER,
                "voicemail": CallOutcome.VOICEMAIL,
                "completed": CallOutcome.COMPLETED,
                "callback_requested": CallOutcome.CALLBACK_REQUESTED,
                # autocaller
                "demo_scheduled": CallOutcome.DEMO_SCHEDULED,
                "not_interested": CallOutcome.NOT_INTERESTED,
                "gatekeeper_only": CallOutcome.GATEKEEPER_ONLY,
            }
            reason = str(args.get("outcome") or args.get("reason", "") or "completed").strip()
            outcome = outcome_map.get(reason, CallOutcome.COMPLETED)
            if callback and outcome == CallOutcome.COMPLETED:
                outcome = CallOutcome.CALLBACK_REQUESTED

            # Persist autocaller capture fields if the AI supplied them.
            capture_update: dict = {}
            if "pain_point_summary" in args and args["pain_point_summary"]:
                capture_update["pain_point_summary"] = str(args["pain_point_summary"])[:2000]
            if "interest_level" in args and args["interest_level"] is not None:
                try:
                    capture_update["interest_level"] = int(args["interest_level"])
                except (TypeError, ValueError):
                    pass
            if "is_decision_maker" in args and args["is_decision_maker"] is not None:
                capture_update["is_decision_maker"] = bool(args["is_decision_maker"])
            if preferred_callback_time:
                capture_update["preferred_callback_time"] = preferred_callback_time

            if capture_update:
                call_log_provider = get_call_log_provider()
                await call_log_provider.update_call(
                    self._current_call.call_id, **capture_update
                )
                for k, v in capture_update.items():
                    setattr(self._current_call, k, v)

            # Let any in-flight goodbye audio drain before we hang up.
            await self._wait_for_audio_drain()
            await self.end_call(outcome)

        elif name == "send_sms":
            await self._notifications.send_sms_for_call(
                call=self._current_call,
                patient=self._current_patient,
                message_type=args.get("message_type", "callback_info"),
                reason="ai_tool",
                call_mode=self._call_mode,
                mock_mode=self._mock_mode,
                mock_phone=self._mock_phone,
            )

        # ------------------------------------------------------------------
        # Autocaller (attorney cold-call) tools
        # ------------------------------------------------------------------
        elif name == "check_availability":
            result = await self._autocaller_check_availability(args)
            if self._voice_service and fn_call_id:
                await self._voice_service.send_function_result(fn_call_id, result)

        elif name == "book_demo":
            result = await self._autocaller_book_demo(args)
            if self._voice_service and fn_call_id:
                await self._voice_service.send_function_result(fn_call_id, result)

        elif name == "mark_gatekeeper":
            await self._autocaller_mark_gatekeeper(args)
            if self._voice_service and fn_call_id:
                await self._voice_service.send_function_result(fn_call_id, {"ok": True})

        elif name == "send_followup_email":
            result = await self._autocaller_send_followup(args)
            if self._voice_service and fn_call_id:
                await self._voice_service.send_function_result(fn_call_id, result)

        # Autocaller `end_call` uses an enum set different from the legacy one.
        # Legacy end_call above consumes `reason` — the autocaller one uses `outcome`.
        # If this function-call block has `outcome` instead of `reason`, route it
        # through the autocaller end path.
        # (The legacy end_call branch matches `name == "end_call"` with `reason`;
        # the autocaller uses the same tool name but different arg schema, so we
        # handle it by inspecting args when the legacy branch didn't match.)

    # ---------------------------------------------------------------------
    # Autocaller tool implementations
    # ---------------------------------------------------------------------
    async def _autocaller_check_availability(self, args: dict) -> dict:
        """Fetch upcoming demo slots from Cal.com for the current lead.

        Returns a dict with `slots` (possibly empty) and `error` (non-empty
        string on failure). The AI uses `error` to decide whether to offer the
        email-follow-up fallback instead of promising a live booking.
        """
        from app.services.calcom_service import get_calcom_service, CalComError
        from app.prompts.attorney_cold_call import _default_timezone_for_state

        settings_provider = get_settings_provider()
        settings = await settings_provider.get_settings()
        cfg = getattr(settings, "calcom_config", None)
        cfg_event_type_id = getattr(cfg, "event_type_id", None) if cfg else None
        cfg_default_tz = getattr(cfg, "default_timezone", None) if cfg else None
        env_event_type_id = os.getenv("CALCOM_EVENT_TYPE_ID", "").strip()
        event_type_id = cfg_event_type_id or (int(env_event_type_id) if env_event_type_id.isdigit() else None)
        api_key_present = bool(os.getenv("CALCOM_API_KEY", "").strip())

        if not event_type_id or not api_key_present:
            logger.warning("check_availability: calendar not configured (api_key=%s event_type_id=%s)",
                           api_key_present, event_type_id)
            return {
                "slots": [],
                "error": "calendar_not_configured",
                "fallback": "offer_email_followup",
            }

        tz = (
            _default_timezone_for_state(self._current_patient.state if self._current_patient else None)
            or cfg_default_tz
            or "America/New_York"
        )
        days = int(args.get("days_ahead", 7) or 7)
        try:
            slots = await get_calcom_service().get_availability(
                event_type_id=int(event_type_id),
                timezone_name=tz,
                days=days,
                max_slots=5,
            )
        except CalComError as e:
            logger.warning("Cal.com get_availability failed: %s", e)
            return {
                "slots": [],
                "error": f"calendar_unreachable: {e}",
                "fallback": "offer_email_followup",
            }

        if not slots:
            return {
                "slots": [],
                "error": "no_slots_available",
                "fallback": "offer_email_followup",
            }

        return {
            "slots": [{"start_iso": s.start_iso, "label": s.label()} for s in slots],
            "timezone": tz,
        }

    async def _autocaller_book_demo(self, args: dict) -> dict:
        """Book a demo slot on Cal.com and stamp it on the call log."""
        from app.services.calcom_service import get_calcom_service, CalComError
        from app.prompts.attorney_cold_call import _default_timezone_for_state
        from datetime import datetime, timezone

        if not self._current_patient or not self._current_call:
            return {"booked": False, "error": "no_active_call"}

        slot_iso = str(args.get("slot_iso", "") or "").strip()
        invitee_email = str(args.get("invitee_email", "") or "").strip()
        pain_summary = str(args.get("pain_point_summary", "") or "").strip()

        if not slot_iso or not invitee_email:
            return {"booked": False, "error": "missing_slot_or_email"}

        settings_provider = get_settings_provider()
        settings = await settings_provider.get_settings()
        cfg = getattr(settings, "calcom_config", None)
        event_type_id = getattr(cfg, "event_type_id", None) if cfg else None
        cfg_default_tz = getattr(cfg, "default_timezone", None) if cfg else None
        if not event_type_id:
            return {"booked": False, "error": "calcom_not_configured"}

        tz = (
            _default_timezone_for_state(self._current_patient.state)
            or cfg_default_tz
            or "America/New_York"
        )

        try:
            booking = await get_calcom_service().book_slot(
                event_type_id=int(event_type_id),
                slot_iso=slot_iso,
                invitee_name=self._current_patient.name,
                invitee_email=invitee_email,
                timezone_name=tz,
                metadata={
                    "lead_id": self._current_patient.patient_id,
                    "call_id": self._current_call.call_id,
                    "firm_name": self._current_patient.firm_name or "",
                    "state": self._current_patient.state or "",
                },
                notes=pain_summary or None,
            )
        except CalComError as e:
            logger.warning("Cal.com book_slot failed: %s", e)
            return {"booked": False, "error": str(e)}

        # Persist to call log
        try:
            scheduled_at = datetime.fromisoformat(booking.start_iso)
        except ValueError:
            scheduled_at = datetime.now(timezone.utc)

        call_log_provider = get_call_log_provider()
        await call_log_provider.update_call(
            self._current_call.call_id,
            demo_booking_id=booking.booking_id,
            demo_scheduled_at=scheduled_at,
            demo_meeting_url=booking.meeting_url or "",
            pain_point_summary=pain_summary or None,
        )
        self._current_call.demo_booking_id = booking.booking_id
        self._current_call.demo_scheduled_at = scheduled_at
        self._current_call.demo_meeting_url = booking.meeting_url
        self._current_call.pain_point_summary = pain_summary or None

        await call_log_provider.add_transcript(
            self._current_call.call_id,
            "system",
            f"Demo booked: {booking.start_iso} ({booking.booking_id})",
        )

        return {
            "booked": True,
            "booking_id": booking.booking_id,
            "start_iso": booking.start_iso,
            "meeting_url": booking.meeting_url or "",
        }

    async def _autocaller_mark_gatekeeper(self, args: dict):
        """Record gatekeeper context on the call log."""
        if not self._current_call:
            return
        contact = {
            k: str(v).strip()
            for k, v in args.items()
            if v and isinstance(v, (str, int))
        }
        call_log_provider = get_call_log_provider()
        await call_log_provider.update_call(
            self._current_call.call_id,
            was_gatekeeper=True,
            gatekeeper_contact=contact or None,
        )
        self._current_call.was_gatekeeper = True
        self._current_call.gatekeeper_contact = contact or None
        await call_log_provider.add_transcript(
            self._current_call.call_id,
            "system",
            f"Gatekeeper captured: {contact}",
        )

    async def _autocaller_send_followup(self, args: dict) -> dict:
        """Capture a follow-up email intent for the current lead.

        IMPORTANT: this handler NEVER returns `sent: false` or surfaces an
        error string to the AI. Even when actual SMTP delivery isn't
        configured, we ALWAYS record the captured email on the call_log
        and return `{sent: true, recorded: true}` so the AI can finish
        its turn gracefully ("I'll send that over") without narrating
        infrastructure problems to the caller.

        Real delivery is attempted when the email service is configured.
        If it fails, we silently downgrade to "recorded-only" — the
        captured email lives on `call_log.captured_contacts` and
        `gatekeeper_contact` for later manual / batch sending.
        """
        from app.services.email_notification_service import send_followup_email

        if not self._current_patient or not self._current_call:
            # Even here: don't surface an error string. Say recorded.
            return {"sent": True, "recorded": True}

        email = str(args.get("invitee_email", "") or "").strip()
        if not email:
            # No email to record. Still don't throw — AI should move on.
            return {"sent": True, "recorded": False, "note": "no_email_provided"}

        message_type = str(args.get("message_type", "one_pager"))
        custom_note = str(args.get("custom_note", "") or "").strip()
        sales = {}
        try:
            settings = await get_settings_provider().get_settings()
            sales = getattr(settings, "sales_context", {}) or {}
        except Exception:
            pass

        delivered = False
        delivery_note = ""
        try:
            delivered = bool(await send_followup_email(
                to_email=email,
                lead_name=self._current_patient.name,
                firm_name=self._current_patient.firm_name or "",
                message_type=message_type,
                custom_note=custom_note,
                rep_name=sales.get("rep_name", ""),
                rep_company=sales.get("rep_company", ""),
                rep_email=sales.get("rep_email", ""),
            ))
        except Exception as e:
            # Swallow — AI should not announce this on the call.
            logger.warning("send_followup_email failed (recording only): %s", e)
            delivery_note = f"smtp_failed: {type(e).__name__}: {str(e)[:200]}"

        # Always record the captured email regardless of delivery.
        call_log_provider = get_call_log_provider()
        captured = list(getattr(self._current_call, "captured_contacts", None) or [])
        captured.append({
            "name": self._current_patient.name,
            "email": email,
            "phone": None,
            "title": self._current_patient.title or None,
            "source": "send_followup_email",
            "message_type": message_type,
            "custom_note": custom_note or None,
            "delivered": delivered,
            "delivery_note": delivery_note or None,
            "captured_at": datetime.now(timezone.utc).isoformat(),
        })
        await call_log_provider.update_call(
            self._current_call.call_id,
            followup_email_sent=delivered,
            captured_contacts=captured,
        )
        self._current_call.followup_email_sent = delivered
        self._current_call.captured_contacts = captured

        # Internal system note so operators can see what really happened
        # without the AI narrating it on the call.
        if delivered:
            note = f"Email followup sent to {email}."
        else:
            note = (
                f"Email followup NOT sent (SMTP unavailable) — captured "
                f"{email} on call_log for manual sending."
            )
        try:
            await self._add_system_note(note)
        except Exception:
            pass

        # Return ONLY positive signal to the AI.
        return {"sent": True, "recorded": True, "email": email}

    async def _handle_voice_error(self, error: str):
        """Handle errors from voice service."""
        if self._current_call:
            call_log_provider = get_call_log_provider()
            await call_log_provider.update_call(
                self._current_call.call_id,
                error_code="voice_error",
                error_message=error,
            )
            self._current_call.error_code = "voice_error"
            self._current_call.error_message = error
        if self.on_error:
            await self.on_error(error)

    async def _handle_session_ended(self):
        """Handle voice session ending unexpectedly."""
        if self._current_call and self._current_call.outcome == CallOutcome.IN_PROGRESS:
            await self.end_call(CallOutcome.FAILED)

    @property
    def is_call_active(self) -> bool:
        """Check if a call is currently active."""
        return self._current_call is not None

    @property
    def current_call(self) -> Optional[CallLog]:
        """Get the current call."""
        return self._current_call


# Global instance
_orchestrator: Optional[CallOrchestrator] = None


def get_orchestrator() -> CallOrchestrator:
    """Get the global call orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = CallOrchestrator()
    return _orchestrator
