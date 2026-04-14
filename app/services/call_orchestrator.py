"""Call orchestrator service managing the call lifecycle."""
import asyncio
import logging
import os
from typing import Optional, Callable, Any

from app.models import CallLog, CallOutcome, Patient
from app.providers import get_queue_provider, get_patient_provider, get_call_log_provider, get_settings_provider
from app.services.realtime_voice import RealtimeVoiceService
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
        self._voice_service: Optional[RealtimeVoiceService] = None
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

    async def start_call(self, patient_id: str, call_mode: str = "web") -> Optional[CallLog]:
        """Start an outbound call to a patient."""
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
            TOOLS as AUTOCALLER_TOOLS,
            PROMPT_VERSION,
        )
        sales = getattr(settings, "sales_context", None)

        def _sales_or_env(attr: str, env: str, default: str = "") -> str:
            val = getattr(sales, attr, "") if sales is not None else ""
            return val or os.getenv(env, default)

        system_prompt = render_system_prompt(
            lead=patient,
            rep_name=_sales_or_env("rep_name", "SALES_REP_NAME", "Alex"),
            rep_company=_sales_or_env("rep_company", "SALES_REP_COMPANY", "our team"),
            product_context=_sales_or_env("product_context", "PRODUCT_CONTEXT", ""),
        )

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
            prompt_version=PROMPT_VERSION,
            tools_snapshot=list(AUTOCALLER_TOOLS),
        )

        self._current_call = call
        self._current_patient = patient
        self._call_mode = call_mode
        self._web_voicemail_simulated = False
        self._verbose = settings.dispatcher_settings.verbose_logging

        mode_label = "Twilio" if call_mode == "twilio" else "Web"
        print(f"[CallOrchestrator] Starting call to {patient.name} ({patient.phone}) in {mode_label} mode")

        if self.on_status_update:
            await self.on_status_update(f"Connecting ({mode_label})...")

        audio_format = "g711_ulaw" if call_mode == "twilio" else "pcm16"

        self._voice_service = RealtimeVoiceService(audio_format=audio_format, verbose=self._verbose)
        self._voice_service.on_transcript = self._handle_transcript
        self._voice_service.on_audio = self._handle_audio
        self._voice_service.on_function_call = self._handle_function_call
        self._voice_service.on_error = self._handle_voice_error
        self._voice_service.on_session_ended = self._handle_session_ended

        if self._verbose:
            print(f"[CallOrchestrator] Connecting to OpenAI Realtime for call {call.call_id}...")

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
            print(f"[CallOrchestrator] OpenAI Realtime connection FAILED for call {call.call_id}")
            self._last_start_error = "Failed to connect to OpenAI Realtime API"
            await call_log_provider.update_call(
                call.call_id,
                error_code="openai_connect_failed",
                error_message=self._last_start_error,
            )
            await call_log_provider.end_call(call.call_id, CallOutcome.FAILED)
            await self._mark_patient_attempt(patient, "failed")
            self._voice_service = None
            self._current_call = None
            self._current_patient = None
            return None
        if self._verbose:
            print(f"[CallOrchestrator] OpenAI Realtime connected for call {call.call_id}")

        if call_mode == "twilio":
            self._mock_mode = settings.mock_mode
            self._mock_phone = settings.mock_phone if settings.mock_mode else ""

            # In mock mode, redirect the Twilio call to the mock phone number
            dial_number = patient.phone
            if settings.mock_mode and settings.mock_phone:
                dial_number = settings.mock_phone
                print(f"[CallOrchestrator] MOCK MODE — redirecting call from {patient.phone} to mock_phone={dial_number}")

            try:
                from app.services.twilio_voice_service import (
                    TwilioMediaBridge,
                    place_twilio_call,
                    generate_stream_id,
                    register_bridge,
                )

                stream_id = generate_stream_id()
                bridge = TwilioMediaBridge(self._voice_service, verbose=self._verbose)
                register_bridge(stream_id, bridge)
                self._twilio_bridge = bridge

                backend_host = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
                if not backend_host:
                    backend_host = os.getenv("NEXT_PUBLIC_API_URL", "http://localhost:8000").rstrip("/")
                twiml_url = f"{backend_host}/api/twilio/twiml/{stream_id}"

                mock_label = " [MOCK]" if settings.mock_mode else ""
                if self._verbose:
                    print(f"[CallOrchestrator] Placing Twilio call{mock_label} for {call.call_id} to {dial_number}, twiml_url={twiml_url}")
                if self.on_status_update:
                    status_msg = f"Mock mode — calling {dial_number} (instead of {patient.phone})" if settings.mock_mode else f"Calling {patient.phone} via Twilio..."
                    await self.on_status_update(status_msg)

                status_callback_url = f"{backend_host}/api/twilio/status"
                recording_callback_url = f"{backend_host}/api/twilio/recording-status/{call.call_id}"
                call_sid = place_twilio_call(
                    to_number=dial_number,
                    twiml_url=twiml_url,
                    status_callback_url=status_callback_url,
                    recording_status_callback_url=recording_callback_url,
                    enable_amd=not settings.mock_mode,
                )
                self._twilio_call_sid = call_sid
                self._voicemail_handled = False
                if self._verbose:
                    print(f"[CallOrchestrator] Twilio call placed: SID={call_sid}, call_id={call.call_id}, to={dial_number}")

            except Exception as e:
                print(f"[CallOrchestrator] Twilio call FAILED for {call.call_id} to {dial_number}: {e}")
                self._last_start_error = f"Twilio call placement failed: {type(e).__name__}: {str(e)}"
                if self.on_error:
                    await self.on_error(f"Twilio call failed: {str(e)}")
                await call_log_provider.update_call(
                    call.call_id,
                    error_code="twilio_place_failed",
                    error_message=self._last_start_error,
                )
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
        else:
            if self._verbose:
                print(f"[CallOrchestrator] Web mode — no Twilio phone call placed. call_id={call.call_id}, phone={patient.phone}")
            if self.on_status_update:
                await self.on_status_update("Connected - AI Speaking")

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
                # Send callback SMS for no-answer (per spec: no-answer should get SMS)
                print(f"[CallOrchestrator] Sending SMS (no answer) for call {call.call_id} to {patient.phone if patient else 'unknown'}")
                await self._notifications.send_sms_for_call(
                    call=call,
                    patient=patient,
                    message_type="callback_info",
                    reason="no_answer",
                    call_mode=call_mode,
                    mock_mode=self._mock_mode,
                    mock_phone=self._mock_phone,
                )
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

        await self._voice_service.start_conversation()
        if self._verbose:
            print(f"[CallOrchestrator] Conversation started for call {call.call_id}")

        return call

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

        call = self._current_call
        patient = self._current_patient
        voice_service = self._voice_service
        call_mode = self._call_mode
        twilio_call_sid = self._twilio_call_sid

        print(f"[CallOrchestrator] Ending call {call.call_id} with outcome={outcome.value} (mode={call_mode})")

        self._sync_status_callback()

        try:
            await self._notifications.maybe_send_issue_email(call, outcome)

            # Skip SMS only when the number is known-bad or the patient is already
            # talking to a human.  All other outcomes (no answer, hung up, voicemail,
            # callback, technical error) should get a callback SMS.
            sms_skip_outcomes = (CallOutcome.TRANSFERRED, CallOutcome.WRONG_NUMBER)
            if outcome not in sms_skip_outcomes:
                print(f"[CallOrchestrator] Sending SMS (callback_info) for call {call.call_id} to {patient.phone if patient else 'unknown'}")
                await self._notifications.send_sms_for_call(
                    call=call,
                    patient=patient,
                    message_type="callback_info",
                    reason="auto_end_not_transferred",
                    call_mode=call_mode,
                    mock_mode=self._mock_mode,
                    mock_phone=self._mock_phone,
                )
            else:
                print(f"[CallOrchestrator] Skipping SMS for call {call.call_id} — outcome={outcome.value}")

            # Hang up the Twilio phone call (skip for transfers/voicemail which handle it themselves)
            if call_mode == "twilio" and twilio_call_sid and outcome not in (CallOutcome.TRANSFERRED, CallOutcome.VOICEMAIL):
                try:
                    from app.services.twilio_voice_service import hangup_twilio_call
                    if self._verbose:
                        print(f"[CallOrchestrator] Hanging up Twilio call SID={twilio_call_sid}")
                    await asyncio.to_thread(hangup_twilio_call, twilio_call_sid)
                except Exception as e:
                    logger.warning("Failed to hang up Twilio call %s: %s", twilio_call_sid, e)

            self._current_call = None
            self._current_patient = None
            self._voice_service = None
            self._twilio_bridge = None

            call_log_provider = get_call_log_provider()
            await call_log_provider.end_call(call.call_id, outcome)

            if patient:
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
        """Send audio from the patient (browser) to OpenAI."""
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
        elif speaker == "patient":
            await call_log_provider.add_transcript(self._current_call.call_id, "patient", text)
            if self.on_transcript_update:
                await self.on_transcript_update("patient", text)
            if (
                self._call_mode == "web"
                and not self._web_voicemail_simulated
                and looks_like_voicemail_signal(text)
            ):
                self._web_voicemail_simulated = True
                await call_log_provider.update_call(self._current_call.call_id, voicemail_left=True)
                self._current_call.voicemail_left = True
                if self.on_status_update:
                    await self.on_status_update("Web simulation: voicemail detected from transcript")
                await self.end_call(CallOutcome.VOICEMAIL)
        elif speaker == "ai":
            if self.on_transcript_update:
                await self.on_transcript_update("ai_delta", text)

    async def _handle_audio(self, audio_data: bytes):
        """Handle audio output from voice service."""
        if self.on_audio_output:
            await self.on_audio_output(audio_data)

    async def _handle_function_call(self, name: str, args: dict, fn_call_id: str = ""):
        """Handle function calls from AI."""
        if not self._current_call:
            return

        self._sync_status_callback()

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
        cfg = getattr(settings, "calcom_config", {}) or {}
        cfg_event_type_id = cfg.get("event_type_id")
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
            or cfg.get("default_timezone")
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
        cfg = getattr(settings, "calcom_config", {}) or {}
        event_type_id = cfg.get("event_type_id")
        if not event_type_id:
            return {"booked": False, "error": "calcom_not_configured"}

        tz = (
            _default_timezone_for_state(self._current_patient.state)
            or cfg.get("default_timezone")
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
        """Send a one-pager follow-up email to the lead.

        For v1 this just records the intent — actual SMTP delivery reuses the
        existing `email_notification_service` if configured.
        """
        from app.services.email_notification_service import send_followup_email

        if not self._current_patient or not self._current_call:
            return {"sent": False, "error": "no_active_call"}

        email = str(args.get("invitee_email", "") or "").strip()
        if not email:
            return {"sent": False, "error": "missing_email"}

        message_type = str(args.get("message_type", "one_pager"))
        custom_note = str(args.get("custom_note", "") or "").strip()
        sales = {}
        try:
            settings = await get_settings_provider().get_settings()
            sales = getattr(settings, "sales_context", {}) or {}
        except Exception:
            pass

        try:
            ok = await send_followup_email(
                to_email=email,
                lead_name=self._current_patient.name,
                firm_name=self._current_patient.firm_name or "",
                message_type=message_type,
                custom_note=custom_note,
                rep_name=sales.get("rep_name", ""),
                rep_company=sales.get("rep_company", ""),
                rep_email=sales.get("rep_email", ""),
            )
        except Exception as e:
            logger.warning("send_followup_email failed: %s", e)
            return {"sent": False, "error": str(e)}

        call_log_provider = get_call_log_provider()
        await call_log_provider.update_call(
            self._current_call.call_id,
            followup_email_sent=bool(ok),
        )
        self._current_call.followup_email_sent = bool(ok)
        return {"sent": bool(ok)}

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
