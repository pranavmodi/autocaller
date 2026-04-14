"""Transfer routing service extracted from CallOrchestrator."""
import asyncio
import json
import logging
import os
from typing import Optional, Callable, Any

from app.models import CallLog, CallOutcome, Patient
from app.providers import get_queue_provider, get_call_log_provider

logger = logging.getLogger(__name__)


def normalize_language_code(language: Optional[object]) -> str:
    if language is None:
        return "en"
    value = getattr(language, "value", language)
    normalized = str(value).strip().lower()
    return normalized or "en"


def _load_json_object_env(var_name: str) -> dict[str, str]:
    raw = os.getenv(var_name, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {
                str(k).strip().lower(): str(v).strip()
                for k, v in parsed.items()
                if str(v).strip()
            }
    except Exception as e:
        logger.warning("Invalid JSON in %s: %s (raw value: %r)", var_name, e, raw[:200])
    return {}


def resolve_transfer_queue_for_language(language: Optional[object]) -> str:
    language_code = normalize_language_code(language)

    default_map = {
        "en": "9006",
        "es": "9009",
        "zh": "9012",
    }
    configured_map = _load_json_object_env("LANGUAGE_QUEUE_MAP")
    mapping = {**default_map, **configured_map}
    return mapping.get(language_code) or mapping.get("en", "9006")


def resolve_transfer_destination_for_queue(queue_name: str) -> Optional[str]:
    configured_targets = _load_json_object_env("QUEUE_TRANSFER_TARGETS")
    if queue_name in configured_targets:
        return configured_targets[queue_name]
    env_name = f"TRANSFER_TARGET_{queue_name.upper()}"
    value = os.getenv(env_name, "").strip()
    if value:
        return value
    return None


def find_queue_by_name(queue_state, queue_name: str):
    for queue in queue_state.queues:
        if (queue.Queue or "").strip().lower() == queue_name.strip().lower():
            return queue
    return None



def looks_like_voicemail_signal(text: str) -> bool:
    """Detect voicemail / IVR / auto-attendant phrases in caller-side audio.

    Matches generously — false positives here (hanging up on a confused
    human early) are far cheaper than false negatives (the AI rambling
    to a phone tree for 3 minutes).
    """
    lowered = (text or "").lower()
    phrases = (
        # Classic voicemail
        "leave a message",
        "at the tone",
        "after the beep",
        "cannot take your call",
        "not available right now",
        "i'm not available",
        "im not available",
        "please leave your name",
        "leave your name",
        "leave your number",
        "leave your name and number",
        "voice mail",
        "voicemail",
        "record your message",
        "the mailbox",
        "mailbox is full",
        "mailbox belonging",
        # Phone-tree / IVR
        "press 1",
        "press 2",
        "press 3",
        "press 0",
        "press zero",
        "press one",
        "press two",
        "press three",
        "press nine",
        "for the operator",
        "dial by name",
        "directory, press",
        "know your party",
        "your party's extension",
        "your call is very important",
        "this call may be monitored",
        "this call may be recorded",
        "please wait while we connect",
        "have not received a valid response",
        "currently closed",
        "our office hours",
        "please call back during",
        # Spanish IVR prompts — stay in English
        "para español",
        "oprima",
        "marque uno",
        "marque dos",
        "marque tres",
        "marque cinco",
        # Scripted firm greeting
        "thank you for calling",
    )
    if any(p in lowered for p in phrases):
        return True
    return "leave your" in lowered and ("name" in lowered or "number" in lowered)


class TransferService:
    """Resolves transfer queues and executes transfers."""

    def __init__(self):
        self.on_status_update: Optional[Callable[[str], Any]] = None

    async def _log_call_event(self, call_id: str, message: str):
        call_log_provider = get_call_log_provider()
        await call_log_provider.add_transcript(call_id, "system", message)

    def resolve_queue(self, language: Optional[object]) -> str:
        return resolve_transfer_queue_for_language(language)

    def check_capacity(self, queue_state, target_queue: str) -> tuple[Optional[object], bool]:
        """Return (queue_info, has_capacity) for the target queue.

        For transfer decisions: checks the target queue has available agents
        and the system has a connected queue source.  Does NOT require the
        stability hysteresis used for initiating new outbound calls — the
        patient is already on the line, so we just need an agent ready.
        """
        queue_info = find_queue_by_name(queue_state, target_queue)
        if queue_info is None:
            return None, False
        has_capacity = (
            queue_state.ami_connected
            and queue_info.AvailableAgents >= 1
            and queue_state.global_agents_available >= 1
        )
        return queue_info, has_capacity

    async def execute_transfer(
        self,
        call: CallLog,
        patient: Optional[Patient],
        call_mode: str,
        twilio_call_sid: Optional[str],
        notification_service,
        mock_mode: bool = False,
        mock_phone: str = "",
    ) -> CallOutcome:
        """Execute the full transfer flow. Returns the resulting CallOutcome."""
        call_log_provider = get_call_log_provider()
        await call_log_provider.update_call(call.call_id, transfer_attempted=True)

        patient_language = normalize_language_code(
            patient.language if patient else None
        )
        target_queue = resolve_transfer_queue_for_language(
            patient.language if patient else None
        )

        queue_provider = get_queue_provider()
        queue_state = queue_provider.get_state()
        queue_info, has_capacity = self.check_capacity(queue_state, target_queue)

        if queue_info is None:
            await self._log_call_event(
                call.call_id,
                f"Transfer blocked: target queue '{target_queue}' not found for language '{patient_language}'",
            )
            if self.on_status_update:
                await self.on_status_update(
                    f"Transfer unavailable for language '{patient_language}' (queue not configured)"
                )
            await notification_service.send_sms_for_call(
                call=call, patient=patient,
                message_type="callback_info", reason="transfer_queue_missing",
                call_mode=call_mode,
                mock_mode=mock_mode,
                mock_phone=mock_phone,
            )
            return CallOutcome.CALLBACK_REQUESTED

        if not has_capacity:
            await self._log_call_event(
                call.call_id,
                (
                    f"Transfer unavailable: queue '{target_queue}' has no capacity "
                    f"(available_agents={queue_info.AvailableAgents}, "
                    f"outbound_allowed={queue_state.outbound_allowed})"
                ),
            )
            if self.on_status_update:
                await self.on_status_update("Transfer not available - target language queue busy")
            await notification_service.send_sms_for_call(
                call=call, patient=patient,
                message_type="callback_info", reason="transfer_queue_unavailable",
                call_mode=call_mode,
                mock_mode=mock_mode,
                mock_phone=mock_phone,
            )
            return CallOutcome.CALLBACK_REQUESTED

        transfer_context = (
            f"lang={patient_language} queue={target_queue} "
            f"available_agents={queue_info.AvailableAgents}"
        )
        await self._log_call_event(call.call_id, f"Transfer target resolved: {transfer_context}")

        if call_mode == "twilio":
            destination = resolve_transfer_destination_for_queue(target_queue)
            if not destination:
                await self._log_call_event(
                    call.call_id,
                    f"Transfer blocked: no destination configured for queue '{target_queue}'",
                )
                if self.on_status_update:
                    await self.on_status_update(
                        f"Transfer unavailable for queue '{target_queue}' (missing destination config)"
                    )
                await notification_service.send_sms_for_call(
                    call=call, patient=patient,
                    message_type="callback_info", reason="transfer_destination_missing",
                    call_mode=call_mode,
                    mock_mode=mock_mode,
                    mock_phone=mock_phone,
                )
                return CallOutcome.CALLBACK_REQUESTED

            if not twilio_call_sid:
                await self._log_call_event(
                    call.call_id,
                    "Transfer blocked: active Twilio call SID unavailable",
                )
                if self.on_status_update:
                    await self.on_status_update("Transfer unavailable right now; callback SMS sent")
                await notification_service.send_sms_for_call(
                    call=call, patient=patient,
                    message_type="callback_info", reason="transfer_missing_twilio_sid",
                    call_mode=call_mode,
                    mock_mode=mock_mode,
                    mock_phone=mock_phone,
                )
                return CallOutcome.CALLBACK_REQUESTED

            try:
                from app.services.twilio_voice_service import transfer_call_to_destination
                # Pass the patient's original phone as the caller ID so the
                # scheduler sees the actual patient number, not our Twilio DID.
                patient_caller_id = patient.phone if patient and patient.phone else None
                await asyncio.to_thread(
                    transfer_call_to_destination,
                    twilio_call_sid,
                    destination,
                    patient_caller_id,
                )
                await self._log_call_event(
                    call.call_id,
                    f"Twilio transfer initiated to queue '{target_queue}' destination='{destination}' caller_id='{patient_caller_id or ''}'",
                )
            except Exception as e:
                await self._log_call_event(
                    call.call_id,
                    f"Transfer failed for queue '{target_queue}': {str(e)}",
                )
                if self.on_status_update:
                    await self.on_status_update(
                        f"Transfer failed for queue '{target_queue}'; callback SMS sent"
                    )
                await notification_service.send_sms_for_call(
                    call=call, patient=patient,
                    message_type="callback_info", reason="transfer_failed",
                    call_mode=call_mode,
                    mock_mode=mock_mode,
                    mock_phone=mock_phone,
                )
                return CallOutcome.CALLBACK_REQUESTED

        await call_log_provider.update_call(call.call_id, transfer_success=True)
        if self.on_status_update:
            await self.on_status_update(
                f"Transferring to scheduler queue '{target_queue}' ({patient_language})..."
            )
        return CallOutcome.TRANSFERRED
