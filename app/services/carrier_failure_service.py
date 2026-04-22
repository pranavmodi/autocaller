"""Carrier failure detection and handling extracted from CallOrchestrator."""
import logging
from typing import Optional, Callable, Any

from app.models import CallLog, CallOutcome, Patient
from app.providers import get_call_log_provider, get_patient_provider

logger = logging.getLogger(__name__)


def parse_int_or_none(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def map_twilio_failure_reason(
    call_status: str,
    error_code: Optional[int],
    sip_response_code: Optional[int],
) -> str:
    code_map = {
        32009: "invalid number",
        32005: "disconnected/unreachable number",
    }
    if error_code in code_map:
        detail = code_map[error_code]
    elif error_code is not None and 32000 <= error_code <= 32999:
        detail = "carrier failure"
    else:
        detail = "call failed"

    parts = [f"Twilio {call_status}", detail]
    if error_code is not None:
        parts.append(f"error_code={error_code}")
    if sip_response_code is not None:
        parts.append(f"sip_response_code={sip_response_code}")
    return " | ".join(parts)


def is_carrier_failure(
    call_status: str,
    error_code: Optional[int],
    sip_response_code: Optional[int],
) -> bool:
    status = (call_status or "").strip().lower()
    if status == "failed":
        return True
    if status in {"busy", "no-answer"} and (error_code is not None or sip_response_code is not None):
        return True
    return False


def is_known_invalid_number_code(error_code: Optional[int]) -> bool:
    return error_code in {32005, 32009}


def is_known_invalid_number_sip_code(sip_response_code: Optional[int]) -> bool:
    return sip_response_code in {404, 410, 484, 604}


def should_flag_invalid_number(
    error_code: Optional[int],
    sip_response_code: Optional[int],
    reason_text: str,
) -> bool:
    if is_known_invalid_number_code(error_code):
        return True
    if is_known_invalid_number_sip_code(sip_response_code):
        return True
    return looks_like_disconnected_or_invalid(reason_text)


def looks_like_disconnected_or_invalid(error_text: str) -> bool:
    text = (error_text or "").lower()
    keywords = (
        "disconnected",
        "invalid",
        "not in service",
        "unreachable",
        "failed to route",
        "does not exist",
        "cannot be completed",
    )
    return any(k in text for k in keywords)


class CarrierFailureHandler:
    """Handles Twilio carrier failure status callbacks."""

    def __init__(self, get_current_call, get_current_patient, get_twilio_call_sid, end_call_fn):
        self._get_current_call = get_current_call
        self._get_current_patient = get_current_patient
        self._get_twilio_call_sid = get_twilio_call_sid
        self._end_call = end_call_fn
        self.on_status_update: Optional[Callable[[str], Any]] = None
        self.verbose: bool = False

    async def _log_call_event(self, call_id: str, message: str):
        call_log_provider = get_call_log_provider()
        await call_log_provider.add_transcript(call_id, "system", message)

    async def handle_twilio_call_status(
        self,
        call_sid: str,
        call_status: str,
        error_code_raw: str = "",
        sip_response_code_raw: str = "",
    ):
        """Handle Twilio failed/busy/no-answer callback statuses with carrier code mapping."""
        current_call = self._get_current_call()
        twilio_call_sid = self._get_twilio_call_sid()
        if not current_call or not call_sid or call_sid != twilio_call_sid:
            return

        error_code = parse_int_or_none(error_code_raw)
        sip_response_code = parse_int_or_none(sip_response_code_raw)
        status = (call_status or "").strip().lower()
        if not status:
            return
        if not is_carrier_failure(status, error_code, sip_response_code):
            if self.verbose:
                parts = [f"SID={call_sid}", f"status={status}"]
                if sip_response_code is not None:
                    parts.append(f"sip_code={sip_response_code}")
                print(f"[TwilioStatus] {' | '.join(parts)}")
            return

        reason = map_twilio_failure_reason(status, error_code, sip_response_code)
        code_str = str(error_code) if error_code is not None else f"twilio_{status}"
        print(f"[CarrierFailure] Call {current_call.call_id}: {reason}")

        call_log_provider = get_call_log_provider()
        await call_log_provider.update_call(
            current_call.call_id,
            error_code=code_str,
            error_message=reason,
        )
        current_call.error_code = code_str
        current_call.error_message = reason
        await self._log_call_event(current_call.call_id, f"Carrier failure detected: {reason}")

        current_patient = self._get_current_patient()
        if should_flag_invalid_number(error_code, sip_response_code, reason) and current_patient:
            patient_provider = get_patient_provider()
            await patient_provider.mark_patient_invalid_number(current_patient.patient_id, reason)
            await self._log_call_event(
                current_call.call_id,
                f"Patient flagged invalid_number (no retry): {reason}",
            )
            if self.on_status_update:
                await self.on_status_update("Patient flagged as invalid/disconnected number (no retry)")

        if self.on_status_update:
            await self.on_status_update(f"Twilio carrier failure: {reason}")
        await self._end_call(CallOutcome.FAILED, ended_by="carrier_failure")
